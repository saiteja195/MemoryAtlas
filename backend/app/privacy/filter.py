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

PURPOSE = "personal_recall"
READABLE = ("active", "disputed")
HISTORY = ("active", "disputed", "superseded")


def valid_source_ids(conn: sqlite3.Connection, purpose: str = PURPOSE) -> set[str]:
    out = set()
    for r in conn.execute(
            "SELECT s.source_id, g.purposes FROM sources s JOIN consent_grants g"
            " ON g.grant_id = s.grant_id WHERE s.status='active' AND g.revoked_at IS NULL"):
        if purpose in json.loads(r["purposes"]):
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
