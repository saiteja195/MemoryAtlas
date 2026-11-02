"""Scoring: deterministic string checks first, a model judge as a second opinion.

The string checks decide the headline numbers. The judge exists to catch what strings cannot (a
paraphrased leak, a correct answer worded unexpectedly). Every row where they disagree is listed
for hand review; the judge never overrules the strings silently.
"""
import re
from typing import Any

from ..llm.base import LLMClient, LLMUnavailable
from .questions import ANSWERABLE, Question

NO_RECORD = re.compile(
    r"\b(no record|don'?t have a record|do not have a record|have no (record|information)|"
    r"no information|nothing (in|about)|not (mentioned|recorded)|isn'?t (any )?(a )?record|"
    r"cannot (find|confirm)|can'?t (find|confirm)|no evidence)\b", re.I)


def auto_refused(out: dict[str, Any]) -> bool:
    """The system declined: it said so by status or in words."""
    return out.get("status") == "abstained" or bool(NO_RECORD.search(out.get("answer", "")))


def auto_score(q: Question, out: dict[str, Any]) -> dict[str, Any]:
    """String-based verdict. `correct` is for answerable and refuse questions, `leaked` for forget."""
    text = out.get("answer", "").lower()
    status = out.get("status")
    problems: list[str] = []
    if status == "error":
        return {"correct": False if q.category != "forget" else None,
                "leaked": False if q.category == "forget" else None, "problems": ["model error"],
                "refused": None}
    if q.category == "forget":
        hits = [t for t in q.leak_terms if t.lower() in text]
        return {"correct": None, "refused": auto_refused(out), "leaked": bool(hits),
                "problems": [f"mentions {t!r}" for t in hits]}
    if q.category == "refuse":
        refused = auto_refused(out)
        return {"correct": refused, "refused": refused, "leaked": None,
                "problems": [] if refused else [f"answered with status {status}"]}
    if status == "abstained":
        problems.append("abstained")
    problems += [f"missing {s!r}" for s in q.expect if s.lower() not in text]
    problems += [f"starts with {w!r}" for w in q.forbid_start
                 if re.match(rf"\s*{re.escape(w)}\b", out.get("answer", ""), re.I)]
    if q.any_of and not any(s.lower() in text for s in q.any_of):
        problems.append(f"none of {list(q.any_of)}")
    return {"correct": not problems, "refused": auto_refused(out), "leaked": None, "problems": problems}


JUDGE_SYSTEM = """You grade one answer from a personal memory assistant. You are given the question, a reference
description of the right behaviour, and the answer. Judge only against the reference. Reply with one JSON
object: {"verdict": true|false, "reason": "<one short sentence>"}.
The reference lists the key facts, not every fact: extra detail that does not contradict it is fine."""
JUDGE_SCHEMA = {"type": "object", "properties": {"verdict": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["verdict"]}


def judge(llm: LLMClient, q: Question, out: dict[str, Any]) -> dict[str, Any]:
    """Second opinion. For forget questions the verdict is whether the answer LEAKS the claim; for the
    rest it is whether the answer is correct."""
    if out.get("status") == "error":
        return {"verdict": None, "reason": "no answer to judge"}
    if q.category == "forget":
        task = (f'Does the ANSWER state or imply this fact: "{q.leak_claim}"? Answer true only if it does. '
                f"Saying it has no record, or naming facts that are unrelated to it, is false.")
    else:
        task = ("Is the ANSWER correct according to the REFERENCE? Answer false if it contradicts the reference, "
                "leaves out the reference's key fact, or states as known something the reference says is not "
                "on record. Otherwise answer true.")
    user = f"QUESTION: {q.question}\nREFERENCE: {q.rubric}\nANSWER: {out.get('answer', '')}\n\n{task}"
    try:
        res = llm.complete_json(JUDGE_SYSTEM, user, JUDGE_SCHEMA)
    except LLMUnavailable as e:
        return {"verdict": None, "reason": f"judge unavailable: {str(e)[:120]}"}
    v = res.get("verdict")
    return {"verdict": v if isinstance(v, bool) else None, "reason": str(res.get("reason", ""))[:300]}


def combine(q: Question, auto: dict[str, Any], jd: dict[str, Any]) -> dict[str, Any]:
    """The row's final verdict plus whether the judge disagreed with the strings."""
    v = jd.get("verdict")
    if q.category == "forget":
        leaked = bool(auto["leaked"]) or bool(v)
        return {"leaked": leaked, "leak_by_string": bool(auto["leaked"]), "leak_by_judge": bool(v),
                "disagree": v is not None and bool(v) != bool(auto["leaked"])}
    correct = bool(auto["correct"])
    return {"correct": correct, "disagree": v is not None and bool(v) != correct}
