"""Account signals -> explainable priority -> capacity-aware seller actions."""
import json
from pathlib import Path


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "signals.json"
    return json.loads(p.read_text())
