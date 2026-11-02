"""The baseline: what a typical retrieval memory does with the same text observations.

Chunk the text of every stored observation, index it with keyword (FTS5/bm25) and vector search, retrieve
the top 8 by reciprocal-rank fusion, and let the same model answer from those excerpts. An end-of-day
summary note is written by the model and indexed too. There is no graph, no provenance and no support
tracking: deleting a source means deleting its chunks.

Two variants differ only after a deletion:
  stale    the summary note is left as it was (what a plain index does)
  rebuilt  the summary is regenerated from the remaining chunks (a careful implementation)
"""
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..embed import cosine, embed
from ..llm.base import LLMClient, LLMUnavailable

TOP_K = 8
CHUNK_CHARS = 600
RRF_K = 60

SYSTEM = """You answer questions about the user's day from memory excerpts. Each excerpt starts with the time it was
recorded. Use only the excerpts. If they do not contain the answer, say you have no record instead of
guessing. When excerpts disagree about a fact, prefer the most recent one and mention the earlier one.
Reply with ONE JSON object: {"status":"answered|abstained","answer":"...","cited":["excerpt ids"]}.
Keep the answer to one or two sentences."""
ANSWER_SCHEMA = {"type": "object", "properties": {"status": {"enum": ["answered", "abstained"]},
                 "answer": {"type": "string"}, "cited": {"type": "array", "items": {"type": "string"}}},
                 "required": ["status", "answer"]}
SUMMARY_SYSTEM = """You keep an end-of-day memory note. Summarise the day from these records in at most 120 words.
Use only the records. Reply with one JSON object: {"summary": "..."}."""
SUMMARY_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    at: str
    text: str


def chunk_source(source_id: str, at: str, text: str) -> list[Chunk]:
    """One chunk per ~600 characters, split on sentence ends, each prefixed with its time."""
    stamp = at.replace("T", " ")[:16]
    pieces, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if cur and len(cur) + len(sent) > CHUNK_CHARS:
            pieces.append(cur)
            cur = ""
        cur = f"{cur} {sent}".strip()
    if cur:
        pieces.append(cur)
    return [Chunk(f"{source_id}#{i}", source_id, at, f"[{stamp}] {p}") for i, p in enumerate(pieces)]


class Baseline:
    def __init__(self, llm: LLMClient, rebuild_summary: bool):
        self.llm, self.rebuild = llm, rebuild_summary
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE fts USING fts5(chunk_id UNINDEXED, text)")
        self.chunks: dict[str, Chunk] = {}
        self.vecs: dict[str, Any] = {}
        self.known: set[str] = set()          # source ids currently indexed

    # -- index ------------------------------------------------------------------------------

    def _add(self, c: Chunk) -> None:
        self.chunks[c.chunk_id] = c
        self.vecs[c.chunk_id] = embed(c.text)
        self.db.execute("INSERT INTO fts(chunk_id, text) VALUES (?,?)", (c.chunk_id, c.text))

    def _remove(self, chunk_id: str) -> None:
        self.chunks.pop(chunk_id, None)
        self.vecs.pop(chunk_id, None)
        self.db.execute("DELETE FROM fts WHERE chunk_id=?", (chunk_id,))

    def sync(self, sources: list[dict[str, str]]) -> dict[str, int]:
        """Make the index match the stored observations: add new ones, delete the chunks of gone ones.
        The summary is regenerated when something was added, and after a deletion only if `rebuild`."""
        live = {s["source_id"]: s for s in sources}
        added = [sid for sid in live if sid not in self.known]
        gone = [sid for sid in self.known if sid not in live]
        for sid in added:
            for c in chunk_source(sid, live[sid]["captured_at"], live[sid]["text"]):
                self._add(c)
        for cid in [c for c, ch in self.chunks.items() if ch.source_id in gone]:
            self._remove(cid)
        self.known = set(live)
        if added or (gone and self.rebuild):
            self._write_summary()
        return {"added": len(added), "deleted": len(gone)}

    def _write_summary(self) -> None:
        self._remove("summary")
        records = "\n".join(c.text for c in sorted(self.chunks.values(), key=lambda c: c.at))
        try:
            text = self.llm.complete_json(SUMMARY_SYSTEM, records, SUMMARY_SCHEMA).get("summary", "")
        except LLMUnavailable:
            text = ""
        if text:
            self._add(Chunk("summary", "summary", "9999", f"[end-of-day note] {text}"))

    def dump(self, include_summary: bool = True) -> str:
        """Everything the index stores, for the leak scan."""
        return "\n".join(c.text for c in self.chunks.values() if include_summary or c.chunk_id != "summary")

    def summary_text(self) -> str:
        c = self.chunks.get("summary")
        return c.text if c else ""

    # -- retrieval --------------------------------------------------------------------------

    def search(self, question: str, k: int = TOP_K) -> list[Chunk]:
        words = [w for w in re.findall(r"[A-Za-z0-9']+", question.lower()) if len(w) > 2]
        keyword: list[str] = []
        if words:
            q = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
            keyword = [r[0] for r in self.db.execute(
                "SELECT chunk_id FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?", (q, k * 3))]
        qv = embed(question)
        vector = [cid for cid, _ in sorted(((cid, cosine(qv, v)) for cid, v in self.vecs.items()),
                                           key=lambda x: (-x[1], x[0]))[:k * 3]]
        score: dict[str, float] = {}
        for ranking in (keyword, vector):
            for rank, cid in enumerate(ranking):
                score[cid] = score.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        top = sorted(score, key=lambda c: (-score[c], c))[:k]
        return [self.chunks[c] for c in top]

    # -- answering --------------------------------------------------------------------------

    def ask(self, question: str) -> dict[str, Any]:
        hits = self.search(question)
        excerpts = "\n".join(f"({c.chunk_id}) {c.text}" for c in hits)
        user = f"EXCERPTS:\n{excerpts}\n\nQUESTION: {question}"
        res = self.llm.complete_json(SYSTEM, user, ANSWER_SCHEMA)
        status = res.get("status") if res.get("status") in ("answered", "abstained") else "answered"
        return {"status": status, "answer": str(res.get("answer", "")).strip(),
                "cited": [str(x) for x in res.get("cited", []) if isinstance(x, str)],
                "retrieved": [c.chunk_id for c in hits]}
