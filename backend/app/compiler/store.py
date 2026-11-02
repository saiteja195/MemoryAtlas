"""Writes claims with their justifications, FTS row and vector."""
import hashlib
import sqlite3
from datetime import datetime

from ..embed import embed
from .resolve import norm


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ClaimWriter:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def claim_key(subject_id: str, predicate: str, object_id: str | None,
                  object_value: str | None, episode_id: str | None) -> str:
        raw = "|".join([subject_id, predicate, object_id or "", norm(object_value or ""),
                        episode_id or ""])
        return "clm-" + hashlib.sha1(raw.encode()).hexdigest()[:12]

    def write(self, *, subject_id: str, predicate: str, object_id: str | None,
              object_value: str | None, event_time: str | None, evidence_type: str,
              confidence: float, episode_id: str | None, text: str, source_id: str,
              valid_from: str | None = None, valid_to: str | None = None) -> tuple[str, bool]:
        """Insert a claim, or add the source as one more justification of an identical claim
        (this is how a fact gets independent support from two sources). Returns
        (claim_id, created)."""
        cid = self.claim_key(subject_id, predicate, object_id, object_value, episode_id)
        existing = self.conn.execute("SELECT confidence FROM claims WHERE claim_id=?",
                                     (cid,)).fetchone()
        created = existing is None
        if created:
            self.conn.execute(
                "INSERT INTO claims(claim_id, subject_id, predicate, object_id, object_value,"
                " event_time, valid_from, valid_to, evidence_type, confidence, episode_id, text,"
                " status, superseded_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'active',NULL,?)",
                (cid, subject_id, predicate, object_id, object_value, event_time, valid_from,
                 valid_to, evidence_type, confidence, episode_id, text, now_iso()))
            self.conn.execute("INSERT INTO claim_index(claim_id, text) VALUES (?,?)", (cid, text))
            self.conn.execute("INSERT INTO claim_vectors(claim_id, vec) VALUES (?,?)",
                              (cid, embed(text).tobytes()))
        elif confidence > existing["confidence"]:
            self.conn.execute("UPDATE claims SET confidence=? WHERE claim_id=?", (confidence, cid))
        if not self.conn.execute("SELECT 1 FROM justifications WHERE claim_id=? AND source_id=?",
                                 (cid, source_id)).fetchone():
            jid = "jst-" + hashlib.sha1(f"{cid}|{source_id}".encode()).hexdigest()[:12]
            self.conn.execute(
                "INSERT INTO justifications(justification_id, claim_id, kind, source_id, rule)"
                " VALUES (?,?,'source',?,NULL)", (jid, cid, source_id))
        return cid, created
