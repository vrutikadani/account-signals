"""Backtest: does this ranking beat the obvious alternatives at seller capacity?

The question is never "is the score accurate," it's "if sellers can only work K accounts
this week, which list gets them more meetings?" So each method ranks the same accounts,
we take the top K, and count how many booked a meeting in the next 30 days.

Compared:
  signal count   - the default most teams start with: more signals = hotter
  no guards      - this model with decay, source caps and the fit gate switched off
  this model     - decay + source caps + diversity bonus + fit gate

Data is synthetic (data/generate.py): each account has a hidden propensity; real buyers
emit a mix of signals, and one third-party intent feed fires noisily for everyone.

    python backtest.py
"""
from __future__ import annotations

import copy
import random
from datetime import date

from account_signals import load_config
from account_signals.score import score_account
from data.generate import make_world

TODAY = date(2026, 10, 1)


def top_k_hits(ranked_ids: list[str], outcomes: dict[str, bool], k: int) -> int:
    return sum(outcomes[a] for a in ranked_ids[:k])


def run(seed: int = 7, k: int = 40, verbose: bool = True) -> dict:
    cfg = load_config()
    accounts, signals, outcomes = make_world(seed=seed, today=TODAY)
    by_acct: dict[str, list] = {a.account_id: [] for a in accounts}
    for s in signals:
        by_acct[s.account_id].append(s)

    naive = sorted(accounts, key=lambda a: len(by_acct[a.account_id]), reverse=True)

    unguarded = copy.deepcopy(cfg)
    for k_ in unguarded["signals"].values():
        k_["half_life_days"] = 10_000
    unguarded["per_source_cap"] = 10_000
    unguarded["independent_sources_bonus"]["multiplier"] = 1.0
    unguarded["fit"]["min_fit_for_seller_action"] = 0

    def rank(c):
        scored = [(a.account_id, score_account(a, by_acct[a.account_id], c, TODAY).priority) for a in accounts]
        return [a for a, _ in sorted(scored, key=lambda x: x[1], reverse=True)]

    rnd = [a.account_id for a in accounts]
    random.Random(seed).shuffle(rnd)

    base_rate = sum(outcomes.values()) / len(outcomes)
    results = {
        "random": top_k_hits(rnd, outcomes, k),
        "signal count": top_k_hits([a.account_id for a in naive], outcomes, k),
        "no guards": top_k_hits(rank(unguarded), outcomes, k),
        "this model": top_k_hits(rank(cfg), outcomes, k),
    }
    if verbose:
        print(f"{len(accounts)} accounts, {sum(outcomes.values())} booked a meeting ({base_rate:.0%} base rate)")
        print(f"Meetings in the top {k} (one week of seller capacity):")
        for name, hits in results.items():
            print(f"  {name:<13} {hits:>3}   {hits / k:.0%} of worked accounts")
    return results


def main(seeds: int = 30, k: int = 40) -> dict:
    """Average over many synthetic worlds; one seed can flatter or punish any method."""
    totals: dict[str, list[int]] = {}
    wins = 0
    for seed in range(seeds):
        r = run(seed, k, verbose=False)
        for name, hits in r.items():
            totals.setdefault(name, []).append(hits)
        wins += r["this model"] > max(v for n, v in r.items() if n != "this model")
    print(f"{seeds} synthetic worlds x 400 accounts, top {k} worked per week")
    print(f"{'method':<13} {'meetings (mean)':>16} {'worst':>6} {'best':>5}")
    for name, hits in totals.items():
        print(f"{name:<13} {sum(hits) / len(hits):>16.1f} {min(hits):>6} {max(hits):>5}")
    print(f"this model ranked strictly first in {wins}/{seeds} worlds")
    return totals


if __name__ == "__main__":
    main()
