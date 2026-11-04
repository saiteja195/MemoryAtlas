"""Revocation engine: withdraw a consent grant and forget what only it supported.

Deterministic code decides everything here; no model is involved in what is removed.

1. Verify the secret token (an authenticated action by the person who consented).
2. Mark the grant revoked (and, for a recorded conversation, every participant's lines). A claim is dead when it no longer has a valid support path
   (least fixpoint from live, consented sources, see filter.py). Claims with other support
   survive, even derived ones whose premises all survive.
3. In one transaction remove the dead claims and everything built from them: justifications,
   search rows, vectors, orphaned entities, cached answers, chat messages; blank the revoked
   sources; block their content from being re-ingested; re-render survivors that lost a source
   so none carries wording that came only from the removed one.
4. Clean the database file (rebuild the index, checkpoint the log, VACUUM), empty the answer cache
   and the app's model-response cache, then run the leak probes and store a receipt.

Caches are derived copies, so they are cleared whole rather than searched for what was forgotten:
phrase matching misses short or numeric secrets and paraphrases. Receipts never store claim text;
the text of a kept fact is filled in when a receipt is read, and shows "[forgotten since]" once
that fact is gone.

Dead claims are deleted outright, not tombstoned: a tombstone would still reveal who the
claim was about and what it pointed at.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..compiler.contradiction import contradiction_pass
from ..compiler.derive import Deriver
from ..compiler.episodes import _label as episode_label, episode_extent, episode_id_for, reconstruct_contrib
from ..embed import counts, to_blob
from ..llm.base import LLMClient
from . import clock
from .consent import verify_token
from .filter import authorized_claim_ids, valid_source_ids
from .probes import PASS, FAIL, SKIPPED, ProbeResult, run_probes
from .terms import distinctive_terms, rare_terms, term_digest

REDACTED_CHAT = "[removed: this relied on information that was forgotten]"
FORGOTTEN_SINCE = "[forgotten since]"


class UnknownGrant(LookupError):
    pass


class UnknownMemory(LookupError):
    """No active saved memory has that id."""


class NotYourConsent(PermissionError):
    """Only the owner's own consent can be withdrawn without a code."""


class BadToken(PermissionError):
    pass


def _chunks(items: list[str], size: int = 400) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _delete_in(conn: sqlite3.Connection, sql: str, ids: list[str]) -> int:
    """Run `sql` (with one `{}` for the placeholder list) over `ids`, chunked."""
    n = 0
    for part in _chunks(ids):
        n += conn.execute(sql.format(",".join("?" * len(part))), part).rowcount
    return n


def digest(ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


class RevocationEngine:
    def __init__(self, conn: sqlite3.Connection, secret: str, llm: LLMClient | None = None,
                 owner: str = "me", db_path: str | None = None, cache_dir: str | None = None,
                 red_team_questions: list[str] | None = None):
        self.conn, self.secret, self.llm, self.owner = conn, secret, llm, owner
        self.db_path, self.cache_dir = db_path, cache_dir
        self.red_team_questions = red_team_questions or []

    # -- public ------------------------------------------------------------------------------

    def revoke(self, grant_id: str, token: str, run_red_team: bool = True) -> dict[str, Any]:
        """The person withdraws consent. The token proves it is them."""
        grant = self.conn.execute("SELECT * FROM consent_grants WHERE grant_id=?",
                                  (grant_id,)).fetchone()
        if grant is None:
            raise UnknownGrant(grant_id)
        if not verify_token(self.secret, token, grant["token_hash"]):
            raise BadToken(grant_id)
        return self._end(grant, "withdrawn", run_red_team)

    def revoke_own(self, grant_id: str, run_red_team: bool = True) -> dict[str, Any]:
        """The signed-in owner withdraws their own consent. Being signed in to this profile is the proof, so no code
        is needed. Anyone else's consent still needs that person's code (`revoke`)."""
        grant = self.conn.execute("SELECT * FROM consent_grants WHERE grant_id=?", (grant_id,)).fetchone()
        if grant is None:
            raise UnknownGrant(grant_id)
        if grant["grantor"] != self.owner:
            raise NotYourConsent(grant_id)
        return self._end(grant, "withdrawn", run_red_team)

    def delete_memory(self, source_id: str, run_red_team: bool = True) -> dict[str, Any]:
        """The owner deletes one saved memory, with everything that rests only on it, by the same purge and checks as a
        withdrawal, but the consent stays. A video was saved in several parts, so all of its parts go together."""
        row = self.conn.execute("SELECT source_id, kind, session_id, captured_at, text FROM sources"
                                " WHERE source_id=? AND status='active'", (source_id,)).fetchone()
        if row is None:
            raise UnknownMemory(source_id)
        ids = [source_id]
        if row["kind"] == "frame_observation" and (row["text"] or "").startswith("Video: "):
            ids = [r["source_id"] for r in self.conn.execute(
                "SELECT source_id FROM sources WHERE status='active' AND kind='frame_observation' AND session_id IS ?"
                " AND captured_at=? AND text LIKE 'Video: %' ORDER BY source_id",
                (row["session_id"], row["captured_at"]))]
        pseudo = {"grant_id": f"memory-{source_id}", "grantor": self.owner, "revoked_at": None}
        return self._end(pseudo, "deleted", run_red_team, only_sources=ids)

    def due(self) -> list[str]:
        """Grants whose consent has lapsed and whose data has not been purged yet."""
        return [r["grant_id"] for r in self.conn.execute(
            "SELECT grant_id FROM consent_grants WHERE revoked_at IS NULL AND expires_at IS NOT NULL"
            " AND expires_at <= ? ORDER BY expires_at, grant_id", (clock.now_iso(),))]

    def sweep(self, run_red_team: bool = True) -> list[dict[str, Any]]:
        """Forget everything that rested only on a grant that has expired, by the same purge as a
        withdrawal. Nothing is read from an expired grant even before this runs (the filter refuses
        it); this is what removes the data. Returns one receipt per grant ended."""
        out = []
        for gid in self.due():
            grant = self.conn.execute("SELECT * FROM consent_grants WHERE grant_id=?", (gid,)).fetchone()
            out.append(self._end(grant, "expired", run_red_team))
        return out

    def _end(self, grant: Any, reason: str, run_red_team: bool,
             only_sources: list[str] | None = None) -> dict[str, Any]:
        grant_id = grant["grant_id"]
        if grant["revoked_at"]:                      # idempotent: same receipt, nothing changes
            row = self.conn.execute("SELECT report_json FROM forgetting_receipts WHERE grant_id=?"
                                    " ORDER BY created_at LIMIT 1", (grant_id,)).fetchone()
            if row:
                return {**self._hydrate(json.loads(row["report_json"])), "already_revoked": True}
        try:
            plan = self._purge(grant, reason, only_sources)
        except Exception:
            self.conn.rollback()
            raise
        self._clean_storage()
        cache_removed = self._clear_model_cache()
        # The purge has committed. Whatever happens while verifying it, a receipt must still be written, and
        # a verification that could not run is a failure, never a pass.
        try:
            probes = run_probes(
                self.conn, terms=plan["terms"], removed_texts=plan["removed_texts"],
                removed_entity_ids=plan["removed_entities"], db_path=self.db_path,
                media_dirs=[self._data_dir()] if self._data_dir() else [], cache_dir=self.cache_dir,
                llm=self.llm, red_team_questions=self.red_team_questions,
                red_team_terms=plan["rare_terms"], run_red_team=run_red_team)
        except Exception as e:
            probes = [ProbeResult(0, "Verification could not run", FAIL, {"error": type(e).__name__})]
        receipt = self._receipt(grant, plan, cache_removed, probes, reason)
        self.conn.execute("INSERT INTO forgetting_receipts(receipt_id, grant_id, created_at,"
                          " report_json) VALUES (?,?,?,?)",
                          (receipt["receipt_id"], grant_id, receipt["created_at"],
                           json.dumps(receipt)))
        self.conn.commit()
        return self._hydrate(receipt)

    def get_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT report_json FROM forgetting_receipts WHERE receipt_id=?",
                                (receipt_id,)).fetchone()
        return self._hydrate(json.loads(row["report_json"])) if row else None

    def _hydrate(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Add the current wording of each kept fact. Receipts are stored without claim text, so a
        later withdrawal cannot leave forgotten words behind in an older receipt."""
        out = json.loads(json.dumps(receipt))
        ok = authorized_claim_ids(self.conn)
        for r in out.get("retained", []):
            row = self.conn.execute("SELECT text FROM claims WHERE claim_id=?", (r["claim_id"],)).fetchone()
            r["text"] = row["text"] if row and r["claim_id"] in ok else FORGOTTEN_SINCE
        return out

    def _scrub_receipts(self) -> None:
        """Remove claim text from every stored receipt (receipts written by an earlier version
        embedded it)."""
        for r in self.conn.execute("SELECT receipt_id, report_json FROM forgetting_receipts").fetchall():
            report = json.loads(r["report_json"])
            if any("text" in x for x in report.get("retained", [])):
                for x in report["retained"]:
                    x.pop("text", None)
                self.conn.execute("UPDATE forgetting_receipts SET report_json=? WHERE receipt_id=?",
                                  (json.dumps(report), r["receipt_id"]))

    # -- the transaction ---------------------------------------------------------------------

    def _purge(self, grant: Any, reason: str = "withdrawn",
               only_sources: list[str] | None = None) -> dict[str, Any]:
        c = self.conn
        gid = grant["grant_id"]
        now = datetime.now(timezone.utc).isoformat()
        self._scrub_receipts()

        # Every source that depends on this grant. A recorded conversation depends on the grant of
        # each participant (the gateway only records audio when ALL of them agreed), so when one
        # participant withdraws, no one's half of that recording may stay. A grant that was never
        # part of a recording cannot remove it, whatever session id it names.
        if only_sources is not None:
            # Deleting chosen memories: only those sources go, and the consent stays as it is.
            marks = ",".join("?" * len(only_sources))
            revoked = c.execute(
                "SELECT s.source_id, s.kind, s.text, s.content_hash FROM sources s WHERE s.status='active'"
                f" AND s.source_id IN ({marks})", only_sources).fetchall()
        else:
            revoked = c.execute(
                "SELECT s.source_id, s.kind, s.text, s.content_hash FROM sources s WHERE s.status='active'"
                " AND (s.grant_id=? OR EXISTS (SELECT 1 FROM source_consents k WHERE k.source_id = s.source_id"
                " AND k.grant_id=?))", (gid, gid)).fetchall()
        revoked_ids = [r["source_id"] for r in revoked]
        removed_texts = [r["text"] for r in revoked if r["text"]]

        if only_sources is None:
            c.execute("UPDATE consent_grants SET revoked_at=?, ended_reason=? WHERE grant_id=?", (now, reason, gid))
        _delete_in(c, "UPDATE sources SET status='revoked' WHERE source_id IN ({})", revoked_ids)

        # -- who dies, who survives and what each survivor lost ------------------------------
        claims = {r["claim_id"]: r for r in c.execute("SELECT * FROM claims")}
        ok = authorized_claim_ids(c)
        live_src = valid_source_ids(c)
        dead = {cid for cid in claims if cid not in ok}
        justs = self._justifications()
        lost: dict[str, list[dict[str, Any]]] = {}
        kept: dict[str, list[dict[str, Any]]] = {}
        for cid, js in justs.items():
            if cid in dead:
                continue
            for j in js:
                holds = (j["source_id"] in live_src if j["kind"] == "source"
                         else bool(j["premises"]) and all(p not in dead for p in j["premises"]))
                (kept if holds else lost).setdefault(cid, []).append(j)
        # A summary's free-text wording cannot be re-checked. It goes if it lost any support, or
        # if it was written from a claim that has since lost a source (it may repeat that
        # source's phrasing, which the claim itself is re-rendered to drop).
        lost_ids = set(lost)
        for cid in [k for k, c in claims.items() if c["predicate"] == "summary_of"
                    and k not in dead]:
            cites_lost = any(p in lost_ids for j in kept.get(cid, []) for p in j["premises"])
            if cid in lost or cites_lost:
                dead.add(cid)
                lost.pop(cid, None)
                kept.pop(cid, None)
        survivors = {cid for cid in claims if cid not in dead}
        removed_texts += [t for cid in dead for t in (claims[cid]["text"],
                                                       claims[cid]["object_value"]) if t]
        # Probe terms come from what people actually said, saw or were told: the source text,
        # claim values and fact wording. Model-written summaries and bookkeeping claims are
        # left out so their filler words ("conversation", "described") cannot cause false alarms.
        term_texts = [r["text"] for r in revoked if r["text"]]
        for cid in dead:
            cl = claims[cid]
            if cl["object_value"]:
                term_texts.append(cl["object_value"])
            if cl["predicate"] not in ("summary_of", "part_of_episode", "same_as") and cl["text"]:
                term_texts.append(cl["text"])

        # -- remove dead claims and everything hanging off them ------------------------------
        dead_list = sorted(dead)
        refs_before = self._referenced_entities()
        dead_j = [j["justification_id"] for cid in dead_list for j in justs.get(cid, [])]
        stale_j = [j["justification_id"] for cid, js in lost.items() for j in js]
        for ids in (dead_j, stale_j):
            _delete_in(c, "DELETE FROM justification_premises WHERE justification_id IN ({})", ids)
            _delete_in(c, "DELETE FROM justifications WHERE justification_id IN ({})", ids)
        _delete_in(c, "DELETE FROM justification_premises WHERE premise_claim_id IN ({})",
                   dead_list)
        # Survivors the dead ones had replaced come back (a newer sighting that is gone).
        pointing = [r["claim_id"] for r in c.execute(
            "SELECT claim_id, superseded_by FROM claims") if r["superseded_by"] in dead]
        _delete_in(c, "UPDATE claims SET superseded_by=NULL WHERE claim_id IN ({})", pointing)
        _delete_in(c, "DELETE FROM claim_index WHERE claim_id IN ({})", dead_list)
        _delete_in(c, "DELETE FROM claim_vectors WHERE claim_id IN ({})", dead_list)
        _delete_in(c, "DELETE FROM claims WHERE claim_id IN ({})", dead_list)
        _delete_in(c, "DELETE FROM todo_state WHERE claim_id IN ({})", dead_list)

        refs_after = self._referenced_entities()
        orphan_ids = sorted((refs_before - refs_after) - {self.owner})
        removed_entity_names = [r["name"] for r in c.execute(
            "SELECT name FROM entities WHERE entity_id IN (%s)" % ",".join("?" * len(orphan_ids)),
            orphan_ids)] if orphan_ids else []
        removed_texts += removed_entity_names
        term_texts += removed_entity_names
        _delete_in(c, "DELETE FROM entities WHERE entity_id IN ({})", orphan_ids)

        # -- blank the revoked sources, block re-ingest -------------------------------------
        _delete_in(c, "UPDATE sources SET text=NULL, lat=NULL, lon=NULL, session_id=NULL"
                      " WHERE source_id IN ({})", revoked_ids)
        if only_sources is None:              # a withdrawal blocks the same words coming back; a deletion does not
            for r in revoked:
                c.execute("INSERT OR IGNORE INTO blocked_hashes(content_hash, reason) VALUES (?,?)",
                          (r["content_hash"], f"revoked:{gid}"))

        # -- metadata only a removed source supplied: episode time and place, a fact's timestamp --
        moved = self._recompute_episodes()
        self._retime([cid for cid in lost if cid in survivors], lost, kept)
        # -- survivors that lost a source: no wording from the removed one -------------------
        reword = [cid for cid in lost if cid in survivors]
        if moved:                                  # claims that quote a changed episode's label
            marks = ",".join("?" * len(moved))
            reword += [r["claim_id"] for r in c.execute(
                f"SELECT claim_id FROM claims WHERE predicate='part_of_episode' AND object_id IN ({marks})", moved)]
        rewritten = self._rerender(sorted(set(reword)))
        self._recompute_states(claims, dead, pointing)

        # -- terms, then caches and chat -----------------------------------------------------
        known = self._remaining_text() + self._structural_text()
        terms = distinctive_terms(term_texts, known)
        rare = rare_terms(terms, known)
        cache_rows = self._clear_answer_cache()
        chat_rows = self._redact_chat(dead, terms)

        retained = []
        for cid in sorted(lost):
            if cid not in survivors:
                continue
            row = c.execute("SELECT predicate FROM claims WHERE claim_id=?", (cid,)).fetchone()
            retained.append({
                "claim_id": cid, "predicate": row["predicate"],
                "lost_support": sorted({self._describe(j, claims) for j in lost[cid]}),
                "still_supported_by": sorted({self._describe(j, claims) for j in kept[cid]})})
        c.commit()
        return {
            "now": now, "revoked_sources": revoked_ids, "dead": dead_list,
            "survivors": len(survivors), "unaffected": len(survivors) - len(lost),
            "retained": retained, "rewritten": rewritten, "terms": terms,
            "rare_terms": rare, "removed_texts": removed_texts, "removed_entities": orphan_ids,
            "answer_cache_rows": cache_rows, "chat_rows": chat_rows,
            "kinds_removed": self._kinds(claims, dead_list)}

    # -- helpers -----------------------------------------------------------------------------

    def _justifications(self) -> dict[str, list[dict[str, Any]]]:
        by_j: dict[str, dict[str, Any]] = {}
        out: dict[str, list[dict[str, Any]]] = {}
        for j in self.conn.execute("SELECT justification_id, claim_id, kind, source_id, rule"
                                   " FROM justifications"):
            d = {"justification_id": j["justification_id"], "kind": j["kind"],
                 "source_id": j["source_id"], "rule": j["rule"], "premises": []}
            by_j[j["justification_id"]] = d
            out.setdefault(j["claim_id"], []).append(d)
        for p in self.conn.execute("SELECT justification_id, premise_claim_id FROM"
                                   " justification_premises"):
            if p["justification_id"] in by_j:
                by_j[p["justification_id"]]["premises"].append(p["premise_claim_id"])
        return out

    def _referenced_entities(self) -> set[str]:
        ids: set[str] = set()
        for r in self.conn.execute("SELECT subject_id, object_id, episode_id FROM claims"):
            ids.update(x for x in (r["subject_id"], r["object_id"], r["episode_id"]) if x)
        return ids

    def _describe(self, j: dict[str, Any], claims: dict[str, sqlite3.Row]) -> str:
        if j["kind"] == "source":
            s = self.conn.execute("SELECT kind, captured_at FROM sources WHERE source_id=?",
                                  (j["source_id"],)).fetchone()
            return f"{s['kind']} at {s['captured_at'][11:16]}" if s else "a source"
        return f"derivation ({j['rule']})"

    def _name(self, entity_id: str | None) -> str:
        r = self.conn.execute("SELECT name FROM entities WHERE entity_id=?",
                              (entity_id,)).fetchone() if entity_id else None
        return r["name"] if r else ""

    def _rerender(self, claim_ids: list[str]) -> list[str]:
        """Rebuild wording from structure alone. Facts are identical across the sources that
        stated them (the value is part of a claim's identity); only the free-text rendering
        could carry words that came from just one source."""
        done = []
        for cid in claim_ids:
            r = self.conn.execute("SELECT * FROM claims WHERE claim_id=?", (cid,)).fetchone()
            obj = self._name(r["object_id"]) if r["object_id"] else (r["object_value"] or "")
            text = f"{self._name(r['subject_id'])} {r['predicate'].replace('_', ' ')} {obj}".strip()
            if text == r["text"]:
                continue
            self.conn.execute("UPDATE claims SET text=? WHERE claim_id=?", (text, cid))
            self.conn.execute("DELETE FROM claim_index WHERE claim_id=?", (cid,))
            self.conn.execute("INSERT INTO claim_index(claim_id, text) VALUES (?,?)", (cid, text))
            self.conn.execute("UPDATE claim_vectors SET vec=? WHERE claim_id=?",
                              (to_blob(counts(text)), cid))
            done.append(cid)
        return done

    def _recompute_episodes(self) -> list[str]:
        """Rebuild each episode's time bounds and place from the observations that still stand,
        and give it an id that does not carry the time of one that was forgotten."""
        valid = valid_source_ids(self.conn)
        changed: list[str] = []
        for ep in self.conn.execute("SELECT entity_id, attrs FROM entities WHERE type='episode'").fetchall():
            a = json.loads(ep["attrs"])
            contrib = a.get("contrib")
            if contrib is None:                # written before provenance was kept: trace it now
                contrib = reconstruct_contrib(self.conn, ep["entity_id"], a)
            keep = [x for x in contrib if x["source_id"] is None or x["source_id"] in valid]
            if not keep:
                keep = [x for x in reconstruct_contrib(self.conn, ep["entity_id"], a, fallback=False)
                        if x["source_id"] is None or x["source_id"] in valid]
                if not keep:                   # nothing stands behind it any more
                    if not self.conn.execute(
                            "SELECT 1 FROM claims WHERE episode_id=?1 OR subject_id=?1 OR object_id=?1",
                            (ep["entity_id"],)).fetchone():
                        self.conn.execute("DELETE FROM entities WHERE entity_id=?", (ep["entity_id"],))
                        changed.append(ep["entity_id"])
                    continue
            extent = episode_extent(keep)
            if len(keep) == len(contrib) and "contrib" in a and all(a.get(k) == v for k, v in extent.items()):
                continue                       # already exactly what the remaining sources give
            new = {**episode_extent(keep), "contrib": [x for x in keep if x["source_id"] is not None]}
            start = datetime.fromisoformat(new["start"])
            end = datetime.fromisoformat(new["end"])
            eid = ep["entity_id"]
            token = re.match(r"episode:(\d{8}-\d{4})", eid)
            if token and token.group(1) != f"{start:%Y%m%d-%H%M}":
                eid = self._rename_episode(eid, start)
            self.conn.execute("UPDATE entities SET name=?, attrs=? WHERE entity_id=?",
                              (episode_label(start, end), json.dumps(new), eid))
            changed.append(eid)
        return changed

    def _rename_episode(self, old: str, start: datetime) -> str:
        """Move an episode to an id built from its remaining start time, taking every reference
        with it. (Claim ids stay as they are: they are identifiers, not content.)"""
        base = episode_id_for(start)
        new, n = base, 2
        while self.conn.execute("SELECT 1 FROM entities WHERE entity_id=?", (new,)).fetchone():
            new, n = f"{base}-{n}", n + 1
        row = self.conn.execute("SELECT type, name, attrs FROM entities WHERE entity_id=?", (old,)).fetchone()
        self.conn.execute("INSERT INTO entities(entity_id, type, name, attrs) VALUES (?,?,?,?)",
                          (new, row["type"], row["name"], row["attrs"]))
        for col in ("subject_id", "object_id", "episode_id"):
            self.conn.execute(f"UPDATE claims SET {col}=? WHERE {col}=?", (new, old))
        self.conn.execute("DELETE FROM entities WHERE entity_id=?", (old,))
        return new

    def _retime(self, claim_ids: list[str], lost: dict[str, list[dict[str, Any]]],
                kept: dict[str, list[dict[str, Any]]]) -> None:
        """A fact two sources stated carries the time of whichever wrote it first. If that source
        was removed, move the time to the earliest one that remains."""
        for cid in claim_ids:
            when = {r["source_id"]: r["captured_at"] for r in self.conn.execute(
                "SELECT source_id, captured_at FROM sources")}
            gone = {when[j["source_id"]] for j in lost.get(cid, []) if j["kind"] == "source" and j["source_id"] in when}
            left = sorted(when[j["source_id"]] for j in kept.get(cid, []) if j["kind"] == "source" and j["source_id"] in when)
            row = self.conn.execute("SELECT event_time, valid_from FROM claims WHERE claim_id=?", (cid,)).fetchone()
            if not left or row is None or row["event_time"] not in gone:
                continue
            self.conn.execute("UPDATE claims SET event_time=?, valid_from=CASE WHEN valid_from=? THEN ? ELSE valid_from END"
                              " WHERE claim_id=?", (left[0], row["event_time"], left[0], cid))

    def _recompute_states(self, claims: dict[str, sqlite3.Row], dead: set[str],
                          pointing: list[str]) -> None:
        """Disputes and 'latest sighting' depend on which claims exist; redo them."""
        subjects = {claims[c]["subject_id"] for c in dead if claims[c]["predicate"] == "located_at"}
        subjects |= {claims[c]["subject_id"] for c in pointing if c in claims
                     and claims[c]["predicate"] == "located_at"}
        if subjects:
            for sid in subjects:
                self.conn.execute("UPDATE claims SET status='active' WHERE subject_id=? AND"
                                  " predicate='located_at' AND status='disputed'", (sid,))
            contradiction_pass(self.conn, subjects)
            Deriver(self.conn, None, self.owner).supersede_located_at(subjects)  # type: ignore[arg-type]
        for cid in pointing:                      # e.g. an older summary whose replacement died
            r = self.conn.execute("SELECT predicate, status FROM claims WHERE claim_id=?",
                                  (cid,)).fetchone()
            if r and r["predicate"] != "located_at" and r["status"] == "superseded":
                self.conn.execute("UPDATE claims SET status='active' WHERE claim_id=?", (cid,))

    def _remaining_text(self) -> list[str]:
        out = [f"{r['text'] or ''} {r['object_value'] or ''}" for r in
               self.conn.execute("SELECT text, object_value FROM claims")]
        out += [r["text"] for r in self.conn.execute(
            "SELECT text FROM sources WHERE status='active' AND text IS NOT NULL")]
        out += [r["name"] for r in self.conn.execute("SELECT name FROM entities")]
        return out

    def _structural_text(self) -> list[str]:
        """The app's own vocabulary: predicate names, entity types, source kinds, JSON field
        names. Fixed by the code, never by user content, so it cannot excuse a leak. A word
        that is only structure ("place", "kind") is not evidence about what was forgotten."""
        from ..compiler.extract import PREDICATES
        from .export import export_memories
        words = [p.replace("_", " ") for p in PREDICATES]
        from ..db import SCHEMA_PATH
        words.append(SCHEMA_PATH.read_text())    # the database file contains its own schema
        words += ["person place object org episode item", "active disputed superseded revoked",
                  "direct observation user confirmation inference",
                  "transcript segment frame observation location fix calendar event",
                  "spatial referent resolution episode summary personal recall",
                  "capture session source derivation"]

        def keys(node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    words.append(str(k).replace("_", " "))
                    keys(v)
            elif isinstance(node, list):
                for v in node:
                    keys(v)

        keys(export_memories(self.conn))      # field names only; values are never used
        return words

    def _clear_answer_cache(self) -> int:
        """Cached answers are only copies of what could be recomputed, so all of them go."""
        return self.conn.execute("DELETE FROM answer_cache").rowcount

    def _redact_chat(self, dead: set[str], terms: list[str]) -> int:
        from .probes import contains
        n = 0
        for r in self.conn.execute("SELECT msg_id, text, claim_ids FROM chat_messages WHERE"
                                   " redacted=0").fetchall():
            if dead & set(json.loads(r["claim_ids"])) or contains(r["text"], terms):
                self.conn.execute("UPDATE chat_messages SET text=?, claim_ids='[]', redacted=1"
                                  " WHERE msg_id=?", (REDACTED_CHAT, r["msg_id"]))
                n += 1
        return n

    def _kinds(self, claims: dict[str, sqlite3.Row], dead: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for cid in dead:
            p = claims[cid]["predicate"]
            out[p] = out.get(p, 0) + 1
        return dict(sorted(out.items()))

    # -- storage clean-up --------------------------------------------------------------------

    def _data_dir(self) -> str | None:
        if self.db_path and self.db_path != ":memory:":
            return str(Path(self.db_path).resolve().parent)
        return None

    def _clean_storage(self) -> None:
        """Make the database file itself forget: rebuild the text index, flush the log, VACUUM."""
        for stmt in ("INSERT INTO claim_index(claim_index) VALUES('rebuild')",
                     "INSERT INTO claim_index(claim_index) VALUES('optimize')"):
            self.conn.execute(stmt)
        self.conn.commit()
        if self.db_path and self.db_path != ":memory:":
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        self.conn.execute("VACUUM")
        if self.db_path and self.db_path != ":memory:":
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()

    def _clear_model_cache(self) -> int:
        """Delete every recorded model response in the app's own runtime cache. A response's
        dependence on what was forgotten is not recorded, and searching for phrases misses short
        or paraphrased secrets, so nothing is kept. The committed demo fixtures are read-only seed
        data in another directory and are never touched."""
        if not self.cache_dir or not Path(self.cache_dir).is_dir():
            return 0
        n = 0
        for p in Path(self.cache_dir).glob("*.json"):
            p.unlink()
            n += 1
        return n

    # -- receipt -----------------------------------------------------------------------------

    def _receipt(self, grant: sqlite3.Row, plan: dict[str, Any], cache_removed: int,
                 probes: list[Any], reason: str = "withdrawn") -> dict[str, Any]:
        results = [p.as_dict() for p in probes]
        passed = sum(p["status"] == PASS for p in results)
        failed = sum(p["status"] == FAIL for p in results)
        skipped = sum(p["status"] == SKIPPED for p in results)
        return {
            "receipt_id": "rcpt-" + uuid.uuid4().hex[:12],
            "grant_id": grant["grant_id"], "grantor": grant["grantor"],
            "reason": reason,                       # "withdrawn" by the person, or "expired"
            "created_at": plan["now"], "already_revoked": False,
            "removed": {
                "sources_blanked": len(plan["revoked_sources"]),
                "claims_deleted": len(plan["dead"]),
                "claims_deleted_by_kind": plan["kinds_removed"],
                "entities_deleted": len(plan["removed_entities"]),
                "answer_cache_rows": plan["answer_cache_rows"],
                "chat_messages_redacted": plan["chat_rows"],
                "model_cache_files": cache_removed},
            "kept": {
                "claims_surviving": plan["survivors"],
                "claims_that_lost_a_source_but_survive": len(plan["retained"]),
                "claims_unaffected": plan["unaffected"],
                "survivors_reworded": len(plan["rewritten"])},
            "retained": plan["retained"],
            "digests": {"removed_claim_ids_sha256": digest(plan["dead"]),
                        "probe_terms": [term_digest(t) for t in plan["terms"]]},
            "probes": results,
            "summary": {"probes_passed": passed, "probes_failed": failed,
                        "probes_skipped": skipped, "probes_total": len(results),
                        "all_passed": passed == len(results)},
            "notes": [
                "Removed claims are deleted outright, not hidden, and the database file was "
                "rebuilt (index rebuild, log checkpoint, VACUUM).",
                "Cached answers and recorded model responses are derived copies, so they were "
                "cleared whole instead of searched for what was forgotten.",
                "Anything already sent to Meta's hosted models is covered by Meta's terms, not "
                "by this receipt.",
                "Committed demo fixtures (recorded model responses and the staged script) are "
                "read-only seed data outside the app's own stores and are not modified."]}
