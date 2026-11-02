"""Step 3 of the compiler: structured claim extraction with Muse Spark.

The model proposes claims in a controlled vocabulary. Pydantic enforces the schema; on a
validation error there is one repair retry, then the observation is rejected and logged.
"""
import json
import logging
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..capture.models import Observation
from ..llm.base import LLMClient, LLMUnavailable

log = logging.getLogger(__name__)

# Full controlled vocabulary (docs/IMPLEMENTATION_PLAN.md section 3).
PREDICATES = ["observed_at", "located_at", "met_with", "attended", "said", "recommended",
              "committed_to", "has_attribute", "near", "across_from", "part_of_episode",
              "same_as", "summary_of"]
# The subset the extraction step may emit. The rest are written by deterministic code or by
# the derivation rules in Phase 2.
EXTRACTABLE = ("observed_at", "located_at", "met_with", "attended", "said", "recommended",
               "committed_to", "has_attribute", "near", "across_from")
EntityType = Literal["person", "place", "object", "org", "item"]


class ExtractedClaim(BaseModel):
    subject: str = Field(min_length=1)
    subject_type: EntityType
    predicate: Literal[*EXTRACTABLE]
    object: str | None = None
    object_type: EntityType | None = None
    value: str | None = None
    event_time: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    text: str = Field(min_length=3)

    @field_validator("event_time")
    @classmethod
    def _iso(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            datetime.fromisoformat(v)
        except ValueError:
            return None  # an unparseable time falls back to the observation's captured_at
        return v


class Extraction(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


class ExtractionRejected(RuntimeError):
    pass


SYSTEM = f"""You extract factual claims from ONE observation for a personal memory graph.

Rules:
- State only what this observation says or shows. Never use outside knowledge, and never
  connect it to other observations. If a speaker refers to something without naming it
  ("the taco place across the street"), do not guess its name.
- Refer to the person who owns the memory as "Me". Use the exact names that appear in the
  observation. Reuse a name from known_entities when it is clearly the same thing.
- Predicates (use only these): observed_at(X, place): the owner was at that place or event;
  located_at(thing_or_person, place): X is at that place at event_time (use it for a sighting
  of an object); met_with(person, person); attended(person, event or org);
  said(person, value=short paraphrase of what they said); recommended(person, named entity) only
  when the speaker recommends something by NAME, otherwise use said; committed_to(person,
  value=the promise); has_attribute(entity, value="key: value", e.g. "awning: green");
  near(a, b) and across_from(a, b) only when stated or visible.
- Use `object` for another entity and `value` for literal text, not both.
- Allowed entity types: person, place, object, org, item. A business or shop is a place.
- event_time is ISO 8601; omit it to mean the observation's captured_at.
- confidence is 0 to 1: how sure the observation makes this claim.
- text is one plain sentence rendering the claim. 0 to 8 claims; return an empty list if
  nothing is stated.
Return JSON: {{"claims": [{{"subject","subject_type","predicate","object","object_type",
"value","event_time","confidence","text"}}]}}. Allowed predicates: {", ".join(EXTRACTABLE)}."""


def build_user(obs: Observation, episode: dict[str, Any], known: list[str]) -> str:
    return json.dumps({
        "observation": {"kind": obs.kind, "captured_at": obs.captured_at, "text": obs.text,
                        "lat": obs.lat, "lon": obs.lon},
        "episode": episode,
        "known_entities": known,
    }, ensure_ascii=False)


def extract_claims(llm: LLMClient, obs: Observation, episode: dict[str, Any],
                   known: list[str]) -> list[ExtractedClaim]:
    schema = Extraction.model_json_schema()
    user = build_user(obs, episode, known)
    error = ""
    for attempt in range(2):
        prompt = user if not error else (
            f"{user}\n\nYour previous answer was invalid ({error}). Return corrected JSON only.")
        try:
            raw = llm.complete_json(SYSTEM, prompt, schema)
            return Extraction.model_validate(raw).claims
        except ValidationError as e:
            error = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
            log.warning("extraction invalid for %s (attempt %d): %s", obs.source_id, attempt + 1,
                        error)
        except LLMUnavailable as e:
            if "valid JSON" not in str(e) or attempt == 1:
                raise
            error = str(e)[:200]
    raise ExtractionRejected(f"{obs.source_id}: schema invalid after repair: {error}")
