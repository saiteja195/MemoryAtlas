"""Consent grants. Revocation (Phase 3) builds on these; the gateway only needs lookups."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone

from . import clock

DEFAULT_PURPOSES = ["personal_recall"]


def _hash(secret: str, token: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_grant(conn: sqlite3.Connection, secret: str, grantor: str, session_id: str,
                 purposes: list[str] | None = None, scope: str = "capture_session",
                 grant_id: str | None = None, expires_at: datetime | None = None) -> tuple[str, str]:
    """Create a grant and return (grant_id, revocation_token). Only the HMAC is stored.
    `expires_at` (timezone-aware) is when the consent lapses; None means until it is withdrawn."""
    if expires_at is not None and expires_at <= clock.now():
        raise ValueError("expires_at must be in the future")
    grant_id = grant_id or f"grant-{uuid.uuid4().hex[:10]}"
    token = secrets.token_urlsafe(16)
    conn.execute(
        "INSERT INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes, token_hash,"
        " granted_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
        (grant_id, grantor, scope, session_id, json.dumps(purposes or DEFAULT_PURPOSES),
         _hash(secret, token), datetime.now(timezone.utc).isoformat(),
         clock.iso(expires_at) if expires_at else None))
    conn.commit()
    return grant_id, token


def verify_token(secret: str, token: str, token_hash: str) -> bool:
    return hmac.compare_digest(_hash(secret, token), token_hash)


def active_grant(conn: sqlite3.Connection, grantor: str, session_id: str,
                 purpose: str = "personal_recall") -> str | None:
    """The grant_id of an active grant by `grantor` that covers `session_id`, else None."""
    rows = conn.execute(
        "SELECT grant_id, purposes FROM consent_grants WHERE grantor=? AND scope='capture_session'"
        " AND scope_ref=? AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > ?)"
        " ORDER BY granted_at", (grantor, session_id, clock.now_iso())
    ).fetchall()
    for row in rows:
        if purpose in json.loads(row["purposes"]):
            return row["grant_id"]
    return None
