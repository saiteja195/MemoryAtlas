"""Memory Compiler: one observation in, claims with justifications out."""
import json
import logging
import sqlite3
from dataclasses import dataclass, field

from ..capture.models import Observation
from ..llm.base import LLMClient, LLMUnavailable
from .contradiction import contradiction_pass
from .episodes import bind_episode
from .extract import ExtractedClaim, ExtractionRejected, extract_claims
from .resolve import EntityResolver
from .store import ClaimWriter

log = logging.getLogger(__name__)

DIRECT_CONFIDENCE = 0.95    # direct_observation = model confidence x 0.95
CONFIRMED_CONFIDENCE = 0.99


@dataclass
class CompileResult:
    source_id: str
    episode_id: str | None = None
    claim_ids: list[str] = field(default_factory=list)
    disputed: list[tuple[str, str]] = field(default_factory=list)
    rejected: str | None = None


class Compiler:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, owner: str = "me"):
        self.conn, self.llm, self.owner = conn, llm, owner
        self.resolver = EntityResolver(conn, llm, owner)
        self.writer = ClaimWriter(conn)

    def compile(self, obs: Observation) -> CompileResult:
        res = CompileResult(obs.source_id)
        self.resolver.ensure_owner()
        res.episode_id = bind_episode(self.conn, obs)
        ep = self.conn.execute("SELECT name, attrs FROM entities WHERE entity_id=?",
                               (res.episode_id,)).fetchone()
        attrs = json.loads(ep["attrs"])
        episode_ctx = {"start": attrs["start"], "end": attrs["end"]}
        known = [r["name"] for r in self.conn.execute(
            "SELECT name FROM entities WHERE type != 'episode' ORDER BY name LIMIT 60")]
        try:
            extracted = extract_claims(self.llm, obs, episode_ctx, known)
        except (ExtractionRejected, LLMUnavailable) as e:
            log.error("rejected %s: %s", obs.source_id, e)
            res.rejected = str(e)
            self.conn.commit()   # the episode binding stays; the source has no claims
            return res

        mentioned: dict[str, float] = {}
        subjects: set[str] = set()
        for c in extracted:
            ids = self._write(obs, res.episode_id, c)
            if ids is None:
                continue
            claim_id, subject_id, object_id = ids
            res.claim_ids.append(claim_id)
            subjects.add(subject_id)
            for eid in (subject_id, object_id):
                if eid:
                    mentioned[eid] = max(mentioned.get(eid, 0.0), c.confidence)
        # Deterministic: every entity this observation involves belongs to its episode.
        for eid, conf in mentioned.items():
            res.claim_ids.append(self._part_of_episode(obs, res.episode_id, ep["name"], eid, conf))
        res.disputed = contradiction_pass(self.conn, subjects)
        self.conn.commit()
        return res

    # -- helpers ------------------------------------------------------------------------------

    def _write(self, obs: Observation, episode_id: str, c: ExtractedClaim
               ) -> tuple[str, str, str | None] | None:
        if not c.object and not c.value:
            return None
        ctx = obs.text[:200]
        subject_id, _ = self.resolver.resolve(c.subject, c.subject_type, obs.source_id, ctx)
        object_id = None
        if c.object:
            object_id, _ = self.resolver.resolve(c.object, c.object_type or "object",
                                                 obs.source_id, ctx)
            if object_id == subject_id:
                return None
        event_time = c.event_time or obs.captured_at
        if obs.kind == "user_confirmation":
            evidence, conf = "user_confirmation", CONFIRMED_CONFIDENCE
        else:
            evidence, conf = "direct_observation", round(c.confidence * DIRECT_CONFIDENCE, 3)
        cid, _ = self.writer.write(
            subject_id=subject_id, predicate=c.predicate, object_id=object_id,
            object_value=None if object_id else c.value, event_time=event_time,
            evidence_type=evidence, confidence=conf, episode_id=episode_id, text=c.text.strip(),
            source_id=obs.source_id,
            valid_from=event_time if c.predicate == "located_at" else None)
        return cid, subject_id, object_id

    def _part_of_episode(self, obs: Observation, episode_id: str, episode_name: str, eid: str,
                         conf: float) -> str:
        name = self.conn.execute("SELECT name FROM entities WHERE entity_id=?",
                                 (eid,)).fetchone()["name"]
        cid, _ = self.writer.write(
            subject_id=eid, predicate="part_of_episode", object_id=episode_id, object_value=None,
            event_time=obs.captured_at, evidence_type="direct_observation",
            confidence=round(conf * DIRECT_CONFIDENCE, 3), episode_id=episode_id,
            text=f"{name} was part of {episode_name}", source_id=obs.source_id)
        return cid
