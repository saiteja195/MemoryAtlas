"""Automated leak probes. Each one looks for the removed material in a different store and
reports pass, fail or skipped. 'Skipped' is never counted as a pass.

All probes search for `terms`: phrases that were in the removed text and are not in anything
that remains (see terms.py). Nothing here prints or stores the terms, only counts and digests.
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..capture.audit import media_bytes_on_disk
from ..compiler.episodes import episode_extent
from ..embed import embed
from ..llm.base import LLMClient, LLMUnavailable
from .export import export_memories
from .filter import authorized_claim_ids, valid_source_ids
from .terms import tokens

PASS, FAIL, SKIPPED = "pass", "fail", "skipped"
NEIGHBOURS = 3


@dataclass
class ProbeResult:
    id: int
    name: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail}


def _leaves(node: Any):
    """Every string value in a JSON structure (keys are the app's own field names)."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _leaves(v)
    elif isinstance(node, list):
        for v in node:
            yield from _leaves(v)


def contains(haystack: str, terms: list[str]) -> list[str]:
    """Terms that occur in `haystack` as whole-word phrases (case-insensitive).

    JSON text is searched one string value at a time: phrases must never be formed by the
    layout of the document (`"predicate": "said", "value": ...` is not the phrase "said value")."""
    try:
        parsed = json.loads(haystack)
    except (ValueError, TypeError):
        parsed = None
    texts = list(_leaves(parsed)) if isinstance(parsed, (dict, list)) else [haystack]
    found: list[str] = []
    for text in texts:
        h = " " + " ".join(tokens(text)) + " "
        found += [t for t in terms if f" {t} " in h and t not in found]
    return found


def _result(i: int, name: str, hits: int, **detail: Any) -> ProbeResult:
    return ProbeResult(i, name, PASS if hits == 0 else FAIL, {"hits": hits, **detail})


# 1 ---------------------------------------------------------------------------------------------

def graph_support(conn: sqlite3.Connection, removed_entity_ids: list[str]) -> ProbeResult:
    """Every remaining claim has a valid support path; nothing dangles."""
    ok = authorized_claim_ids(conn)
    claims = {r["claim_id"] for r in conn.execute("SELECT claim_id FROM claims")}
    live = valid_source_ids(conn)
    unsupported = len(claims - ok)
    dead_src = conn.execute(
        "SELECT COUNT(*) FROM justifications j LEFT JOIN sources s ON s.source_id=j.source_id"
        " WHERE j.kind='source' AND (s.source_id IS NULL OR s.status != 'active')").fetchone()[0]
    dead_prem = conn.execute(
        "SELECT COUNT(*) FROM justification_premises p LEFT JOIN claims c ON c.claim_id ="
        " p.premise_claim_id WHERE c.claim_id IS NULL").fetchone()[0]
    dangling = conn.execute(
        "SELECT COUNT(*) FROM claims c WHERE c.superseded_by IS NOT NULL AND NOT EXISTS"
        " (SELECT 1 FROM claims d WHERE d.claim_id = c.superseded_by)").fetchone()[0]
    entities = {r["entity_id"] for r in conn.execute("SELECT entity_id FROM entities")}
    leftover = len(entities & set(removed_entity_ids))
    stale_episodes = 0
    for e in conn.execute("SELECT attrs FROM entities WHERE type='episode'"):
        a = json.loads(e["attrs"] or "{}")
        contrib = a.get("contrib")
        if not contrib:
            stale_episodes += 1                  # no record of where its time and place came from
            continue
        stale = any(c["source_id"] is not None and c["source_id"] not in live for c in contrib)
        stale = stale or any(a.get(k) != v for k, v in episode_extent(contrib).items())
        stale_episodes += bool(stale)
    total = unsupported + dead_src + dead_prem + dangling + leftover + stale_episodes
    return _result(1, "Graph: no claim or episode rests on removed support", total, claims=len(claims),
                   unsupported_claims=unsupported, justifications_on_revoked_sources=dead_src,
                   premises_missing=dead_prem, dangling_supersession=dangling,
                   removed_entities_still_present=leftover,
                   episode_metadata_from_removed_sources=stale_episodes, live_sources=len(live))


# 2 ---------------------------------------------------------------------------------------------

def search_index(conn: sqlite3.Connection, terms: list[str]) -> ProbeResult:
    """Full-text search, and a plain scan of the stored text, find none of the terms."""
    fts_hits = 0
    for t in terms:
        q = '"' + t.replace('"', '""') + '"'
        fts_hits += conn.execute("SELECT COUNT(*) FROM claim_index WHERE claim_index MATCH ?",
                                 (q,)).fetchone()[0]
    scan = 0
    for r in conn.execute("SELECT text, object_value FROM claims"):
        scan += len(contains(r["text"] or "", terms)) + len(contains(r["object_value"] or "", terms))
    for r in conn.execute("SELECT text FROM sources"):
        scan += len(contains(r["text"] or "", terms))
    index_rows = conn.execute("SELECT COUNT(*) FROM claim_index").fetchone()[0]
    claim_rows = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    orphan_rows = abs(index_rows - claim_rows)      # a leftover or missing index row
    return _result(2, "Search index: removed phrases return nothing", fts_hits + scan + orphan_rows,
                   terms=len(terms), fts_hits=fts_hits, text_scan_hits=scan,
                   index_row_mismatch=orphan_rows)


# 3 ---------------------------------------------------------------------------------------------

def vectors(conn: sqlite3.Connection, removed_texts: list[str], terms: list[str]) -> ProbeResult:
    """No vector without a claim, and the nearest neighbours of the removed text are clean."""
    orphan = conn.execute("SELECT COUNT(*) FROM claim_vectors v WHERE NOT EXISTS (SELECT 1 FROM"
                          " claims c WHERE c.claim_id = v.claim_id)").fetchone()[0]
    rows = conn.execute("SELECT v.claim_id, v.vec, c.text, c.object_value FROM claim_vectors v"
                        " JOIN claims c ON c.claim_id = v.claim_id").fetchall()
    leaked = 0
    for text in removed_texts:
        q = embed(text)
        ranked = sorted(rows, key=lambda r: -float(np.dot(q, np.frombuffer(r["vec"],
                                                                           dtype=np.float32))))
        for r in ranked[:NEIGHBOURS]:
            leaked += len(contains(r["text"] or "", terms)) + \
                len(contains(r["object_value"] or "", terms))
    return _result(3, "Vectors: no orphan vectors, neighbours of removed text are clean",
                   orphan + leaked, orphan_vectors=orphan, leaking_neighbours=leaked,
                   queries=len(removed_texts))


# 4 ---------------------------------------------------------------------------------------------

def caches_and_chat(conn: sqlite3.Connection, terms: list[str], cache_dir: str | None
                    ) -> ProbeResult:
    """Answer cache, chat log and the app's own model-response cache hold nothing removed."""
    valid = {r["claim_id"] for r in conn.execute("SELECT claim_id FROM claims")}
    stale = 0
    for r in conn.execute("SELECT answer_json, claim_ids FROM answer_cache"):
        ids = json.loads(r["claim_ids"])
        stale += (any(i not in valid for i in ids) or bool(contains(r["answer_json"], terms)))
    chat = 0
    for r in conn.execute("SELECT text, claim_ids FROM chat_messages"):
        ids = json.loads(r["claim_ids"])
        chat += (any(i not in valid for i in ids) or bool(contains(r["text"], terms)))
    files, remaining = 0, 0
    if cache_dir and Path(cache_dir).is_dir():
        for p in Path(cache_dir).glob("*.json"):
            remaining += 1                      # the whole runtime cache is cleared, so any file is a leak
            files += bool(contains(p.read_text(), terms))
    receipts = sum(bool(contains(r["report_json"], terms) or '"text"' in r["report_json"].replace(" ", ""))
                   for r in conn.execute("SELECT report_json FROM forgetting_receipts"))
    return _result(4, "Caches: answer cache, chat log, receipts and model-response cache are clean",
                   stale + chat + remaining + receipts, answer_cache_rows=int(stale), chat_rows=int(chat),
                   model_cache_files_with_removed_text=files, model_cache_files_remaining=remaining,
                   receipts_holding_text=receipts,
                   model_cache="runtime directory" if cache_dir else "none configured")


# 5 ---------------------------------------------------------------------------------------------

def export(conn: sqlite3.Connection, terms: list[str]) -> ProbeResult:
    """A freshly generated export of everything contains none of the removed phrases."""
    blob = json.dumps(export_memories(conn), ensure_ascii=False)
    return _result(5, "Export: a regenerated export mentions nothing removed",
                   len(contains(blob, terms)), export_bytes=len(blob))


# 6 ---------------------------------------------------------------------------------------------

def red_team(conn: sqlite3.Connection, llm: LLMClient | None, questions: list[str],
             terms: list[str]) -> ProbeResult:
    """Adversarial questions put to the real investigator never surface a removed fact."""
    from ..recall.investigator import Investigator
    if llm is None or not questions:
        return ProbeResult(6, "Red team: adversarial questions leak nothing", SKIPPED,
                           {"reason": "no model client or no questions configured"})
    inv, leaks, answered = Investigator(conn, llm), 0, []
    try:
        for q in questions:
            a = inv.ask(q)
            # Echoing the question back is not a leak: ignore what the asker supplied.
            fresh = [t for t in terms if not contains(q, [t])]
            leaks += len(contains(a.answer, fresh)) + len(contains(a.uncertainty_note, fresh))
            answered.append(a.status)
    except LLMUnavailable as e:
        return ProbeResult(6, "Red team: adversarial questions leak nothing", SKIPPED,
                           {"reason": f"model unavailable: {str(e)[:120]}",
                            "completed": len(answered)})
    return _result(6, "Red team: adversarial questions leak nothing", leaks,
                   questions=len(questions), statuses=answered)


# 7 ---------------------------------------------------------------------------------------------

def disk(db_path: str | None, media_dirs: list[str], terms: list[str]) -> ProbeResult:
    """No media files anywhere, and the database files do not contain the removed text."""
    media = media_bytes_on_disk(*media_dirs, recursive=False) if media_dirs else 0
    raw_hits, files = 0, []
    if db_path and db_path != ":memory:":
        for suffix in ("", "-wal", "-shm"):
            p = Path(db_path + suffix)
            if p.exists():
                files.append(p.name)
                data = p.read_bytes().lower()
                raw_hits += sum(1 for t in terms if re.search(
                    rb"(?<![0-9a-z_])" + re.escape(t.encode("utf-8")) + rb"(?![0-9a-z_])", data))
    return _result(7, "Disk: no media files, and the database file holds no removed text",
                   media + raw_hits, media_bytes=media, raw_term_hits=raw_hits,
                   files_scanned=files or ["in-memory database: no file to scan"])


def run_probes(conn: sqlite3.Connection, *, terms: list[str], removed_texts: list[str],
               removed_entity_ids: list[str], db_path: str | None, media_dirs: list[str],
               cache_dir: str | None, llm: LLMClient | None, red_team_questions: list[str],
               red_team_terms: list[str] | None = None, run_red_team: bool = True
               ) -> list[ProbeResult]:
    steps: list[Callable[[], ProbeResult]] = [
        lambda: graph_support(conn, removed_entity_ids),
        lambda: search_index(conn, terms),
        lambda: vectors(conn, removed_texts, terms),
        lambda: caches_and_chat(conn, terms, cache_dir),
        lambda: export(conn, terms),
        (lambda: red_team(conn, llm, red_team_questions,
                          terms if red_team_terms is None else red_team_terms)) if run_red_team else
        (lambda: ProbeResult(6, "Red team: adversarial questions leak nothing", SKIPPED,
                             {"reason": "turned off for this call"})),
        lambda: disk(db_path, media_dirs, terms),
    ]
    return [s() for s in steps]
