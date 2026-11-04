"""The to-do scan: a second, separate model pass over what was said or written.

It proposes `requested(person, object=Me, value=...)` (someone asked the owner to do something)
and any `committed_to(person, value=...)` the first extraction pass missed. It has its own
prompt, so the extraction prompt and its recorded replies stay untouched. The scan is a bonus:
when the model is unavailable or keeps replying out of schema, it yields nothing and the
observation is still compiled as usual.
"""
import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..capture.models import Observation
from ..llm.base import LLMClient, LLMUnavailable
from ..llm.metered import usage_purpose
from .extract import ExtractedClaim

log = logging.getLogger(__name__)

TODO_PREDICATES = ("committed_to", "requested")


class TodoClaim(ExtractedClaim):
    predicate: Literal[*TODO_PREDICATES]


class TodoScan(BaseModel):
    claims: list[TodoClaim] = Field(default_factory=list)


SYSTEM = f"""You find promises and requests in ONE observation (a conversation segment or a note)
for a personal memory graph.

Rules:
- State only what this observation says. Never use outside knowledge and never guess.
- Refer to the person who owns the memory as "Me". Use the exact names that appear in the
  observation. Reuse a name from known_entities when it is clearly the same person.
- committed_to(person, value=the promise): the person said they will do something
  ("I'll send the proposal by Friday"). The subject is the one who promised.
- requested(person, object="Me", value=what was asked): the person asked the owner to do
  something ("Could you send me the notes?"). The subject is the one asking; the object is
  "Me", the one being asked. The subject of requested is never "Me": the owner is the one
  being asked, never the one asking.
- already_found lists promises another pass already took from this observation. Return only
  promises and requests that are NOT already in that list, not a rewording of one.
- Keep the person's own words in value and text, shortened only to the essential action.
- Ignore wishes, suggestions and recommendations that nobody agreed or was asked to do.
- Allowed entity types: person, place, object, org, item.
- event_time is ISO 8601; omit it to mean the observation's captured_at.
- confidence is 0 to 1: how sure the observation makes this claim.
- text is one plain sentence rendering the claim. 0 to 4 claims; return an empty list if there
  is no promise or request.
Return JSON: {{"claims": [{{"subject","subject_type","predicate","object","object_type",
"value","event_time","confidence","text"}}]}}. Allowed predicates: {", ".join(TODO_PREDICATES)}."""


def build_user(obs: Observation, known: list[str], already: list[str]) -> str:
    payload: dict[str, Any] = {
        "observation": {"kind": obs.kind, "captured_at": obs.captured_at, "text": obs.text},
        "known_entities": known,
        "already_found": already,
    }
    if obs.participants:
        payload["session_participants"] = obs.participants
    return json.dumps(payload, ensure_ascii=False)


def scan_todos(llm: LLMClient, obs: Observation, known: list[str],
               already: list[ExtractedClaim] | None = None) -> list[ExtractedClaim]:
    """`already`: claims the extraction pass returned for this observation. Its promises are
    shown to the model so it does not repeat them; the pipeline still drops near duplicates."""
    schema = TodoScan.model_json_schema()
    found = [f"{c.subject} committed_to: {c.value}" for c in already or []
             if c.predicate == "committed_to" and c.value]
    user = build_user(obs, known, found)
    error = ""
    with usage_purpose("todo_scan", obs.captured_at[:10]):
        for attempt in range(2):
            prompt = user if not error else (
                f"{user}\n\nYour previous answer was invalid ({error}). Return corrected JSON only.")
            try:
                raw = llm.complete_json(SYSTEM, prompt, schema)
                return list(TodoScan.model_validate(raw).claims)
            except ValidationError as e:
                error = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                  for x in e.errors()[:4])
                log.warning("to-do scan invalid for %s (attempt %d): %s", obs.source_id,
                            attempt + 1, error)
            except LLMUnavailable as e:
                log.info("to-do scan skipped for %s: %s", obs.source_id, str(e)[:200])
                return []
    log.warning("to-do scan dropped for %s: invalid after repair", obs.source_id)
    return []
