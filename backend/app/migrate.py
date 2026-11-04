"""Upgrade a database written by an earlier version. Runs on every connect and is idempotent.

Two things were added after the first release and an old database lacks both:
  * `source_consents`: every grant a source depends on (a recorded conversation depends on all
    of its participants). Without rows, a source would depend on its own grant only, and the
    other people in a recording would not be covered when someone withdraws.
  * `attrs.contrib` on episodes: which observation supplied which time and place, so an episode
    can forget what a withdrawn source told it.
"""
import json
import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    add_grant_expiry_columns(conn)
    add_chat_columns(conn)
    backfill_source_consents(conn)
    backfill_episode_provenance(conn)
    conn.commit()


def add_grant_expiry_columns(conn: sqlite3.Connection) -> None:
    """Grants written before expiry existed get the columns; they never expire. A grant that was already
    withdrawn is recorded as withdrawn."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(consent_grants)")}
    if "expires_at" not in have:
        conn.execute("ALTER TABLE consent_grants ADD COLUMN expires_at TEXT")
    if "ended_reason" not in have:
        conn.execute("ALTER TABLE consent_grants ADD COLUMN ended_reason TEXT")
    conn.execute("UPDATE consent_grants SET ended_reason='withdrawn' WHERE revoked_at IS NOT NULL"
                 " AND ended_reason IS NULL")


def add_chat_columns(conn: sqlite3.Connection) -> None:
    """Messages written before the conversation kept its day, status and cited tools get the columns."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)")}
    if "as_of" not in have:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN as_of TEXT")
    if "status" not in have:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN status TEXT")
    if "cited_tools" not in have:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN cited_tools TEXT NOT NULL DEFAULT '[]'")


def backfill_source_consents(conn: sqlite3.Connection) -> int:
    """Give every source without consent rows the grants it must have rested on.

    A note or photo rested on its own grant. A recorded line rested on the grant of every
    participant, and who the silent participants were was never stored, so the line is tied to
    every standing grant for its session (plus its own). That can tie a recording to someone who
    was not in it, in which case their withdrawal removes it too: for forgetting, the wrong
    guess errs towards removing, never towards keeping."""
    done = 0
    for s in conn.execute(
            "SELECT source_id, kind, session_id, grant_id FROM sources s WHERE grant_id IS NOT NULL"
            " AND NOT EXISTS (SELECT 1 FROM source_consents c WHERE c.source_id = s.source_id)").fetchall():
        grants = {s["grant_id"]}
        if s["kind"] == "transcript_segment":
            grants |= {r[0] for r in conn.execute(
                "SELECT grant_id FROM consent_grants WHERE scope='capture_session' AND scope_ref=?"
                " AND revoked_at IS NULL", (s["session_id"],))}
        conn.executemany("INSERT OR IGNORE INTO source_consents(source_id, grant_id) VALUES (?,?)",
                         [(s["source_id"], g) for g in sorted(grants)])
        done += 1
    return done


def backfill_episode_provenance(conn: sqlite3.Connection) -> int:
    """Rebuild `contrib` for episodes that have none, from the sources behind their claims.
    Their stored bounds are left as they are; the next forgetting (or the graph probe) compares
    them with what the remaining sources give and corrects or flags any difference."""
    from .compiler.episodes import reconstruct_contrib
    done = 0
    for e in conn.execute("SELECT entity_id, attrs FROM entities WHERE type='episode'").fetchall():
        a = json.loads(e["attrs"] or "{}")
        if a.get("contrib") is not None or "start" not in a:
            continue
        a["contrib"] = reconstruct_contrib(conn, e["entity_id"], a)
        conn.execute("UPDATE entities SET attrs=? WHERE entity_id=?", (json.dumps(a), e["entity_id"]))
        done += 1
    return done
