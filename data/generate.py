"""Synthetic world for tests and the backtest. Fixed seed, no real accounts.

Each account gets a hidden propensity. High-propensity, good-fit accounts emit recent,
varied signals. Everyone gets background noise from one third-party intent feed, and
some poor-fit accounts are very "active" (students, competitors, researchers), because
that is what makes naive signal counting fail in practice.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from account_signals.model import Account, Signal

SPECIALTIES = ["dermatology", "plastic surgery", "med spa", "chiropractic", "dental", ""]
BUYER_SIGNALS = ["pricing_page_visit", "demo_form_abandoned", "email_reply_positive", "webinar_attended",
                 "champion_job_change", "hiring_injector_role", "competitor_mentioned"]


def make_world(seed: int = 7, n: int = 400, today: date = date(2026, 10, 1)):
    rng = random.Random(seed)
    accounts, signals, outcomes = [], [], {}
    for i in range(n):
        spec = rng.choices(SPECIALTIES, [25, 15, 25, 12, 12, 11])[0]
        good_fit = spec in {"dermatology", "plastic surgery", "med spa"}
        a = Account(account_id=f"A{i:03d}", name=f"Practice {i:03d}", specialty=spec,
                    locations=rng.choice([1, 1, 1, 2, 3]), has_medical_director=rng.random() < 0.6,
                    in_covered_territory=rng.random() < 0.85)
        accounts.append(a)
        propensity = rng.betavariate(1.2, 6) * (1.0 if good_fit else 0.25)

        # real buying behaviour: more, more recent, more varied signals
        for _ in range(int(propensity * 14)):
            signals.append(Signal(a.account_id, rng.choice(BUYER_SIGNALS),
                                  today - timedelta(days=int(rng.expovariate(1 / 12)))))
        # noisy third-party feed fires for everyone, often
        for _ in range(rng.randint(0, 6)):
            signals.append(Signal(a.account_id, "intent_topic_surge", today - timedelta(days=rng.randint(0, 90))))
        # poor-fit but busy accounts (students, competitors, researchers)
        if not good_fit and rng.random() < 0.25:
            for _ in range(rng.randint(4, 10)):
                signals.append(Signal(a.account_id, rng.choice(["pricing_page_visit", "webinar_attended"]),
                                      today - timedelta(days=rng.randint(0, 120))))
        # old activity that no longer means much
        for _ in range(rng.randint(0, 3)):
            signals.append(Signal(a.account_id, rng.choice(BUYER_SIGNALS),
                                  today - timedelta(days=rng.randint(120, 365))))
        outcomes[a.account_id] = rng.random() < min(0.9, propensity * 1.6)
    return accounts, signals, outcomes
