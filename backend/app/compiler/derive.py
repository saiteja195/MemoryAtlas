"""Step 5 of the compiler: named inference rules. The LLM proposes, the code validates.

- spatial_referent_resolution: a place described but not named in conversation ("the taco place
  across the street, green awning") is bound to a place seen in a frame, only if the code
  confirms matching attributes and a GPS distance of at most 100 m. Writes `same_as` and, when
  the speaker is known, `recommended`, each justified by ALL of its premises.
- last_seen / supersession: the latest `located_at` per subject by EVENT time stays active;
  earlier ones become `superseded` history. Late uploads reorder correctly.
- episode_summary: a one-paragraph summary that is itself a claim whose premises are the claims
  it used, so it dies with them.
"""
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..llm.base import LLMClient, LLMUnavailable
from ..privacy.filter import authorized_claim_ids
from .episodes import haversine_m
from .resolve import norm
from .store import ClaimWriter

log = logging.getLogger(__name__)

SPATIAL_RULE = "spatial_referent_resolution"
SUMMARY_RULE = "episode_summary"
MAX_DISTANCE_M = 100.0
INFERENCE_FACTOR = 0.9           # inference confidence = min(premises) x 0.9
_REFERENT_TYPES = ("place", "org", "item", "object")
_META = ("part_of_episode", "summary_of", "same_as")

BIND_SYSTEM = (
    "A spoken conversation described a place without naming it. Decide whether it is the same "
    "place as one of the candidate places that were seen in photos. Be conservative: answer "
    "null unless one candidate clearly matches the description. Each candidate carries "
    "`metres_from_where_it_was_described`: the GPS distance between where the conversation took "
    "place and where the candidate was photographed. A short distance supports a description "
    "like 'across the street'; matching attributes (awning colour, kind of place) support identity.")
BIND_SCHEMA = {"type": "object", "properties": {"match": {"type": ["string", "null"]},
                                                "reason": {"type": "string"}},
               "required": ["match"]}
SUMMARY_SYSTEM = (
    "Write one factual paragraph (at most 3 sentences) summarising an episode of someone's day "
    "using ONLY the numbered claims given. Do not add anything that is not in them.")
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}},
                  "required": ["summary"]}


@dataclass
class DeriveResult:
    bindings: list[tuple[str, str]] = field(default_factory=list)   # (referent, candidate)
    superseded: list[str] = field(default_factory=list)
    summary_claim: str | None = None
    errors: list[str] = field(default_factory=list)


def parse_attr(value: str | None) -> tuple[str, str] | None:
    if not value or ":" not in value:
        return None
    k, v = value.split(":", 1)
    return norm(k), norm(v)


def pair_match(a: tuple[str, str], b: tuple[str, str]) -> bool:
    return a[0] == b[0] and (a[1] == b[1] or a[1] in b[1] or b[1] in a[1])


def attrs_agree(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> bool:
    """At least one attribute matches (same key, equal or contained value), none conflicts."""
    matched = False
    for x in a:
        for y in b:
            if x[0] != y[0]:
                continue
            if pair_match(x, y):
                matched = True
            else:
                return False
    return matched


class Deriver:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, owner: str = "me"):
        self.conn, self.llm, self.owner = conn, llm, owner
        self.writer = ClaimWriter(conn)
        self._decided: set[tuple] = set()

    def reset(self) -> None:
        """Forget what has been decided. Needed whenever the database is emptied: the memo says
        "the model was already asked about this binding", which is false for a fresh graph."""
        self._decided.clear()

    # -- entry point --------------------------------------------------------------------------

    def run(self, episode_id: str, subject_ids: set[str]) -> DeriveResult:
        res = DeriveResult()
        res.superseded = self.supersede_located_at(subject_ids)
        for step in (self.resolve_spatial_referents, self.summarize_episode):
            try:
                step(episode_id, res)
            except LLMUnavailable as e:
                log.error("%s failed: %s", step.__name__, e)
                res.errors.append(f"{step.__name__}: {e}")
        return res

    # -- last_seen / supersession -------------------------------------------------------------

    def supersede_located_at(self, subject_ids: set[str]) -> list[str]:
        changed: list[str] = []
        for sid in subject_ids:
            rows = self.conn.execute(
                "SELECT claim_id, event_time, status FROM claims WHERE subject_id=? AND"
                " predicate='located_at' AND status IN ('active','superseded','disputed')"
                " AND event_time IS NOT NULL", (sid,)).fetchall()
            if not rows:
                continue
            when = {r["claim_id"]: datetime.fromisoformat(r["event_time"]) for r in rows}
            latest_t = max(when.values())
            latest = next(r["claim_id"] for r in rows if when[r["claim_id"]] == latest_t)
            for r in rows:
                if r["status"] == "disputed":
                    continue
                if when[r["claim_id"]] < latest_t and r["status"] != "superseded":
                    self.conn.execute("UPDATE claims SET status='superseded', superseded_by=?"
                                      " WHERE claim_id=?", (latest, r["claim_id"]))
                    changed.append(r["claim_id"])
                elif when[r["claim_id"]] == latest_t and r["status"] == "superseded":
                    self.conn.execute("UPDATE claims SET status='active', superseded_by=NULL"
                                      " WHERE claim_id=?", (r["claim_id"],))
        return changed

    # -- spatial referent resolution ----------------------------------------------------------

    def _claim_rows(self, authorized: set[str], where: str, args: tuple) -> list[sqlite3.Row]:
        return [r for r in self.conn.execute(
            f"SELECT * FROM claims WHERE status IN ('active','disputed') AND {where}", args)
                if r["claim_id"] in authorized]

    def _source_info(self, claim_ids: list[str]) -> list[sqlite3.Row]:
        if not claim_ids:
            return []
        marks = ",".join("?" * len(claim_ids))
        return self.conn.execute(
            f"SELECT DISTINCT s.source_id, s.kind, s.lat, s.lon FROM justifications j JOIN sources"
            f" s ON s.source_id=j.source_id WHERE j.kind='source' AND j.claim_id IN ({marks})",
            claim_ids).fetchall()

    def resolve_spatial_referents(self, episode_id: str, res: DeriveResult) -> None:
        auth = authorized_claim_ids(self.conn)
        aliases = {norm(r["object_value"]) for r in self._claim_rows(auth, "predicate='same_as'", ())
                   if r["object_value"]}
        ents = {r["entity_id"]: r for r in self.conn.execute(
            "SELECT * FROM entities WHERE type != 'episode'")}
        for ref in [e for e in ents.values() if e["type"] in _REFERENT_TYPES]:
            if norm(ref["name"]) in aliases:
                continue
            claims = self._claim_rows(auth, "subject_id=?", (ref["entity_id"],))
            anchors = [c for c in claims if c["predicate"] in ("across_from", "near") and c["object_id"]]
            attr_claims = [c for c in claims if c["predicate"] == "has_attribute"]
            if not anchors or not attr_claims:
                continue
            ref_src = self._source_info([c["claim_id"] for c in claims])
            if not ref_src or any(s["kind"] != "transcript_segment" for s in ref_src):
                continue   # it was also seen or confirmed somewhere: it is not an unnamed referent
            self._try_bind(ref, ents, auth, anchors, attr_claims, ref_src, res)

    def _try_bind(self, ref, ents, auth, anchors, attr_claims, ref_src, res) -> None:
        ref_attrs = [(parse_attr(c["object_value"]), c) for c in attr_claims]
        ref_attrs = [(a, c) for a, c in ref_attrs if a]
        candidates: dict[str, dict[str, Any]] = {}
        for cand in [e for e in ents.values() if e["type"] in ("place", "org")
                     and e["entity_id"] != ref["entity_id"]]:
            cclaims = self._claim_rows(auth, "subject_id=?", (cand["entity_id"],))
            cattr = [(parse_attr(c["object_value"]), c) for c in cclaims
                     if c["predicate"] == "has_attribute"]
            cattr = [(a, c) for a, c in cattr if a]
            seen = [s for s in self._source_info([c["claim_id"] for _, c in cattr])
                    if s["kind"] == "frame_observation"]
            if not cattr or not seen:
                continue
            if not attrs_agree([a for a, _ in ref_attrs], [a for a, _ in cattr]):
                continue
            dist = self._min_distance(ref_src, seen)
            if dist is None or dist > MAX_DISTANCE_M:
                continue
            candidates[cand["entity_id"]] = {
                "entity": cand, "all": [c["text"] for c in cclaims], "metres": round(dist),
                "claims": [c for a, c in cattr if any(pair_match(a, r) for r, _ in ref_attrs)],
                "ref_claims": [c for r, c in ref_attrs if any(pair_match(a, r) for a, _ in cattr)]}
        if not candidates:
            return
        key = (ref["entity_id"], tuple(sorted(candidates)))
        if key in self._decided:
            return
        self._decided.add(key)
        said = self._speech(ref_src, auth)
        pick = self._propose(ref, anchors, attr_claims, said, candidates)
        if pick not in candidates:      # the model may only choose among validated candidates
            return
        cand = candidates[pick]
        premises = [c["claim_id"] for c in anchors + cand["ref_claims"] + cand["claims"] + said]
        anchor_ids = {c["object_id"] for c in anchors}
        premises += [c["claim_id"] for c in self._claim_rows(auth, "predicate IN ('observed_at',"
                     "'located_at')", ()) if c["object_id"] in anchor_ids
                     and c["subject_id"] == self.owner]
        conf = self._confidence(premises)
        episode = anchors[0]["episode_id"]
        cname = cand["entity"]["name"]
        self.writer.write_derived(
            subject_id=pick, predicate="same_as", object_id=None, object_value=ref["name"],
            event_time=anchors[0]["event_time"], confidence=conf, episode_id=episode,
            text=f'The "{ref["name"]}" described in conversation is {cname}', rule=SPATIAL_RULE,
            premises=premises)
        res.bindings.append((ref["entity_id"], pick))
        for s in said:
            self.writer.write_derived(
                subject_id=s["subject_id"], predicate="recommended", object_id=pick,
                object_value=None, event_time=s["event_time"], confidence=conf,
                episode_id=s["episode_id"],
                text=f"{self._name(s['subject_id'])} recommended {cname}", rule=SPATIAL_RULE,
                premises=premises)

    @staticmethod
    def _min_distance(a_sources, b_sources) -> float | None:
        """Smallest GPS distance between any two located sources, or None if none has a fix."""
        d = [haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
             for a in a_sources for b in b_sources
             if None not in (a["lat"], a["lon"], b["lat"], b["lon"])]
        return min(d) if d else None

    def _speech(self, ref_src, auth) -> list[sqlite3.Row]:
        """`said` claims by someone other than the owner, from the same utterances."""
        ids = [s["source_id"] for s in ref_src]
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT c.* FROM claims c JOIN justifications j ON j.claim_id=c.claim_id WHERE"
            f" c.predicate='said' AND c.status IN ('active','disputed') AND c.subject_id != ?"
            f" AND j.source_id IN ({marks})", (self.owner, *ids)).fetchall()
        return [r for r in rows if r["claim_id"] in auth]

    def _confidence(self, premise_ids: list[str]) -> float:
        marks = ",".join("?" * len(premise_ids))
        lo = self.conn.execute(f"SELECT MIN(confidence) FROM claims WHERE claim_id IN ({marks})",
                               premise_ids).fetchone()[0]
        return round((lo or 0.5) * INFERENCE_FACTOR, 3)

    def _name(self, entity_id: str) -> str:
        return self.conn.execute("SELECT name FROM entities WHERE entity_id=?",
                                 (entity_id,)).fetchone()["name"]

    def _propose(self, ref, anchors, attr_claims, said, candidates) -> str | None:
        user = json.dumps({
            "described_place": {"name": ref["name"],
                                "claims": [c["text"] for c in anchors + attr_claims]},
            "what_was_said": [c["text"] for c in said],
            "candidates": [{"id": eid, "name": v["entity"]["name"], "claims": v["all"],
                            "metres_from_where_it_was_described": v["metres"]}
                           for eid, v in candidates.items()],
        }, ensure_ascii=False)
        out = self.llm.complete_json(BIND_SYSTEM, user, BIND_SCHEMA)
        return out.get("match")

    # -- episode summary ----------------------------------------------------------------------

    def summarize_episode(self, episode_id: str, res: DeriveResult) -> None:
        auth = authorized_claim_ids(self.conn)
        rows = [r for r in self._claim_rows(auth, "episode_id=?", (episode_id,))
                if r["predicate"] not in _META]
        if len(rows) < 2:
            return
        rows.sort(key=lambda r: (r["event_time"] or "", r["claim_id"]))
        premises = [r["claim_id"] for r in rows]
        for old in self.conn.execute(
                "SELECT c.claim_id FROM claims c WHERE c.subject_id=? AND c.predicate='summary_of'"
                " AND c.status='active'", (episode_id,)).fetchall():
            have = {p[0] for p in self.conn.execute(
                "SELECT p.premise_claim_id FROM justification_premises p JOIN justifications j"
                " USING(justification_id) WHERE j.claim_id=?", (old["claim_id"],))}
            if have == set(premises):
                return           # nothing changed since the last summary
        lines = "\n".join(f"{i}. {r['text']}" for i, r in enumerate(rows, 1))
        out = self.llm.complete_json(SUMMARY_SYSTEM, lines, SUMMARY_SCHEMA)
        text = (out.get("summary") or "").strip()
        if not text:
            return
        cid, _ = self.writer.write_derived(
            subject_id=episode_id, predicate="summary_of", object_id=None, object_value=text,
            event_time=rows[0]["event_time"], confidence=self._confidence(premises),
            episode_id=episode_id, text=text, rule=SUMMARY_RULE, premises=premises)
        self.conn.execute("UPDATE claims SET status='superseded', superseded_by=? WHERE"
                          " subject_id=? AND predicate='summary_of' AND status='active' AND"
                          " claim_id != ?", (cid, episode_id, cid))
        res.summary_claim = cid
