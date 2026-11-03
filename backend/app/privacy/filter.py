"""Deterministic privacy filter: which claims may be read right now.

A claim is authorized when at least one of its justifications holds: a source justification
holds when the source is active and its consent grant is unrevoked and covers the purpose; a
derivation holds when ALL of its premises are authorized. This is a least fixpoint built
bottom-up from live sources, so cyclic derivations cannot keep each other alive.

Every recall tool reads through this module. It is defence in depth: the purge in Phase 3
removes revoked material from the stores, and this filter still refuses anything unsupported.
"""
import json
import sqlite3

from . import clock

PURPOSE = "personal_recall"
READABLE = ("active", "disputed")
HISTORY = ("active", "disputed", "superseded")


def valid_source_ids(conn: sqlite3.Connection, purpose: str = PURPOSE) -> set[str]:
    """Sources that may be used: active, and every grant they depend on is unrevoked and covers
    the purpose. A grant past its expiry no longer counts, even before the purge has run.
    (Rows written before `source_consents` existed depend on their own grant only.)"""
    good = {r["grant_id"] for r in conn.execute(
        "SELECT grant_id, purposes FROM consent_grants WHERE revoked_at IS NULL"
        " AND (expires_at IS NULL OR expires_at > ?)", (clock.now_iso(),))
            if purpose in json.loads(r["purposes"])}
    needs: dict[str, set[str]] = {}
    for r in conn.execute("SELECT source_id, grant_id FROM source_consents"):
        needs.setdefault(r["source_id"], set()).add(r["grant_id"])
    out = set()
    for r in conn.execute("SELECT source_id, grant_id FROM sources WHERE status='active'"):
        required = needs.get(r["source_id"]) or ({r["grant_id"]} if r["grant_id"] else set())
        if required and required <= good:
            out.add(r["source_id"])
    return out


def authorized_claim_ids(conn: sqlite3.Connection, purpose: str = PURPOSE) -> set[str]:
    live = valid_source_ids(conn, purpose)
    supported: set[str] = set()
    derivations: dict[str, list[str]] = {}          # justification_id -> premises
    owner: dict[str, str] = {}                      # justification_id -> claim_id
    for j in conn.execute("SELECT justification_id, claim_id, kind, source_id FROM justifications"):
        if j["kind"] == "source":
            if j["source_id"] in live:
                supported.add(j["claim_id"])
        else:
            derivations[j["justification_id"]] = []
            owner[j["justification_id"]] = j["claim_id"]
    for p in conn.execute("SELECT justification_id, premise_claim_id FROM justification_premises"):
        if p["justification_id"] in derivations:
            derivations[p["justification_id"]].append(p["premise_claim_id"])
    changed = True
    while changed:
        changed = False
        for jid, premises in derivations.items():
            cid = owner[jid]
            if cid not in supported and premises and all(p in supported for p in premises):
                supported.add(cid)
                changed = True
    return supported


def visible_claim_ids(conn: sqlite3.Connection, include_history: bool = False) -> set[str]:
    statuses = HISTORY if include_history else READABLE
    marks = ",".join("?" * len(statuses))
    ok = {r["claim_id"] for r in conn.execute(
        f"SELECT claim_id FROM claims WHERE status IN ({marks})", statuses)}
    return ok & authorized_claim_ids(conn)
