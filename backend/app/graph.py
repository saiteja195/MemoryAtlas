"""Read model for the Atlas UI: entities as nodes, claims as edges."""
import json
import sqlite3
from typing import Any

from .privacy.filter import authorized_claim_ids, valid_source_ids


def _first_seen(conn: sqlite3.Connection, live: set[str]) -> tuple[dict, dict]:
    """When each claim first became knowable, and what supports it.

    A source-backed claim is knowable when its earliest live source was captured. A derived
    claim is knowable when ALL premises of one of its derivations are (the latest of them)."""
    support: dict[str, list[dict[str, Any]]] = {}
    seen: dict[str, str] = {}
    sources = {r["source_id"]: r for r in conn.execute("SELECT source_id, kind, captured_at"
                                                       " FROM sources")}
    derivations: dict[str, dict[str, Any]] = {}
    for j in conn.execute("SELECT justification_id, claim_id, kind, source_id, rule"
                          " FROM justifications"):
        if j["kind"] == "source":
            if j["source_id"] in live:
                s = sources[j["source_id"]]
                support.setdefault(j["claim_id"], []).append(
                    {"kind": s["kind"], "at": s["captured_at"]})
                seen[j["claim_id"]] = min(seen.get(j["claim_id"], s["captured_at"]),
                                          s["captured_at"])
        else:
            derivations[j["justification_id"]] = {"claim": j["claim_id"], "rule": j["rule"],
                                                  "premises": []}
    for p in conn.execute("SELECT justification_id, premise_claim_id FROM justification_premises"):
        if p["justification_id"] in derivations:
            derivations[p["justification_id"]]["premises"].append(p["premise_claim_id"])
    changed = True
    while changed:
        changed = False
        for d in derivations.values():
            if d["premises"] and all(p in seen for p in d["premises"]):
                when = max(seen[p] for p in d["premises"])
                if d["claim"] not in seen or when < seen[d["claim"]]:
                    seen[d["claim"]] = when
                    changed = True
    for d in derivations.values():
        if d["premises"] and all(p in seen for p in d["premises"]):
            support.setdefault(d["claim"], []).append(
                {"kind": "derivation", "rule": d["rule"], "premises": sorted(d["premises"]),
                 "at": max(seen[p] for p in d["premises"])})
    return seen, support


def _public(attrs: dict[str, Any]) -> dict[str, Any]:
    """Entity attributes as shown to a client. `contrib` is internal provenance (source ids)."""
    return {k: v for k, v in attrs.items() if k != "contrib"}


def build_graph(conn: sqlite3.Connection, at: str | None = None,
                include_history: bool = False) -> dict[str, Any]:
    """`at` limits the graph to what had been captured by that time (for the timeline).
    Superseded claims appear only with include_history. Only claims that still have valid,
    consented support are returned, so revoked material never reaches the UI."""
    seen, support = _first_seen(conn, valid_source_ids(conn))
    ok = authorized_claim_ids(conn)
    statuses = ("active", "disputed", "superseded") if include_history else ("active", "disputed")
    marks = ",".join("?" * len(statuses))
    claims = conn.execute(f"SELECT * FROM claims WHERE status IN ({marks}) ORDER BY event_time",
                          statuses).fetchall()
    edges, used = [], set()
    for c in claims:
        first = seen.get(c["claim_id"])
        if c["claim_id"] not in ok or first is None or (at and first > at):
            continue
        used.add(c["subject_id"])
        if c["object_id"]:
            used.add(c["object_id"])
        edges.append({
            "id": c["claim_id"], "source": c["subject_id"], "target": c["object_id"],
            "predicate": c["predicate"], "value": c["object_value"], "text": c["text"],
            "status": c["status"], "evidence_type": c["evidence_type"],
            "confidence": c["confidence"], "event_time": c["event_time"],
            "episode_id": c["episode_id"], "superseded_by": c["superseded_by"],
            "support": support.get(c["claim_id"], []),
        })
    nodes = []
    for e in conn.execute("SELECT * FROM entities ORDER BY type, name"):
        if e["entity_id"] in used:
            nodes.append({"id": e["entity_id"], "type": e["type"], "name": e["name"],
                          "attrs": _public(json.loads(e["attrs"])) if e["attrs"] else None})
    return {"at": at, "include_history": include_history, "nodes": nodes, "edges": edges}
