"""Types shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Signal:
    account_id: str
    kind: str                 # key in config/signals.json
    observed_on: date
    detail: str = ""          # human-readable evidence, shown to the seller


@dataclass
class Account:
    account_id: str
    name: str
    specialty: str = ""
    locations: int = 1
    has_medical_director: bool = False
    in_covered_territory: bool = True
    owner: Optional[str] = None
    is_customer: bool = False
    has_open_opportunity: bool = False
    last_seller_touch: Optional[date] = None


@dataclass
class Score:
    account_id: str
    fit: int
    intent: float
    priority: float
    reasons: list[str] = field(default_factory=list)     # strongest first
    sources: set[str] = field(default_factory=set)


@dataclass
class Action:
    account_id: str
    kind: str                 # sdr_task | owner_task | expansion_play | nurture | none
    assignee: Optional[str]
    why: str                  # the rule that decided it
    note: str = ""            # what the seller reads
