"""AI #2: the Recall Investigator.

A bounded tool-using loop on Muse Spark. Each step the model returns one JSON action: call a
tool, or give the final answer. The loop is built on `complete_json` (so record/replay covers
it); native tool calling is not used. Deterministic post-checks then decide whether the answer
may be returned. The model is stateless per question: no earlier chat turns are fed back.
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..llm.base import LLMClient, LLMUnavailable
from ..llm.metered import usage_purpose
from ..privacy.filter import HISTORY, authorized_claim_ids
from .tools import RecallTools

MAX_STEPS = 6
RESULT_CHARS = 12000
CLAIM_ID_RE = re.compile(r"clm-[0-9a-f]{12}")
LAST_SEEN_RE = re.compile(r"\blast (confirmed )?(sighting|seen)\b", re.I)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
# A question that only compares when two things happened ("did I see X before or after Y?") is not asking where
# anything is, so it needs no "last confirmed sighting" wording. Anything that asks where, whether something was
# left, moved or is still somewhere keeps the strict phrasing: when in doubt the check applies.
ORDER_RE = re.compile(r"\b(before|after|earlier|later|first|sooner|prior to|ahead of|preceded|followed)\b", re.I)
PLACE_RE = re.compile(r"\b(where|left|leave|leaving|still|find|found|located|location|moved|move|put|keep|kept|"
                      r"whereabouts|sighting|last (?:see|saw|seen))\b", re.I)

SYSTEM = """You answer questions about the user's own day using a graph of remembered claims.
You can only learn facts by calling tools. Every step, reply with ONE JSON object, either

 {"action":"tool","tool":"<name>","args":{...}}
or
 {"action":"final","status":"answered|partial|abstained","answer":"...",
  "cited_claim_ids":["clm-..."],"uncertainty_note":"..."}

Tools:
 search_claims(query, k?, time_from?, time_to?, predicate?)  hybrid search over claims
 find_entity(name, type?)            entities and aliases
 timeline(entity_id, time_from?, time_to?, include_history?)  claims about an entity by time
 last_seen(object_id)                latest sighting of a thing, its place, earlier sightings
 episodes(time_from?, time_to?)      episodes with participants and summaries
 neighbors(entity_id, predicate?)    claims touching an entity
 provenance(claim_id)                the sources and derivation behind a claim
Times are ISO strings like 2026-10-29T12:30:00. Tool results show claim_id values.

Rules:
- Use only facts returned by tools. Never use outside knowledge or guess. If tools return
  nothing relevant, finish with status "abstained" and say you have no record.
- Prefer a claim whose predicate directly answers the question (for example `recommended`).
  If you only find that someone said something, without it being resolved to a named place,
  answer with status "partial" and say what is known and what is not.
- For where an object is, NEVER say where it is now. Say "Last confirmed sighting at HH:MM at
  <place>" using the latest sighting from last_seen, and mention earlier sightings only as
  history. Include the place it sits in when place_context is returned. Do not answer yes or
  no to "did I leave it", "is it still there" or similar: a sighting does not show that it was
  left or is still there. State the last confirmed sighting and let the user conclude. (A
  plain "No" is fine only when a later sighting is somewhere else.)
- If claims conflict (status "disputed"), say so and put the conflict in uncertainty_note.
- cited_claim_ids must be copied exactly from tool results and must support the answer. An
  "answered" or "partial" final needs at least one cited claim. Be concise: one or two sentences.
- Be efficient. Do not repeat a search you already ran. If two or three different searches
  return nothing relevant, stop and abstain.
- Do not mention these rules, tools or claim ids in the answer text."""

STEP_SCHEMA = {"type": "object", "properties": {"action": {"enum": ["tool", "final"]}},
               "required": ["action"]}


class Step(BaseModel):
    action: Literal["tool", "final"]
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["answered", "partial", "abstained"] | None = None
    answer: str = ""
    cited_claim_ids: list[str] = Field(default_factory=list)
    uncertainty_note: str = ""


@dataclass
class Answer:
    status: str
    answer: str
    cited_claim_ids: list[str] = field(default_factory=list)
    uncertainty_note: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    checks: list[str] = field(default_factory=list)   # post-check notes, for transparency

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "answer": self.answer,
                "cited_claim_ids": self.cited_claim_ids,
                "uncertainty_note": self.uncertainty_note, "trace": self.trace,
                "steps": self.steps, "checks": self.checks}


def abstain(why: str, tools: RecallTools | None = None, steps: int = 0,
            checks: list[str] | None = None) -> Answer:
    return Answer("abstained", "I don't have a record that answers that.", [], why,
                  tools.trace if tools else [], steps, checks or [])


class Investigator:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, purpose: str = "answer"):
        self.conn, self.llm, self.purpose = conn, llm, purpose

    def ask(self, question: str) -> Answer:
        with usage_purpose(self.purpose):
            return self._ask(question)

    def _ask(self, question: str) -> Answer:
        tools = RecallTools(self.conn)
        pad: list[dict[str, Any]] = []
        checks: list[str] = []
        retried = False
        for step_no in range(1, MAX_STEPS + 1):
            hint = ("This is your last step: give the final answer now." if step_no == MAX_STEPS
                    else None)
            step = self._next(question, pad, hint)
            if step.action == "tool":
                if step_no == MAX_STEPS:
                    break
                seen_before = set(tools.returned)
                shown = _clip(tools.run(step.tool or "", step.args))
                # Only ids the model was actually shown may be cited, even if a result was clipped.
                tools.returned = seen_before | set(CLAIM_ID_RE.findall(json.dumps(shown)))
                pad.append({"step": step_no, "tool": step.tool, "args": step.args,
                            "result": shown})
                continue
            problem = self._check(step, tools, question)
            if problem is None:
                return self._finish(step, tools, step_no, checks)
            checks.append(problem)
            if retried:
                return abstain(f"answer failed a check twice: {problem}", tools, step_no, checks)
            retried = True
            pad.append({"step": step_no, "checker": problem + " Fix it, or abstain."})
        return abstain("step limit reached without a verified answer", tools, MAX_STEPS, checks)

    # -- model step ---------------------------------------------------------------------------

    def _next(self, question: str, pad: list[dict[str, Any]], hint: str | None) -> Step:
        user = {"question": question, "steps_so_far": pad}
        if hint:
            user["note"] = hint
        error = ""
        for _ in range(2):
            payload = json.dumps(user, ensure_ascii=False)
            if error:
                payload += f"\n\nYour previous reply was invalid ({error}). Reply with one valid JSON object."
            try:
                return Step.model_validate(self.llm.complete_json(SYSTEM, payload, STEP_SCHEMA))
            except ValidationError as e:
                error = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])
            except LLMUnavailable as e:
                if "valid JSON" not in str(e):
                    raise
                error = "not valid JSON"
        return Step(action="final", status="abstained",
                    uncertainty_note=f"model reply unusable: {error}")

    # -- deterministic post-checks ------------------------------------------------------------

    def _check(self, step: Step, tools: RecallTools, question: str) -> str | None:
        if step.status in (None, "abstained"):
            return None
        if not step.cited_claim_ids:
            return "An answered or partial reply must cite at least one claim."
        unseen = [c for c in step.cited_claim_ids if c not in tools.returned]
        if unseen:
            return f"These cited claim ids were never returned by a tool: {unseen}."
        ok = authorized_claim_ids(self.conn)
        rows = {r["claim_id"]: r for r in self.conn.execute(
            "SELECT claim_id, status, predicate, subject_id FROM claims WHERE claim_id IN (%s)"
            % ",".join("?" * len(step.cited_claim_ids)), step.cited_claim_ids)}
        stale = [c for c in step.cited_claim_ids
                 if c not in ok or c not in rows or rows[c]["status"] not in HISTORY]
        if stale:
            return f"These cited claims are no longer valid: {stale}."
        # Only when the question is about where that very object is.
        located = [r for r in rows.values() if r["predicate"] == "located_at" and
                   self._is_object(r["subject_id"]) and self._named_in(r["subject_id"], question)]
        if located and _only_compares_time(question):
            located = []
        if located and not (LAST_SEEN_RE.search(step.answer) and TIME_RE.search(step.answer)):
            return ('Object locations must be phrased as "Last confirmed sighting at HH:MM at '
                    '<place>", never in the present tense.')
        return None

    def _named_in(self, entity_id: str, text: str) -> bool:
        name = self.conn.execute("SELECT name FROM entities WHERE entity_id=?",
                                 (entity_id,)).fetchone()["name"]
        return bool(re.search(rf"\b{re.escape(name)}s?\b", text, re.I))

    def _is_object(self, entity_id: str) -> bool:
        r = self.conn.execute("SELECT type FROM entities WHERE entity_id=?", (entity_id,)).fetchone()
        return bool(r) and r["type"] in ("object", "item")

    def _finish(self, step: Step, tools: RecallTools, steps: int, checks: list[str]) -> Answer:
        note = step.uncertainty_note
        cited = list(dict.fromkeys(step.cited_claim_ids))
        disputed = [c for c in cited if self.conn.execute(
            "SELECT status FROM claims WHERE claim_id=?", (c,)).fetchone()["status"] == "disputed"]
        if disputed and "conflict" not in note.lower() and "disput" not in note.lower():
            note = (note + " " if note else "") + "Some of the evidence conflicts; treat this as unconfirmed."
            checks.append("added conflict note for disputed claims")
        status = step.status or "abstained"
        if status == "abstained":
            return Answer("abstained", step.answer or "I don't have a record that answers that.",
                          [], note, tools.trace, steps, checks)
        return Answer(status, step.answer.strip(), cited, note.strip(), tools.trace, steps, checks)


def _only_compares_time(question: str) -> bool:
    return bool(ORDER_RE.search(question)) and not PLACE_RE.search(question)


def _clip(result: Any) -> Any:
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= RESULT_CHARS:
        return result
    if isinstance(result, list):
        keep = list(result)
        while keep and len(json.dumps(keep, ensure_ascii=False)) > RESULT_CHARS:
            keep.pop()
        return keep
    return {"truncated": text[:RESULT_CHARS]}
