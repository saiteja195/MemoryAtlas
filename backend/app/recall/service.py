"""Question answering service: cache, chat log and the investigator."""
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from ..compiler.resolve import norm
from ..insights.coverage import memory_days
from ..llm.base import LLMClient
from ..privacy import clock
from ..privacy.filter import authorized_claim_ids
from .investigator import Answer, Investigator
from .router import needs_extended
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
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, owner: str = "me"):
        self.conn, self.llm = conn, llm
        self.investigator = Investigator(conn, llm, owner=owner)

    def ask(self, question: str, as_of: str | None = None) -> dict[str, Any]:
        """`as_of` (YYYY-MM-DD) is the day "today" means; it defaults to the latest day with memories
        (None when there are none, and then no question is routed)."""
        if as_of is None:
            days = memory_days(self.conn)
            as_of = days[-1] if days else None
        route = needs_extended(question) if as_of else None
        # Unrouted: the original key, so the day does not matter. Routed: the day is part of the
        # question, so the same words on two days are two cache entries.
        key = f"{route}|{as_of}|{norm(question)}" if route else norm(question)
        qhash = hashlib.sha256(key.encode()).hexdigest()
        version = graph_version(self.conn)
        # Ruling R-G(c): a memory question (coverage, the models' usage) is never cached at all. Even an
        # abstention or a claim-only answer could outlive new usage, which does not change the graph version.
        # A to-do answer changes when a to-do is ticked or dismissed, which the graph version does not see.
        cacheable = route not in ("memory", "todo")
        row = self.conn.execute("SELECT answer_json FROM answer_cache WHERE question_hash=?",
                                (qhash,)).fetchone() if cacheable else None
        if row:
            cached = json.loads(row["answer_json"])
            # An answer built from coverage or usage_stats is never reused: usage changes without the
            # graph version changing (ruling R-C). Such answers are never written, so this is a guard.
            if cached.get("graph_version") == version and not cached.get("cited_tools"):
                cached["cached"] = True
                self._log(question, cached, as_of)
                return cached
        ans: Answer = self.investigator.ask(question, as_of)
        out = ans.as_dict()
        out["citations"] = self._citations(ans.cited_claim_ids)
        out["graph_version"], out["cached"] = version, False
        if cacheable and not ans.cited_tools:
            self.conn.execute("INSERT OR REPLACE INTO answer_cache(question_hash, answer_json,"
                              " claim_ids) VALUES (?,?,?)",
                              (qhash, json.dumps(out), json.dumps(ans.cited_claim_ids)))
        self._log(question, out, as_of)
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

    def _log(self, question: str, out: dict[str, Any], as_of: str | None) -> None:
        cols = "(msg_id, role, text, claim_ids, as_of, status, cited_tools)"
        self.conn.execute(f"INSERT INTO chat_messages{cols} VALUES (?,?,?,?,?,?,?)",
                          (uuid.uuid4().hex, "user", question, "[]", as_of, None, "[]"))
        self.conn.execute(f"INSERT INTO chat_messages{cols} VALUES (?,?,?,?,?,?,?)",
                          (uuid.uuid4().hex, "assistant", out["answer"], json.dumps(out["cited_claim_ids"]),
                           as_of, out["status"], json.dumps(out.get("cited_tools", []))))
        self.conn.commit()

    def history(self) -> list[dict[str, Any]]:
        """The whole conversation, oldest first. A citation is shown only while its claim may still be read;
        a message the forgetting code redacted has no citations and its stored text is the redaction notice."""
        readable = authorized_claim_ids(self.conn)
        out = []
        for r in self.conn.execute("SELECT * FROM chat_messages ORDER BY rowid").fetchall():
            ids = [c for c in json.loads(r["claim_ids"]) if c in readable]
            out.append({"id": r["msg_id"], "role": r["role"], "text": r["text"], "as_of": r["as_of"],
                        "status": r["status"], "cited_claim_ids": ids, "citations": self._citations(ids),
                        "cited_tools": json.loads(r["cited_tools"] or "[]"), "redacted": bool(r["redacted"])})
        return out

    def provenance(self, claim_id: str) -> dict[str, Any]:
        tools = RecallTools(self.conn)
        return tools.run("provenance", {"claim_id": claim_id})
