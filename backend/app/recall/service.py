"""Question answering service: cache, chat log and the investigator."""
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from ..compiler.resolve import norm
from ..llm.base import LLMClient
from ..privacy import clock
from ..privacy.filter import authorized_claim_ids
from .investigator import Answer, Investigator
from .tools import RecallTools


def graph_version(conn: sqlite3.Connection) -> str:
    """Changes whenever a claim or source changes, so cached answers never go stale."""
    h = hashlib.sha1()
    for r in conn.execute("SELECT claim_id, status, COALESCE(superseded_by,'') s FROM claims"
                          " ORDER BY claim_id"):
        h.update(f"{r['claim_id']}{r['status']}{r['s']}".encode())
    for r in conn.execute("SELECT source_id, status FROM sources ORDER BY source_id"):
        h.update(f"{r['source_id']}{r['status']}".encode())
    # A grant that has lapsed changes what may be read, so it changes the version even before the purge runs.
    for r in conn.execute("SELECT grant_id, COALESCE(revoked_at,'') x, CASE WHEN expires_at IS NOT NULL"
                          " AND expires_at <= ? THEN 'expired' ELSE '' END e FROM consent_grants"
                          " ORDER BY grant_id", (clock.now_iso(),)):
        h.update(f"{r['grant_id']}{r['x']}{r['e']}".encode())
    return h.hexdigest()


class RecallService:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient):
        self.conn, self.llm = conn, llm
        self.investigator = Investigator(conn, llm)

    def ask(self, question: str) -> dict[str, Any]:
        qhash = hashlib.sha256(norm(question).encode()).hexdigest()
        version = graph_version(self.conn)
        row = self.conn.execute("SELECT answer_json FROM answer_cache WHERE question_hash=?",
                                (qhash,)).fetchone()
        if row:
            cached = json.loads(row["answer_json"])
            if cached.get("graph_version") == version:
                cached["cached"] = True
                self._log(question, cached)
                return cached
        ans: Answer = self.investigator.ask(question)
        out = ans.as_dict()
        out["citations"] = self._citations(ans.cited_claim_ids)
        out["graph_version"], out["cached"] = version, False
        self.conn.execute("INSERT OR REPLACE INTO answer_cache(question_hash, answer_json,"
                          " claim_ids) VALUES (?,?,?)",
                          (qhash, json.dumps(out), json.dumps(ans.cited_claim_ids)))
        self._log(question, out)
        return out

    def _citations(self, claim_ids: list[str]) -> list[dict[str, Any]]:
        tools = RecallTools(self.conn)
        tools._auth = authorized_claim_ids(self.conn)
        rows = []
        for cid in claim_ids:
            r = self.conn.execute("SELECT * FROM claims WHERE claim_id=?", (cid,)).fetchone()
            if r:
                rows.append(tools.view(r))
        return rows

    def _log(self, question: str, out: dict[str, Any]) -> None:
        self.conn.execute("INSERT INTO chat_messages(msg_id, role, text, claim_ids) VALUES (?,?,?,?)",
                          (uuid.uuid4().hex, "user", question, "[]"))
        self.conn.execute("INSERT INTO chat_messages(msg_id, role, text, claim_ids) VALUES (?,?,?,?)",
                          (uuid.uuid4().hex, "assistant", out["answer"],
                           json.dumps(out["cited_claim_ids"])))
        self.conn.commit()

    def provenance(self, claim_id: str) -> dict[str, Any]:
        tools = RecallTools(self.conn)
        return tools.run("provenance", {"claim_id": claim_id})
