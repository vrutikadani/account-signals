"""The seller-facing note: the only place a language model is allowed in.

The model receives the decided action and the reasons, and writes two sentences a
seller can act on. It never sees raw signals it could reinterpret, and nothing it
writes flows back into the score or the action. If the model is unavailable or its
output fails the checks, the template note is used instead.

The checks are cheap guards, not a fact-checker: the note must name this account
(full name or ID), and every number or claim word in it must already appear in the
evidence it was given. The model path is off unless the caller opts in.
"""
from __future__ import annotations

import os
import re

from .model import Account, Action, Score

TEMPLATE = "{name}: {why}. Signals: {reasons}."
MAX_CHARS = 280
NUMBER = re.compile(r"[$€£]?\d+(?:[.,]\d+)*[%kKmMbB]?")
CLAIM_TERMS = ("budget", "approved", "signed", "contract", "million", "billion",
               "decision maker", "ready to buy", "guarantee")


def template_note(acct: Account, s: Score, a: Action) -> str:
    return TEMPLATE.format(name=acct.name, why=a.why, reasons="; ".join(s.reasons) or "none")


def write_note(acct: Account, s: Score, a: Action, llm=None) -> str:
    fallback = template_note(acct, s, a)
    if llm is None:
        return fallback
    prompt = (f"Write a two-sentence note for a seller. Account: {acct.name}. Action: {a.kind} ({a.why}). "
              f"Evidence: {'; '.join(s.reasons)}. Name the account. Use only this evidence: "
              f"no numbers or facts that aren't in it. No hype.")
    try:
        text = llm(prompt).strip()
    except Exception:
        return fallback
    evidence = " ".join([acct.name, acct.account_id, a.why, *s.reasons])
    if not text or len(text) > MAX_CHARS or not names_account(text, acct) or not grounded(text, evidence):
        return fallback
    return text


def names_account(text: str, acct: Account) -> bool:
    """The full name or the ID, as whole words. "Practice" alone matches every account."""
    return any(re.search(rf"(?<!\w){re.escape(x)}(?!\w)", text) for x in (acct.name, acct.account_id) if x)


def grounded(text: str, evidence: str) -> bool:
    """No number (with its unit) or claim word that the evidence doesn't already contain."""
    if not set(NUMBER.findall(text)) <= set(NUMBER.findall(evidence)):
        return False
    low_text, low_ev = text.lower(), evidence.lower()
    return not any(term in low_text and term not in low_ev for term in CLAIM_TERMS)


def claude_writer(enabled: bool = False):
    """Off by default. Returns a callable only when the caller opts in and a key is set."""
    if not enabled or not os.getenv("ANTHROPIC_API_KEY"):
        return None
    return _anthropic_call()


def _anthropic_call():  # pragma: no cover - needs a key and the optional package
    import anthropic
    client = anthropic.Anthropic()

    def call(prompt: str) -> str:
        msg = client.messages.create(model="claude-sonnet-4-5", max_tokens=120,
                                     messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text
    return call
