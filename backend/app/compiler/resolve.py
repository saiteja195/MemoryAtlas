"""Entity resolution: exact or alias match first, an LLM adjudicates only ambiguous cases."""
import difflib
import json
import re
import sqlite3
import unicodedata
from typing import Any

from ..llm.base import LLMClient, LLMUnavailable
from ..privacy.filter import authorized_claim_ids

# Types the model may use interchangeably for the same real thing.
_GROUPS = {"person": "person", "place": "site", "org": "site", "object": "thing", "item": "thing"}
_ARTICLES = re.compile(r"^(the|a|an|my)\s+")
_SELF = {"me", "i", "myself", "my", "user", "owner"}
FUZZY_THRESHOLD = 0.8

ADJUDICATE_SYSTEM = (
    "You decide whether a newly mentioned name refers to the same real-world entity as one of "
    "the candidates. Be conservative: answer null unless it is clearly the same one.")
ADJUDICATE_SCHEMA = {"type": "object", "properties": {"match": {"type": ["string", "null"]},
                                                      "reason": {"type": "string"}},
                     "required": ["match"]}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return _ARTICLES.sub("", s)


def slug(name: str) -> str:
    return re.sub(r"\s+", "-", norm(name)) or "unknown"


class EntityResolver:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient | None = None, owner: str = "me"):
        self.conn, self.llm, self.owner = conn, llm, owner
        self.adjudications: list[dict[str, Any]] = []   # kept for tests and the provenance UI

    # -- reads --------------------------------------------------------------------------------

    def ensure_owner(self, name: str = "Me") -> None:
        self.conn.execute("INSERT OR IGNORE INTO entities(entity_id, type, name, attrs)"
                          " VALUES (?, 'person', ?, NULL)", (self.owner, name))

    def _same_as(self) -> list[sqlite3.Row]:
        """Active, still-authorized alias claims (revoked support means the alias is gone)."""
        auth = authorized_claim_ids(self.conn)
        return [r for r in self.conn.execute(
            "SELECT claim_id, subject_id, object_value FROM claims WHERE predicate='same_as'"
            " AND status='active' AND object_value IS NOT NULL") if r["claim_id"] in auth]

    def _names_of(self, entity_id: str, name: str, aliases: list[sqlite3.Row] | None = None
                  ) -> set[str]:
        """Names an entity answers to: its own, plus surface forms from active same_as claims."""
        names = {norm(name)}
        for r in (aliases if aliases is not None else self._same_as()):
            if r["subject_id"] == entity_id:
                names.add(norm(r["object_value"]))
        return names

    def _candidates(self, etype: str) -> list[sqlite3.Row]:
        group = _GROUPS.get(etype, "thing")
        return [r for r in self.conn.execute(
            "SELECT * FROM entities WHERE type != 'episode'") if _GROUPS.get(r["type"]) == group]

    # -- main entry ---------------------------------------------------------------------------

    def resolve(self, name: str, etype: str, source_id: str, context: str = "") -> tuple[str, bool]:
        """Returns (entity_id, created). Fuzzy merges are returned with created=False and the
        caller records a `same_as` claim (see `merge_surface_form`)."""
        key = norm(name)
        if etype == "person" and key in _SELF:
            self.ensure_owner()
            return self.owner, False
        cands = self._candidates(etype)
        aliases = self._same_as()
        for a in aliases:                     # a name bound to another entity resolves to it
            if norm(a["object_value"]) == key and any(c["entity_id"] == a["subject_id"]
                                                      for c in cands):
                return a["subject_id"], False
        for r in cands:                       # an entity's own name wins over anyone's alias
            if key == norm(r["name"]):
                return r["entity_id"], False
        for r in cands:
            if key in self._names_of(r["entity_id"], r["name"], aliases):
                return r["entity_id"], False
        scored = sorted(
            ((difflib.SequenceMatcher(None, key, norm(r["name"])).ratio(), r) for r in cands),
            key=lambda x: -x[0])
        close = [(s, r) for s, r in scored[:3] if s >= FUZZY_THRESHOLD]
        if close and self.llm is not None:
            picked = self._adjudicate(name, etype, [r for _, r in close], context)
            if picked:
                self.merge_surface_form(picked, name, source_id)
                return picked, False
        return self._create(name, etype), True

    def _create(self, name: str, etype: str) -> str:
        base = f"{etype}:{slug(name)}"
        eid, n = base, 2
        while self.conn.execute("SELECT 1 FROM entities WHERE entity_id=?", (eid,)).fetchone():
            eid, n = f"{base}-{n}", n + 1
        self.conn.execute("INSERT INTO entities(entity_id, type, name, attrs) VALUES (?,?,?,NULL)",
                          (eid, etype, name.strip()))
        return eid

    def _adjudicate(self, name: str, etype: str, cands: list[sqlite3.Row], context: str) -> str | None:
        user = json.dumps({"new_name": name, "type": etype, "context": context,
                           "candidates": [{"id": r["entity_id"], "name": r["name"],
                                           "type": r["type"]} for r in cands]})
        try:
            out = self.llm.complete_json(ADJUDICATE_SYSTEM, user, ADJUDICATE_SCHEMA)
        except LLMUnavailable:
            return None   # when unsure, keep entities apart rather than merge on a guess
        pick = out.get("match")
        valid = {r["entity_id"] for r in cands}
        self.adjudications.append({"name": name, "candidates": sorted(valid), "match": pick})
        return pick if pick in valid else None

    def merge_surface_form(self, entity_id: str, surface: str, source_id: str) -> None:
        """Record 'surface refers to entity' as a justified `same_as` claim, so a later
        revocation of its source can undo the alias."""
        from .store import ClaimWriter  # local import: store depends on this module's norm()
        ClaimWriter(self.conn).write(
            subject_id=entity_id, predicate="same_as", object_id=None, object_value=surface.strip(),
            event_time=None, evidence_type="inference", confidence=0.8, episode_id=None,
            text=f'"{surface.strip()}" refers to the same entity as '
                 f'{self.conn.execute("SELECT name FROM entities WHERE entity_id=?", (entity_id,)).fetchone()["name"]}',
            source_id=source_id)
