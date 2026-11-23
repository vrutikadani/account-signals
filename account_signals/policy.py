"""Decide what happens to each scored account. Deterministic, ordered, and explainable.

A signal has no value until it changes what someone does, and sellers have a fixed
number of hours. So the policy works down the ranked list and stops assigning when a
rep's daily capacity is used up, instead of creating tasks nobody will work.

Order of rules (first match wins):
  1. Below the act threshold                     -> none
  2. Touched by a seller inside the cooldown      -> none (don't double-tap)
  3. Open opportunity                             -> owner_task (context for the AE, not a new sequence)
  4. Existing customer                            -> expansion_play for the account owner
  5. High intent but fit below the seller bar     -> nurture (marketing, not seller time)
  6. Owned account                                -> owner_task
  7. Unowned                                      -> sdr_task, round-robin

Every task that lands on a rep (rules 3, 4, 6, 7) counts against that rep's daily cap.
Over the cap -> none, marked as overflow in `why`. Overflow is reported, not carried:
nothing here schedules it for tomorrow; the next daily run re-scores from scratch.
An open opportunity or customer with no owner goes to the named unassigned queue
(`policy.unassigned_queue`) with the reason, for someone to assign an owner.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from .model import Account, Action, Score


def decide(scored: list[tuple[Account, Score]], cfg: dict, today: date, sdr_pool: list[str]) -> list[Action]:
    p = cfg["policy"]
    load: Counter[str] = Counter()
    actions: list[Action] = []
    rr = 0

    def has_capacity(rep: str) -> bool:
        return load[rep] < p["max_new_tasks_per_rep_per_day"]

    def to_owner(acct: Account, kind: str, why: str) -> Action:
        if not acct.owner:
            return Action(acct.account_id, kind, p["unassigned_queue"], f"{why}; no owner on record, needs assignment")
        if not has_capacity(acct.owner):
            return Action(acct.account_id, "none", acct.owner, f"{why}; owner at daily capacity: overflow, not assigned")
        load[acct.owner] += 1
        return Action(acct.account_id, kind, acct.owner, why)

    for acct, s in sorted(scored, key=lambda pair: pair[1].intent, reverse=True):
        if s.intent < p["act_threshold"]:
            actions.append(Action(acct.account_id, "none", None, f"intent {s.intent} below {p['act_threshold']}"))
            continue
        if acct.last_seller_touch and (today - acct.last_seller_touch).days < p["cooldown_days"]:
            actions.append(Action(acct.account_id, "none", acct.owner,
                                  f"touched {(today - acct.last_seller_touch).days}d ago, cooldown {p['cooldown_days']}d"))
            continue
        if acct.has_open_opportunity:
            actions.append(to_owner(acct, "owner_task", "open opportunity: give the AE the context"))
            continue
        if acct.is_customer:
            actions.append(to_owner(acct, "expansion_play", "existing customer showing new intent"))
            continue
        if s.priority == 0:
            actions.append(Action(acct.account_id, "nurture", None, "intent without fit: marketing, not seller time"))
            continue
        if acct.owner:
            actions.append(to_owner(acct, "owner_task", "owned account"))
            continue
        for _ in range(len(sdr_pool)):
            rep = sdr_pool[rr % len(sdr_pool)]
            rr += 1
            if has_capacity(rep):
                load[rep] += 1
                actions.append(Action(acct.account_id, "sdr_task", rep, "unowned, routed round-robin"))
                break
        else:
            actions.append(Action(acct.account_id, "none", None, "all SDRs at daily capacity: overflow, not assigned"))
    return actions
