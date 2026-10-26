"""One daily run on synthetic data: score every account, decide actions, write notes.

    python run_daily.py
"""
from collections import Counter
from datetime import date

from account_signals import load_config
from account_signals.note import claude_writer, write_note
from account_signals.policy import decide
from account_signals.score import score_account
from data.generate import make_world

TODAY = date(2026, 10, 1)
cfg = load_config()
accounts, signals, _ = make_world(seed=7, today=TODAY)
for i, a in enumerate(accounts):           # give the world some owners and history
    a.owner = ["AE-West", "AE-Central", "AE-East"][i % 3] if i % 4 == 0 else None
    a.is_customer = i % 17 == 0
    a.has_open_opportunity = i % 23 == 0

by_acct = {a.account_id: [] for a in accounts}
for s in signals:
    by_acct[s.account_id].append(s)

scored = [(a, score_account(a, by_acct[a.account_id], cfg, TODAY)) for a in accounts]
actions = decide(scored, cfg, TODAY, sdr_pool=["SDR-1", "SDR-2"])
score_of = {a.account_id: (a, s) for a, s in scored}
llm = claude_writer()

print("Actions today:", dict(Counter(x.kind for x in actions)))
print("\nFirst 8 seller tasks:")
for act in [x for x in actions if x.kind in {"sdr_task", "owner_task", "expansion_play"}][:8]:
    acct, s = score_of[act.account_id]
    print(f"  [{act.kind:<14}] {act.assignee:<10} intent {s.intent:>5}  {write_note(acct, s, act, llm)}")

print("\nWhy some high-intent accounts got no seller task:")
for act in [x for x in actions if x.kind in {"nurture", "none"} and score_of[x.account_id][1].intent >= cfg['policy']['act_threshold']][:4]:
    acct, s = score_of[act.account_id]
    print(f"  {acct.name}: intent {s.intent} -> {act.kind}: {act.why}")
