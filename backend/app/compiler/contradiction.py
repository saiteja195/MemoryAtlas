"""Step 6 of the compiler (deterministic): flag contradictory location claims.

Two `located_at` claims for the same subject that are within five minutes of each other and
name different places cannot both hold, so both become `disputed` and answers must show the
conflict. Sightings far apart in time are not a contradiction: that is the thing moving, and
the recall layer reports the latest one (Phase 2).
"""
import sqlite3
from datetime import datetime, timedelta

CONFLICT_WINDOW = timedelta(minutes=5)


def contradiction_pass(conn: sqlite3.Connection, subject_ids: set[str]) -> list[tuple[str, str]]:
    disputed: list[tuple[str, str]] = []
    for sid in subject_ids:
        rows = conn.execute(
            "SELECT claim_id, object_id, event_time FROM claims WHERE subject_id=? AND"
            " predicate='located_at' AND status IN ('active','disputed') AND object_id IS NOT NULL"
            " AND event_time IS NOT NULL", (sid,)).fetchall()
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a["object_id"] == b["object_id"]:
                    continue
                gap = abs(datetime.fromisoformat(a["event_time"]) -
                          datetime.fromisoformat(b["event_time"]))
                if gap <= CONFLICT_WINDOW:
                    conn.execute("UPDATE claims SET status='disputed' WHERE claim_id IN (?,?)",
                                 (a["claim_id"], b["claim_id"]))
                    disputed.append((a["claim_id"], b["claim_id"]))
    return disputed
