from datetime import date, timedelta

import pytest

from account_signals import load_config
from account_signals.model import Account, Action, Score, Signal
from account_signals.note import template_note, write_note
from account_signals.policy import decide
from account_signals.score import decay, score_account

TODAY = date(2026, 10, 1)
CFG = load_config()


def acct(**kw):
    base = dict(account_id="A1", name="Glow Derm", specialty="Dermatology", has_medical_director=True)
    base.update(kw)
    return Account(**base)


def sig(kind, days_ago, aid="A1"):
    return Signal(aid, kind, TODAY - timedelta(days=days_ago))


# ---------------- scoring
def test_decay_halves_at_half_life():
    assert decay(7, 7) == pytest.approx(0.5)
    assert decay(0, 7) == 1.0


def test_recent_beats_old():
    new = score_account(acct(), [sig("pricing_page_visit", 1)], CFG, TODAY)
    old = score_account(acct(), [sig("pricing_page_visit", 60)], CFG, TODAY)
    assert new.intent > old.intent * 5


def test_one_noisy_source_is_capped():
    spam = [sig("intent_topic_surge", 0) for _ in range(30)]
    s = score_account(acct(), spam, CFG, TODAY)
    assert s.intent == CFG["per_source_cap"]


def test_independent_sources_earn_a_bonus():
    one = score_account(acct(), [sig("pricing_page_visit", 0)], CFG, TODAY)
    two = score_account(acct(), [sig("pricing_page_visit", 0), sig("email_reply_positive", 0)], CFG, TODAY)
    assert two.intent == pytest.approx((25 + 35) * 1.25)
    assert two.intent > one.intent + 35


def test_poor_fit_gets_no_seller_priority_but_keeps_intent():
    s = score_account(acct(specialty="Dental", has_medical_director=False),
                      [sig("pricing_page_visit", 0), sig("email_reply_positive", 0)], CFG, TODAY)
    assert s.intent > 0 and s.priority == 0
    assert any("below seller bar" in r for r in s.reasons)


def test_unknown_signal_types_are_ignored():
    assert score_account(acct(), [sig("made_up_signal", 0)], CFG, TODAY).intent == 0


def test_reasons_are_strongest_first():
    s = score_account(acct(), [sig("webinar_attended", 30), sig("email_reply_positive", 0)], CFG, TODAY)
    assert s.reasons[0].startswith("email reply positive")


def test_reasons_do_not_repeat_a_signal_type():
    s = score_account(acct(), [sig("champion_job_change", d) for d in (0, 5, 9)] + [sig("pricing_page_visit", 2)],
                      CFG, TODAY)
    assert sum("champion job change" in r for r in s.reasons) == 1


# ---------------- policy
def scored(a, intent, priority=None):
    return (a, Score(a.account_id, 60, intent, intent if priority is None else priority))


def test_policy_rule_order():
    rows = [
        scored(acct(account_id="low"), 10),
        scored(acct(account_id="cool", last_seller_touch=TODAY - timedelta(days=3)), 90),
        scored(acct(account_id="opp", has_open_opportunity=True, owner="AE-1"), 90),
        scored(acct(account_id="cust", is_customer=True, owner="AM-1"), 90),
        scored(acct(account_id="nofit"), 90, priority=0),
        scored(acct(account_id="owned", owner="AE-1"), 90),
        scored(acct(account_id="free"), 90),
    ]
    got = {a.account_id: a.kind for a in decide(rows, CFG, TODAY, ["SDR-1"])}
    assert got == {"low": "none", "cool": "none", "opp": "owner_task", "cust": "expansion_play",
                   "nofit": "nurture", "owned": "owner_task", "free": "sdr_task"}


def test_capacity_carries_work_to_tomorrow_instead_of_overloading():
    cap = CFG["policy"]["max_new_tasks_per_rep_per_day"]
    rows = [scored(acct(account_id=f"A{i}"), 100 - i) for i in range(cap + 3)]
    acts = decide(rows, CFG, TODAY, ["SDR-1"])
    assert sum(a.kind == "sdr_task" for a in acts) == cap
    carried = [a for a in acts if a.kind == "none"]
    assert len(carried) == 3 and all("capacity" in a.why for a in carried)
    # the highest-intent accounts got the slots
    assert {a.account_id for a in acts if a.kind == "sdr_task"} == {f"A{i}" for i in range(cap)}


# ---------------- note: the model can write words, not decisions
def test_note_falls_back_when_model_fails_or_misbehaves():
    a, s = acct(), Score("A1", 60, 80, 80, ["pricing page (1d ago)"])
    act = Action("A1", "sdr_task", "SDR-1", "unowned, routed round-robin")
    assert write_note(a, s, act, llm=lambda p: 1 / 0) == template_note(a, s, act)
    assert write_note(a, s, act, llm=lambda p: "x" * 500) == template_note(a, s, act)
    assert write_note(a, s, act, llm=lambda p: "Call them today.") == template_note(a, s, act)  # no account name
    ok = "Glow Derm hit the pricing page yesterday. Worth a call today."
    assert write_note(a, s, act, llm=lambda p: ok) == ok
