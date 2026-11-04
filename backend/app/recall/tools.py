"""Recall tools. Every read goes through the privacy filter (authorized AND readable status),
and every claim id handed to the model is remembered so citations can be checked."""
import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Callable

from fractions import Fraction

from ..compiler.episodes import haversine_m
from ..compiler.resolve import norm
from ..embed import counts, from_blob, rank
from ..privacy.filter import HISTORY, READABLE, authorized_claim_ids

HIDDEN_PREDICATES = ("part_of_episode",)
MAX_K = 12


def when(iso: str | None) -> str | None:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M") if iso else None


class RecallTools:
    def __init__(self, conn: sqlite3.Connection, extended: bool = False, owner: str = "me"):
        self.conn = conn
        self.owner = owner                   # the entity whose to-dos open_todos lists
        self.returned: set[str] = set()      # every claim id the model has been shown
        # Stats tools show numbers, not claims: the raw result of each, keyed by tool name, so the
        # figures in an answer can be checked against it and the tool cited instead of a claim.
        self.stats_returned: dict[str, dict[str, Any]] = {}
        self.trace: list[dict[str, Any]] = []
        self._auth: set[str] | None = None
        self._names: dict[str, str] = {}
        self.registry: dict[str, Callable[..., Any]] = {
            "search_claims": self.search_claims, "find_entity": self.find_entity,
            "timeline": self.timeline, "last_seen": self.last_seen, "episodes": self.episodes,
            "neighbors": self.neighbors, "provenance": self.provenance}
        if extended:                         # only for questions the router sends to the extended prompt
            from .tools_extra import extra_tools
            self.registry.update(extra_tools(self))

    # -- plumbing -----------------------------------------------------------------------------

    def run(self, name: str, args: dict[str, Any]) -> Any:
        fn = self.registry.get(name)
        if fn is None:
            out: Any = {"error": f"unknown tool {name!r}; use one of {sorted(self.registry)}"}
        else:
            self._auth = authorized_claim_ids(self.conn)   # re-read: consent may have changed
            try:
                out = fn(**args)
            except TypeError as e:
                out = {"error": f"bad arguments for {name}: {e}"}
        n = len(out) if isinstance(out, list) else (0 if isinstance(out, dict) and "error" in out
                                                    else 1)
        self.trace.append({"tool": name, "args": args, "results": n})
        if out == [] and (args.get("time_from") or args.get("time_to")):
            out = self._outside_memory(args) or out
        return out

    def _outside_memory(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """An empty result for a date window that lies wholly outside what the memory covers is almost always
        a guessed date ("this morning" taken to mean the real today). Say what the memory covers, using only
        readable claims, so the caller can ask again with a window that exists."""
        times = sorted(r["event_time"] for r in self._claims("event_time IS NOT NULL")
                       if r["predicate"] != "part_of_episode")
        if not times:
            return None
        lo, hi = times[0], times[-1]
        start, end = args.get("time_from") or "", args.get("time_to") or "9999"
        if not (end < lo or start > hi):
            return None                       # the window overlaps the memory: nothing really matches
        return {"results": [], "note": (
            f"Nothing in that window. The memory only covers {when(lo)} to {when(hi)}. Words like 'today' or "
            f"'this morning' refer to that period, not to the current date.")}

    def _name(self, eid: str | None) -> str | None:
        if eid is None:
            return None
        if eid not in self._names:
            r = self.conn.execute("SELECT name FROM entities WHERE entity_id=?", (eid,)).fetchone()
            self._names[eid] = r["name"] if r else eid
        return self._names[eid]

    def _readable(self, row: sqlite3.Row, history: bool = False) -> bool:
        return row["claim_id"] in (self._auth or set()) and \
            row["status"] in (HISTORY if history else READABLE)

    def _supports(self, claim_id: str) -> list[str]:
        kinds = [r["kind"] for r in self.conn.execute(
            "SELECT s.kind FROM justifications j JOIN sources s ON s.source_id=j.source_id"
            " WHERE j.claim_id=? AND j.kind='source' AND s.status='active'", (claim_id,))]
        rules = [r["rule"] for r in self.conn.execute(
            "SELECT rule FROM justifications WHERE claim_id=? AND kind='derivation'", (claim_id,))]
        return sorted(set(kinds)) + [f"derived:{r}" for r in sorted(set(rules))]

    def view(self, row: sqlite3.Row) -> dict[str, Any]:
        self.returned.add(row["claim_id"])
        v = {"claim_id": row["claim_id"], "text": row["text"], "predicate": row["predicate"],
             "subject": self._name(row["subject_id"]), "subject_id": row["subject_id"],
             "when": when(row["event_time"]), "status": row["status"],
             "evidence": row["evidence_type"], "confidence": row["confidence"],
             "supported_by": self._supports(row["claim_id"])}
        if row["object_id"]:
            v["object"], v["object_id"] = self._name(row["object_id"]), row["object_id"]
        elif row["object_value"]:
            v["value"] = row["object_value"]
        return v

    def _claims(self, where: str, args: tuple = (), history: bool = False) -> list[sqlite3.Row]:
        return [r for r in self.conn.execute(f"SELECT * FROM claims WHERE {where}", args)
                if self._readable(r, history)]

    # -- tools --------------------------------------------------------------------------------

    def search_claims(self, query: str, k: int = 8, time_from: str | None = None,
                      time_to: str | None = None, predicate: str | None = None) -> list[dict]:
        """Hybrid full-text + vector search over readable claims."""
        k = max(1, min(int(k), MAX_K))
        terms = re.findall(r"\w+", norm(query))
        fts: list[str] = []
        if terms:
            q = " OR ".join(f'"{t}"' for t in terms)
            rows = self.conn.execute(
                "SELECT claim_id, rowid, bm25(claim_index) AS s FROM claim_index WHERE claim_index MATCH ?",
                (q,)).fetchall()
            # bm25 is a float; round away last-digit differences between SQLite builds, and break
            # exact ties by insertion order, so the order is the same on every machine.
            fts = [r["claim_id"] for r in sorted(rows, key=lambda r: (round(r["s"], 9), r["rowid"]))[:50]]
        vec = rank(counts(query), [
            (r["claim_id"], from_blob(r["vec"], r["text"])) for r in self.conn.execute(
                "SELECT v.claim_id, v.vec, c.text FROM claim_vectors v JOIN claims c ON c.claim_id = v.claim_id")])[:50]
        score: dict[str, Fraction] = {}                     # reciprocal rank fusion, in exact arithmetic
        for rank_i, cid in enumerate(fts):
            score[cid] = score.get(cid, Fraction(0)) + Fraction(1, 60 + rank_i)
        for rank_i, cid in enumerate(vec):
            score[cid] = score.get(cid, Fraction(0)) + Fraction(1, 60 + rank_i)
        out = []
        for cid in sorted(score, key=lambda c: -score[c]):   # stable: equal scores keep fusion order
            row = self.conn.execute("SELECT * FROM claims WHERE claim_id=?", (cid,)).fetchone()
            if not row or not self._readable(row):
                continue
            if row["predicate"] in HIDDEN_PREDICATES and predicate != row["predicate"]:
                continue
            if predicate and row["predicate"] != predicate:
                continue
            if time_from and (row["event_time"] or "") < time_from:
                continue
            if time_to and (row["event_time"] or "9") > time_to:
                continue
            out.append(self.view(row))
            if len(out) >= k:
                break
        return out

    def find_entity(self, name: str, type: str | None = None) -> list[dict]:
        key = norm(name)
        out = []
        for e in self.conn.execute("SELECT * FROM entities WHERE type != 'episode'"):
            if type and e["type"] != type:
                continue
            aliases = [norm(r["object_value"]) for r in self._claims(
                "subject_id=? AND predicate='same_as'", (e["entity_id"],)) if r["object_value"]]
            names = [norm(e["name"]), *aliases]
            if not any(key == n or key in n or n in key for n in names if n):
                continue
            used = self._claims("(subject_id=? OR object_id=?)", (e["entity_id"], e["entity_id"]))
            if used:
                out.append({"entity_id": e["entity_id"], "type": e["type"], "name": e["name"],
                            "aliases": aliases, "claims": len(used)})
        return out

    def timeline(self, entity_id: str, time_from: str | None = None, time_to: str | None = None,
                 include_history: bool = False) -> list[dict]:
        rows = self._claims("(subject_id=? OR object_id=?) AND predicate NOT IN ('part_of_episode')",
                            (entity_id, entity_id), history=include_history)
        rows = [r for r in rows if (not time_from or (r["event_time"] or "") >= time_from)
                and (not time_to or (r["event_time"] or "9") <= time_to)]
        rows.sort(key=lambda r: (r["event_time"] or "", r["claim_id"]))
        return [self.view(r) for r in rows[:30]]

    def last_seen(self, object_id: str) -> dict[str, Any]:
        """Latest sighting by event time, the place it sits in, and earlier sightings."""
        rows = self._claims("subject_id=? AND predicate='located_at'", (object_id,), history=True)
        rows.sort(key=lambda r: r["event_time"] or "", reverse=True)
        live = [r for r in rows if r["status"] != "superseded"]
        if not live:
            return {"latest": None, "note": "no readable sighting"}
        latest = live[0]
        out: dict[str, Any] = {"latest": self.view(latest),
                               "earlier_sightings": [self.view(r) for r in rows if r is not latest]}
        context, cur, seen = [], latest["object_id"], {object_id}
        while cur and cur not in seen and len(context) < 3:
            seen.add(cur)
            parent = self._claims("subject_id=? AND predicate='located_at'", (cur,))
            if not parent:
                break
            parent.sort(key=lambda r: r["event_time"] or "", reverse=True)
            context.append(self.view(parent[0]))
            cur = parent[0]["object_id"]
        if context:
            out["place_context"] = context
        if any(r["status"] == "disputed" for r in rows):
            out["note"] = "sightings conflict; report the conflict"
        return out

    def episodes(self, time_from: str | None = None, time_to: str | None = None,
                 near_lat: float | None = None, near_lon: float | None = None,
                 radius_m: float = 150.0) -> list[dict]:
        out = []
        for e in self.conn.execute("SELECT * FROM entities WHERE type='episode' ORDER BY name"):
            a = json.loads(e["attrs"])
            if time_from and a["end"] < time_from or time_to and a["start"] > time_to:
                continue
            if near_lat is not None and near_lon is not None and a.get("lat") is not None and \
                    haversine_m(near_lat, near_lon, a["lat"], a["lon"]) > radius_m:
                continue
            members = self._claims("episode_id=? AND predicate='part_of_episode'", (e["entity_id"],))
            if not members:
                continue
            summary = self._claims("subject_id=? AND predicate='summary_of'", (e["entity_id"],))
            item = {"episode_id": e["entity_id"], "name": e["name"], "start": when(a["start"]),
                    "end": when(a["end"]),
                    "participants": sorted({self._name(m["subject_id"]) for m in members})}
            if summary:
                item["summary"] = self.view(summary[0])
            out.append(item)
        return out

    def neighbors(self, entity_id: str, predicate: str | None = None) -> list[dict]:
        where = "(subject_id=? OR object_id=?)"
        args: tuple = (entity_id, entity_id)
        if predicate:
            where, args = where + " AND predicate=?", (*args, predicate)
        else:
            where += " AND predicate NOT IN ('part_of_episode','summary_of')"
        rows = sorted(self._claims(where, args), key=lambda r: r["event_time"] or "")
        return [self.view(r) for r in rows[:30]]

    def provenance(self, claim_id: str, _depth: int = 0) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        if not row or not self._readable(row, history=True):
            return {"error": "claim not available"}
        node = self.view(row)
        node["justifications"] = []
        live = self._live_sources()
        for j in self.conn.execute("SELECT * FROM justifications WHERE claim_id=?", (claim_id,)):
            if j["kind"] == "source":
                s = self.conn.execute("SELECT * FROM sources WHERE source_id=?",
                                      (j["source_id"],)).fetchone()
                if s and s["source_id"] in live:
                    node["justifications"].append({"kind": "source", "source": {
                        "source_id": s["source_id"], "kind": s["kind"],
                        "captured_at": when(s["captured_at"]), "text": s["text"]}})
            else:
                premises = [p["premise_claim_id"] for p in self.conn.execute(
                    "SELECT premise_claim_id FROM justification_premises WHERE justification_id=?",
                    (j["justification_id"],))]
                item: dict[str, Any] = {"kind": "derivation", "rule": j["rule"]}
                if _depth < 2:
                    item["premises"] = [self.provenance(p, _depth + 1) for p in premises]
                node["justifications"].append(item)
        return node

    def _live_sources(self) -> set[str]:
        from ..privacy.filter import valid_source_ids
        return valid_source_ids(self.conn)
