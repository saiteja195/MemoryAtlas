"""Runs the demo-act questions against a played day and scores them."""
from pathlib import Path
from typing import Any

import yaml

from .config import ROOT

ACTS_PATH = ROOT / "fixtures" / "demo_day" / "acts.yaml"


def load_acts(path: Path = ACTS_PATH) -> dict[str, list[dict[str, Any]]]:
    return yaml.safe_load(path.read_text())


def score(item: dict[str, Any], out: dict[str, Any], abstain: bool = False) -> list[str]:
    """Returns the list of problems (empty means it passed)."""
    if abstain:
        return [] if out["status"] == "abstained" else [f"expected abstention, got {out['status']}"]
    problems = []
    if out["status"] == "abstained":      # a careful "partial" that holds the facts is fine
        problems.append("abstained")
    text = out["answer"].lower()
    problems += [f"missing {s!r}" for s in item.get("expect", []) if s.lower() not in text]
    import re
    problems += [f"starts with {w!r}" for w in item.get("forbid_start", [])
                 if re.match(rf"\s*{re.escape(w)}\b", out["answer"], re.I)]
    any_of = item.get("any_of")
    if any_of and not any(s.lower() in text for s in any_of):
        problems.append(f"none of {any_of}")
    if not out["cited_claim_ids"]:
        problems.append("no citations")
    return problems


def run_group(recall, items: list[dict[str, Any]], abstain: bool = False) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        out = recall.ask(item["question"])
        rows.append({"question": item["question"], "problems": score(item, out, abstain),
                     "out": out})
    return rows
