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


# ---------------- audit fixes: as-of scoring (no future data)
def test_signals_after_today_are_ignored():
    s = score_account(acct(), [sig("email_reply_positive", -20)], CFG, TODAY)
    assert s.intent == 0
    assert not any("-20d" in r for r in s.reasons)


def test_future_signal_does_not_change_a_real_score():
    real = [sig("pricing_page_visit", 2)]
    assert (score_account(acct(), real + [sig("demo_form_abandoned", -3)], CFG, TODAY).intent
            == score_account(acct(), real, CFG, TODAY).intent)


# ---------------- audit fixes: low-trust sources don't earn the diversity bonus
def test_third_party_intent_is_configured_as_low_trust():
    assert "third_party_intent" in CFG["low_trust_sources"]


def test_noise_source_does_not_earn_the_diversity_bonus():
    s = score_account(acct(), [sig("pricing_page_visit", 0), sig("intent_topic_surge", 0)], CFG, TODAY)
    assert s.intent == pytest.approx(25 + 10)


# ---------------- audit fixes: backtest is a dated forward test
def test_generator_outcomes_are_dated_meetings_and_deterministic():
    from data.generate import make_world
    _, _, meetings = make_world(seed=3, today=TODAY)
    assert meetings and all(isinstance(m.booked_on, date) for m in meetings)
    assert any(m.booked_on > TODAY + timedelta(days=30) for m in meetings)   # some fall outside the window
    assert make_world(seed=3, today=TODAY)[2] == meetings


def test_backtest_counts_only_meetings_inside_the_window():
    from account_signals.model import Meeting
    from backtest import meetings_in_window
    ms = [Meeting("before", TODAY - timedelta(days=5)), Meeting("today", TODAY),
          Meeting("first", TODAY + timedelta(days=1)), Meeting("last", TODAY + timedelta(days=30)),
          Meeting("late", TODAY + timedelta(days=31))]
    assert meetings_in_window(ms, TODAY, 30) == {"first", "last"}


def test_backtest_does_not_use_signals_after_today():
    from backtest import run
    from data.generate import make_world
    accounts, signals, meetings = make_world(seed=5, today=TODAY)
    booked = {m.account_id for m in meetings}
    # leak the answer: pile future activity onto every account that never books
    leak = [Signal(a.account_id, k, TODAY + timedelta(days=d)) for a in accounts if a.account_id not in booked
            for k in ("email_reply_positive", "pricing_page_visit", "demo_form_abandoned") for d in (1, 2, 3)]
    clean = run(k=40, verbose=False, world=(accounts, signals, meetings))
    leaky = run(k=40, verbose=False, world=(accounts, signals + leak, meetings))
    assert leaky == clean


# ---------------- audit fixes: capacity on every task-creating branch
def test_open_opportunity_tasks_respect_capacity():
    cap = CFG["policy"]["max_new_tasks_per_rep_per_day"]
    rows = [scored(acct(account_id=f"O{i}", has_open_opportunity=True, owner="AE-1"), 100 - i) for i in range(cap + 3)]
    acts = decide(rows, CFG, TODAY, ["SDR-1"])
    assert sum(a.kind == "owner_task" and a.assignee == "AE-1" for a in acts) == cap


def test_expansion_plays_respect_capacity():
    cap = CFG["policy"]["max_new_tasks_per_rep_per_day"]
    rows = [scored(acct(account_id=f"C{i}", is_customer=True, owner="AM-1"), 100 - i) for i in range(cap + 3)]
    acts = decide(rows, CFG, TODAY, ["SDR-1"])
    assert sum(a.kind == "expansion_play" for a in acts) == cap


def test_capacity_is_shared_across_branches():
    cap = CFG["policy"]["max_new_tasks_per_rep_per_day"]
    rows = ([scored(acct(account_id=f"O{i}", has_open_opportunity=True, owner="AE-1"), 100 - i) for i in range(3)]
            + [scored(acct(account_id=f"C{i}", is_customer=True, owner="AE-1"), 90 - i) for i in range(3)]
            + [scored(acct(account_id=f"W{i}", owner="AE-1"), 80 - i) for i in range(3)])
    acts = decide(rows, CFG, TODAY, ["SDR-1"])
    assert sum(a.assignee == "AE-1" and a.kind != "none" for a in acts) == cap


def test_ownerless_task_goes_to_named_unassigned_queue_with_reason():
    queue = CFG["policy"]["unassigned_queue"]
    rows = [scored(acct(account_id="cust", is_customer=True), 90),
            scored(acct(account_id="opp", has_open_opportunity=True), 90)]
    acts = {a.account_id: a for a in decide(rows, CFG, TODAY, ["SDR-1"])}
    for aid in ("cust", "opp"):
        assert acts[aid].assignee == queue
        assert "no owner" in acts[aid].why


def test_overflow_is_reported_not_claimed_as_carried():
    cap = CFG["policy"]["max_new_tasks_per_rep_per_day"]
    rows = [scored(acct(account_id=f"A{i}"), 100 - i) for i in range(cap + 2)]
    over = [a for a in decide(rows, CFG, TODAY, ["SDR-1"]) if a.kind == "none"]
    assert len(over) == 2
    assert all("overflow" in a.why and "carried" not in a.why for a in over)


# ---------------- audit fixes: the note guard checks identity and evidence
def _note_case(name="Practice 001", aid="A001"):
    a = acct(account_id=aid, name=name)
    s = Score(aid, 60, 80, 80, ["pricing page visit (1d ago)", "email reply positive (3d ago)"])
    return a, s, Action(aid, "sdr_task", "SDR-1", "unowned, routed round-robin")


def test_note_naming_another_account_falls_back():
    a, s, act = _note_case()
    assert write_note(a, s, act, llm=lambda p: "Practice 002 hit pricing. Call today.") == template_note(a, s, act)


def test_note_with_invented_evidence_falls_back():
    a, s, act = _note_case()
    bad = ["Practice 001 has a $2M budget. Call today.",
           "Practice 001 visited pricing 9 times. Call today.",
           "Practice 001 has budget approved. Call today."]
    for text in bad:
        assert write_note(a, s, act, llm=lambda p, t=text: t) == template_note(a, s, act), text


def test_note_grounded_in_reasons_is_kept():
    a, s, act = _note_case()
    ok = "Practice 001 visited pricing 1d ago and replied 3d ago. Worth a call today."
    assert write_note(a, s, act, llm=lambda p: ok) == ok
    by_id = "A001 replied positively 3d ago. Call today."
    assert write_note(a, s, act, llm=lambda p: by_id) == by_id


def test_model_notes_are_off_by_default(monkeypatch):
    from account_signals.note import claude_writer
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    assert claude_writer() is None
