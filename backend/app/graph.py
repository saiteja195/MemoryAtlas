"""Read model for the Atlas UI: entities as nodes, claims as edges."""
import json
import sqlite3
from typing import Any

SOURCE_KINDS_SQL = ("SELECT j.claim_id, s.kind, s.captured_at, s.status FROM justifications j"
                    " JOIN sources s ON s.source_id = j.source_id WHERE j.kind='source'")


def build_graph(conn: sqlite3.Connection, at: str | None = None,
                include_history: bool = False) -> dict[str, Any]:
    """`at` limits the graph to what had been captured by that time (for the timeline).
    Superseded claims appear only with include_history. Revoked claims never appear."""
    support: dict[str, list[dict[str, str]]] = {}
    first_seen: dict[str, str] = {}
    for r in conn.execute(SOURCE_KINDS_SQL):
        if r["status"] != "active":
            continue
        support.setdefault(r["claim_id"], []).append({"kind": r["kind"], "at": r["captured_at"]})
        first_seen[r["claim_id"]] = min(first_seen.get(r["claim_id"], r["captured_at"]),
                                        r["captured_at"])
    statuses = ("active", "disputed", "superseded") if include_history else ("active", "disputed")
    marks = ",".join("?" * len(statuses))
    claims = conn.execute(f"SELECT * FROM claims WHERE status IN ({marks}) ORDER BY event_time",
                          statuses).fetchall()
    edges, used = [], set()
    for c in claims:
        seen = first_seen.get(c["claim_id"])
        if seen is None or (at and seen > at):
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
                          "attrs": json.loads(e["attrs"]) if e["attrs"] else None})
    return {"at": at, "include_history": include_history, "nodes": nodes, "edges": edges}
