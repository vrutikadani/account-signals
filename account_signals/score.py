"""Turn raw signals into an explainable priority.

priority = intent, but only for accounts that clear a fit bar.

Intent is the sum of each signal's weight, decayed by age. Three guards keep it honest:
  * decay       - a pricing visit from last week matters more than one from last quarter
  * source cap  - twenty intent-topic pings from one vendor can't outscore one real reply
  * diversity   - two independent sources agreeing earn a bonus; one noisy source doesn't
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .model import Account, Score, Signal


def decay(age_days: int, half_life_days: float) -> float:
    return 0.5 ** (max(age_days, 0) / half_life_days)


def fit_score(account: Account, cfg: dict) -> tuple[int, list[str]]:
    f = cfg["fit"]
    pts, why = 0, []
    spec = account.specialty.strip().lower()
    if spec in f["specialty"]:
        pts += f["specialty"][spec]
        why.append(f"{account.specialty} practice")
    if account.has_medical_director:
        pts += f["has_medical_director"]
        why.append("has a medical director")
    if account.locations >= 2:
        pts += f["locations_2_plus"]
        why.append(f"{account.locations} locations")
    if account.in_covered_territory:
        pts += f["in_covered_territory"]
    else:
        why.append("outside rep coverage")
    return pts, why


def score_account(account: Account, signals: list[Signal], cfg: dict, today: date) -> Score:
    kinds = cfg["signals"]
    by_source: dict[str, float] = defaultdict(float)
    contributions: list[tuple[float, str, str]] = []

    for s in signals:
        if s.kind not in kinds:
            continue                     # unknown signal types are ignored, never guessed at
        k = kinds[s.kind]
        value = k["weight"] * decay((today - s.observed_on).days, k["half_life_days"])
        by_source[k["source"]] += value
        age = (today - s.observed_on).days
        label = s.detail or s.kind.replace("_", " ")
        contributions.append((value, f"{label} ({age}d ago)", s.kind))

    cap = cfg["per_source_cap"]
    intent = sum(min(v, cap) for v in by_source.values())
    active_sources = {src for src, v in by_source.items() if v >= 1}
    bonus = cfg["independent_sources_bonus"]
    if len(active_sources) >= bonus["min_sources"]:
        intent *= bonus["multiplier"]

    fit, fit_why = fit_score(account, cfg)
    priority = intent if fit >= cfg["fit"]["min_fit_for_seller_action"] else 0.0

    # Strongest instance of each signal type, top three. Repeating "job change" three
    # times tells a seller nothing new.
    seen, reasons = set(), []
    for value, label, kind in sorted(contributions, reverse=True):
        if kind not in seen:
            seen.add(kind)
            reasons.append(label)
        if len(reasons) == 3:
            break
    if fit < cfg["fit"]["min_fit_for_seller_action"]:
        reasons.append(f"fit {fit} below seller bar ({', '.join(fit_why) or 'no fit signals'})")
    return Score(account.account_id, fit, round(intent, 1), round(priority, 1), reasons, active_sources)
