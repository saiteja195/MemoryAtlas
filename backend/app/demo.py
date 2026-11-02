"""Deterministic demo control: reset, advance through the scripted day, upload the live frame."""
import sqlite3
from typing import Any

from . import db
from .capture.adapters import MockDayAdapter
from .engine import Ingested, MemoryEngine
from .privacy.consent import create_grant


class DemoRunner:
    def __init__(self, engine: MemoryEngine, adapter: MockDayAdapter, secret: str):
        self.engine, self.adapter, self.secret = engine, adapter, secret
        self.conn: sqlite3.Connection = engine.conn
        self.cursor = 0
        self.tokens: dict[str, str] = {}   # grantor:session -> revocation token (demo only)
        if not self.conn.execute("SELECT 1 FROM consent_grants").fetchone():
            self.reset()   # seed a fresh database; never wipe one that already has data

    def reset(self) -> None:
        db.reset(self.conn)
        self.cursor = 0
        self.tokens = {}
        for g in self.adapter.grants():
            _, token = create_grant(self.conn, self.secret, g["grantor"], g["session"])
            self.tokens[f"{g['grantor']}:{g['session']}"] = token
        self.engine.compiler.resolver.ensure_owner(self.adapter.names.get(self.adapter.owner, "Me"))
        self.conn.commit()

    def _scheduled(self) -> list[dict[str, Any]]:
        return [e for e in self.adapter.events() if not e.get("live_upload")]

    def play(self, event_id: str) -> list[Ingested]:
        ev = next(e for e in self.adapter.events() if e["id"] == event_id)
        return self.engine.ingest(self.adapter.capture(ev))

    def advance(self, steps: int = 1) -> list[dict[str, Any]]:
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

    def status(self) -> dict[str, Any]:
        events = self._scheduled()
        return {"total": len(events), "cursor": self.cursor,
                "next": events[self.cursor]["id"] if self.cursor < len(events) else None,
                "live_uploads": [e["id"] for e in self.adapter.events() if e.get("live_upload")]}
