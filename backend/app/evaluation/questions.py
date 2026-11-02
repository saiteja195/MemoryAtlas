"""The evaluation question set (eval/questions.yaml)."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import ROOT

QUESTIONS_PATH = ROOT / "eval" / "questions.yaml"
CATEGORIES = ("multi_source", "timing", "correction", "refuse", "forget", "keep")
PHASES = ("day", "after_live", "after_revoke")
ANSWERABLE = ("multi_source", "timing", "correction", "keep")


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    phase: str
    question: str
    rubric: str
    expect: tuple[str, ...] = ()
    any_of: tuple[str, ...] = ()
    forbid_start: tuple[str, ...] = ()
    leak_terms: tuple[str, ...] = ()
    leak_claim: str = ""


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    raw = yaml.safe_load(Path(path).read_text())["questions"]
    out, seen = [], set()
    for r in raw:
        q = Question(
            id=r["id"], category=r["category"], phase=r["phase"], question=r["question"],
            rubric=r["rubric"], expect=tuple(r.get("expect", [])), any_of=tuple(r.get("any_of", [])),
            forbid_start=tuple(r.get("forbid_start", [])), leak_terms=tuple(r.get("leak_terms", [])),
            leak_claim=r.get("leak_claim", ""))
        if q.id in seen:
            raise ValueError(f"duplicate question id {q.id}")
        seen.add(q.id)
        if q.category not in CATEGORIES:
            raise ValueError(f"{q.id}: unknown category {q.category!r}")
        if q.phase not in PHASES:
            raise ValueError(f"{q.id}: unknown phase {q.phase!r}")
        if q.category == "forget" and not (q.leak_terms and q.leak_claim):
            raise ValueError(f"{q.id}: a forget question needs leak_terms and leak_claim")
        if q.category in ANSWERABLE and not (q.expect or q.any_of):
            raise ValueError(f"{q.id}: an answerable question needs expect or any_of")
        if q.category == "forget" and q.phase != "after_revoke":
            raise ValueError(f"{q.id}: forget questions are asked after revocation")
        out.append(q)
    return out
