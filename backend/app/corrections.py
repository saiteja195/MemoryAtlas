"""User corrections: "that is wrong" (retract) or "that is wrong, it is X" (replace).

A correction never deletes. The corrected claim becomes `superseded` history, and so does any claim that
was derived only from it, so the next answer stops using them while the earlier version stays inspectable.
The replacement is recorded as an ordinary user-confirmed note under the owner's own consent, and goes
through the same compiler as every other source. Deterministic code decides what is superseded.
"""
import json
import sqlite3
from datetime import datetime
from typing import Any

from .capture.models import RawCapture
from .compiler.contradiction import contradiction_pass
from .engine import MemoryEngine
from .privacy import clock
from .privacy.filter import PURPOSE, READABLE, authorized_claim_ids


class CorrectionError(Exception):
    """`code` is the HTTP status the API maps it to."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _owner_session(conn: sqlite3.Connection, owner: str) -> str | None:
    """The session of the owner's newest standing grant: a correction is the owner speaking, so it rests
    on their own consent, never anyone else's."""
    for r in conn.execute(
            "SELECT scope_ref, purposes FROM consent_grants WHERE grantor=? AND scope='capture_session'"
            " AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)"
            " ORDER BY granted_at DESC, grant_id", (owner, clock.now_iso())):
        if PURPOSE in json.loads(r["purposes"]):
            return r["scope_ref"]
    return None


def dependents(conn: sqlite3.Connection, roots: set[str]) -> set[str]:
    """Claims that lose all their support if `roots` are set aside: every justification is a derivation
    that uses one of them (or one of the claims already found). Source-backed claims keep standing."""
    gone = set(roots)
    jus: dict[str, list[tuple[str, list[str]]]] = {}
    premises: dict[str, list[str]] = {}
    for p in conn.execute("SELECT justification_id, premise_claim_id FROM justification_premises"):
        premises.setdefault(p["justification_id"], []).append(p["premise_claim_id"])
    for j in conn.execute("SELECT justification_id, claim_id, kind FROM justifications"):
        jus.setdefault(j["claim_id"], []).append((j["kind"], premises.get(j["justification_id"], [])))
    live = {r["claim_id"] for r in conn.execute(
        "SELECT claim_id FROM claims WHERE status IN ('active','disputed')")}
    changed = True
    while changed:
        changed = False
        for cid in live - gone:
            js = jus.get(cid, [])
            if js and not any(kind == "source" or not (set(prem) & gone) for kind, prem in js):
                gone.add(cid)
                changed = True
    return gone


def _retire(conn: sqlite3.Connection, claim_id: str, replacement: str | None) -> list[str]:
    retired = dependents(conn, {claim_id})
    for cid in retired:
        conn.execute("UPDATE claims SET status='superseded', superseded_by=? WHERE claim_id=?",
                     (replacement if cid == claim_id else None, cid))
    # A dispute that rested on a claim now set aside no longer stands: recheck what is left.
    subjects = {r["subject_id"] for r in conn.execute(
        "SELECT DISTINCT subject_id FROM claims WHERE predicate='located_at' AND status='disputed'")}
    conn.execute("UPDATE claims SET status='active' WHERE predicate='located_at' AND status='disputed'")
    contradiction_pass(conn, subjects)
    return sorted(retired - {claim_id})


def correct_claim(engine: MemoryEngine, claim_id: str, text: str | None = None, retract: bool = False,
                  at: str | None = None) -> dict[str, Any]:
    conn = engine.conn
    row = conn.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
    # A fact that was forgotten, or that nobody may read, is reported as unknown, not as forgotten.
    if row is None or claim_id not in authorized_claim_ids(conn):
        raise CorrectionError(404, "unknown claim")
    if row["status"] not in READABLE:
        raise CorrectionError(409, f"this claim is already {row['status']}")
    text = (text or "").strip()
    if retract == bool(text):
        raise CorrectionError(422, "give either the corrected text, or retract=true")
    if retract:
        also = _retire(conn, claim_id, None)
        conn.commit()
        return {"corrected": claim_id, "replacement": None, "also_superseded": also, "source_id": None}

    owner = engine.gateway.owner
    session = _owner_session(conn, owner)
    if session is None:
        raise CorrectionError(409, "no standing consent from the owner to record a correction")
    cap = RawCapture(kind="note", session_id=session, captured_at=at or datetime.now().isoformat(timespec="seconds"),
                     text=text, ref="correction")
    results = engine.ingest(cap)
    got = results[0] if results else None
    if got is None or got.ingest.status != "ingested" or got.compiled is None:
        reason = got.ingest.reason if got else "bad_input"
        raise CorrectionError(422, f"the correction was not recorded ({reason})")
    new = [c for c in got.compiled.claim_ids if c != claim_id]
    rows = {r["claim_id"]: r for r in conn.execute(
        "SELECT claim_id, subject_id, predicate, status FROM claims WHERE claim_id IN (%s)"
        % ",".join("?" * len(new)), new)} if new else {}
    same = [c for c in new if rows.get(c) and rows[c]["subject_id"] == row["subject_id"]
            and rows[c]["predicate"] != "part_of_episode"]
    best = next((c for c in same if rows[c]["predicate"] == row["predicate"]), same[0] if same else None)
    if best is None:
        raise CorrectionError(422, "the correction was recorded as a note, but it did not state a "
                                   "replacement for this fact, so nothing was changed")
    also = _retire(conn, claim_id, best)
    if rows[best]["status"] == "superseded":      # a located_at rule may already have ordered them
        conn.execute("UPDATE claims SET status='active', superseded_by=NULL WHERE claim_id=?", (best,))
    conn.commit()
    return {"corrected": claim_id, "replacement": best, "also_superseded": also,
            "source_id": got.ingest.observation.source_id}
