"""'Export my memories': everything the app would hand back, as JSON. The forgetting probes
search this output for removed text, so it must be built from the live database each time."""
import sqlite3
from typing import Any

from ..graph import build_graph


def export_memories(conn: sqlite3.Connection) -> dict[str, Any]:
    sources = [dict(r) for r in conn.execute(
        "SELECT source_id, kind, captured_at, text FROM sources WHERE status='active'"
        " ORDER BY captured_at, source_id")]
    grants = [dict(r) for r in conn.execute(
        "SELECT grant_id, grantor, scope_ref, granted_at, expires_at, revoked_at FROM consent_grants"
        " ORDER BY granted_at, grant_id")]
    return {"graph": build_graph(conn, include_history=True), "sources": sources,
            "grants": grants}
