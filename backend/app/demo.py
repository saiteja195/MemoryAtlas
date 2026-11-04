"""Deterministic demo control: reset, advance through the scripted day, upload the live frame."""
import secrets
import sqlite3
from datetime import timedelta
from typing import Any

from . import db
from .capture.adapters import MockDayAdapter
from .engine import Ingested, MemoryEngine
from .privacy import clock
from .privacy.consent import _hash, create_grant


class DemoRunner:
    def __init__(self, engine: MemoryEngine, adapter: MockDayAdapter, secret: str, seed: bool = True):
        self.engine, self.adapter, self.secret = engine, adapter, secret
        self.conn: sqlite3.Connection = engine.conn
        self.cursor = 0
        self.played: set[str] = set()      # ids of events already ingested (scheduled or live)
        self.tokens: dict[str, str] = {}   # grantor:session -> revocation token (demo only)
        if seed and not self.conn.execute("SELECT 1 FROM consent_grants").fetchone():
            self.reset()   # seed a fresh database; never wipe one that already has data

    def reset(self) -> None:
        db.reset(self.conn)
        self.engine.reset()
        self.cursor = 0
        self.played = set()
        self.tokens = {}
        for g in self.adapter.grants():
            hours = g.get("valid_for_hours")
            expires = clock.now() + timedelta(hours=hours) if hours else None
            _, token = create_grant(self.conn, self.secret, g["grantor"], g["session"], expires_at=expires)
            self.tokens[f"{g['grantor']}:{g['session']}"] = token
        self.engine.compiler.resolver.ensure_owner(self.adapter.names.get(self.adapter.owner, "Me"))
        self.conn.commit()

    def rekey(self) -> None:
        """DEMO ONLY. A profile restored from a snapshot holds only token hashes, so give each active grant a
        fresh token. A demo token is already shown to whoever runs the demo (`/demo/grants`)."""
        for g in self.conn.execute("SELECT grant_id, grantor, scope_ref FROM consent_grants"
                                   " WHERE revoked_at IS NULL").fetchall():
            token = secrets.token_urlsafe(16)
            self.conn.execute("UPDATE consent_grants SET token_hash=? WHERE grant_id=?",
                              (_hash(self.secret, token), g["grant_id"]))
            self.tokens[f"{g['grantor']}:{g['scope_ref']}"] = token
        self.conn.commit()

    def mark_all_played(self) -> None:
        """The database already holds the day (restored from a snapshot): do not play it a second time."""
        self.cursor = len(self._scheduled())
        self.played = {e["id"] for e in self.adapter.events()}

    def _scheduled(self) -> list[dict[str, Any]]:
        return [e for e in self.adapter.events() if not e.get("live_upload")]

    def _ensure_seeded(self) -> None:
        """A profile that has not played the day yet has no grants, so the day would be rejected. An empty
        database is seeded here, as a fresh single-user database is at start; one with memories is left alone."""
        if not self.conn.execute("SELECT 1 FROM consent_grants").fetchone() \
                and not self.conn.execute("SELECT 1 FROM sources").fetchone():
            self.reset()

    def play(self, event_id: str) -> list[Ingested]:
        self._ensure_seeded()
        ev = next(e for e in self.adapter.events() if e["id"] == event_id)
        self.played.add(event_id)
        return self.engine.ingest(self.adapter.capture(ev))

    def advance(self, steps: int = 1) -> list[dict[str, Any]]:
        self._ensure_seeded()
        events, played = self._scheduled(), []
        for _ in range(steps):
            if self.cursor >= len(events):
                break
            ev = events[self.cursor]
            self.cursor += 1
            results = self.play(ev["id"])
            played.append({"id": ev["id"], "kind": ev["kind"], "at": ev["at"],
                           "ingested": sum(r.ingest.status == "ingested" for r in results),
                           "rejected": [r.ingest.reason for r in results
                                        if r.ingest.status != "ingested"] +
                                       [r.compiled.rejected for r in results
                                        if r.compiled and r.compiled.rejected]})
        return played

    @staticmethod
    def _label(ev: dict[str, Any]) -> str:
        kind = ev["kind"]
        if kind == "calendar":
            return ev.get("title", "Calendar event")
        if kind == "audio":
            return f"Conversation ({len(ev.get('turns') or [])} lines)"
        if kind == "frame":
            return (ev.get("perception") or {}).get("caption", "Photo")
        return ev.get("text") or kind.title()

    def status(self) -> dict[str, Any]:
        events = self._scheduled()
        return {"total": len(events), "cursor": self.cursor,
                "next": events[self.cursor]["id"] if self.cursor < len(events) else None,
                "live_uploads": [e["id"] for e in self.adapter.events() if e.get("live_upload")],
                # Every event in the staged day, so a UI can show what has happened and what
                # is still to come. `at` is HH:MM on the script's day.
                "events": [{"id": e["id"], "kind": e["kind"], "at": e["at"],
                            "label": self._label(e), "live_upload": bool(e.get("live_upload")),
                            "played": e["id"] in self.played}
                           for e in self.adapter.events()]}
