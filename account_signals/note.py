"""The seller-facing note: the only place a language model is allowed in.

The model receives the decided action and the reasons, and writes two sentences a
seller can act on. It never sees raw signals it could reinterpret, and nothing it
writes flows back into the score or the action. If the model is unavailable or its
output fails the checks, the template note is used instead.
"""
from __future__ import annotations

import os

from .model import Account, Action, Score

TEMPLATE = "{name}: {why}. Signals: {reasons}."
MAX_CHARS = 280


def template_note(acct: Account, s: Score, a: Action) -> str:
    return TEMPLATE.format(name=acct.name, why=a.why, reasons="; ".join(s.reasons) or "none")


def write_note(acct: Account, s: Score, a: Action, llm=None) -> str:
    fallback = template_note(acct, s, a)
    if llm is None:
        return fallback
    prompt = (f"Write a two-sentence note for a seller. Account: {acct.name}. Action: {a.kind} ({a.why}). "
              f"Evidence: {'; '.join(s.reasons)}. Use only this evidence. No hype.")
    try:
        text = llm(prompt).strip()
    except Exception:
        return fallback
    # Reject notes that are too long or that cite evidence we didn't give it.
    if not text or len(text) > MAX_CHARS or acct.name.split()[0] not in text:
        return fallback
    return text


def claude_writer():  # pragma: no cover - needs a key
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    import anthropic
    client = anthropic.Anthropic()

    def call(prompt: str) -> str:
        msg = client.messages.create(model="claude-sonnet-4-5", max_tokens=120,
                                     messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text
    return call
