"""To-dos: the owner's own promises and the requests made of the owner.

A to-do is not stored as its own record. It is a readable claim (the privacy filter decides that, as
for every other read) with predicate `committed_to` whose subject is the owner, or `requested` whose
object is the owner. Only its state (open, done, dismissed) is kept here, and a claim with no row is
open. Promises made by other people are never to-dos. There are no due dates: the item shows the
person's own words.
"""
import sqlite3
from datetime import datetime
from typing import Any

from .privacy import clock
from .privacy.filter import READABLE, authorized_claim_ids
from .recall.tools import RecallTools

STATES = ("open", "done", "dismissed")
_SOURCE_LABELS = {"transcript_segment": "conversation", "user_confirmation": "note",
                  "frame_observation": "photo", "calendar_event": "calendar",
                  "location_fix": "location"}


def _label(supported_by: list[str]) -> str:
    kinds = [k for k in supported_by if not k.startswith("derived:")]
    return _SOURCE_LABELS.get(kinds[0], kinds[0]) if kinds else "memory"


def _clock_time(iso: str | None) -> str | None:
    return datetime.fromisoformat(iso).strftime("%H:%M") if iso else None


def list_todos(conn: sqlite3.Connection, owner_id: str, state: str = "open") -> list[dict[str, Any]]:
    """To-dos in `state` (or every state for "all"), oldest first."""
    if state != "all" and state not in STATES:
        raise ValueError(f"unknown state {state!r}")
    marks = ",".join("?" * len(READABLE))
    rows = conn.execute(
        f"SELECT * FROM claims WHERE status IN ({marks}) AND ((predicate='committed_to' AND subject_id=?)"
        " OR (predicate='requested' AND object_id=?)) ORDER BY event_time, claim_id",
        (*READABLE, owner_id, owner_id)).fetchall()
    ok = authorized_claim_ids(conn)
    states = {r["claim_id"]: r["state"] for r in conn.execute("SELECT claim_id, state FROM todo_state")}
    tools = RecallTools(conn)
    out = []
    for r in rows:
        if r["claim_id"] not in ok:
            continue
        current = states.get(r["claim_id"], "open")
        if state != "all" and current != state:
            continue
        request = r["predicate"] == "requested"
        view = tools.view(r)
        who = tools._name(r["subject_id"] if request else r["object_id"])
        out.append({
            "claim_id": r["claim_id"], "kind": "request" if request else "promise",
            "text": r["object_value"] or r["text"], "who": who, "when": _clock_time(r["event_time"]),
            "source_label": _label(view["supported_by"]), "state": current, "citations": [view]})
    return out


def set_todo_state(conn: sqlite3.Connection, claim_id: str, state: str, owner_id: str = "me") -> None:
    """Raises ValueError for a bad state and KeyError for an id that is not a visible to-do."""
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}")
    if not any(t["claim_id"] == claim_id for t in list_todos(conn, owner_id, "all")):
        raise KeyError(claim_id)
    conn.execute(
        "INSERT INTO todo_state(claim_id, state, updated_at) VALUES (?,?,?)"
        " ON CONFLICT(claim_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
        (claim_id, state, clock.now_iso()))
    conn.commit()


def count_open(conn: sqlite3.Connection, owner_id: str) -> int:
    return len(list_todos(conn, owner_id, "open"))
