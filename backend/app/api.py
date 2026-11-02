import base64
import os
from dataclasses import replace
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import db
from .capture.adapters import MockDayAdapter
from .capture.audit import media_bytes_on_disk
from .capture.models import KINDS, RawCapture
from .config import Settings, runtime_cache_path
from .demo import DemoRunner
from .demo_acts import load_acts
from .engine import MemoryEngine
from .graph import build_graph
from .llm.base import LLMClient, LLMUnavailable
from .llm.factory import build_client
from .privacy.consent import create_grant
from .privacy.export import export_memories
from .privacy.revocation import BadToken, RevocationEngine, UnknownGrant
from .recall.service import RecallService


class CaptureBody(BaseModel):
    session_id: str
    captured_at: str
    lat: float | None = None
    lon: float | None = None
    text: str | None = None
    ends_at: str | None = None
    place_name: str | None = None
    attendees: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    speaker_map: dict[str, str] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)
    image_b64: str | None = None
    audio_b64: str | None = None
    perception: dict[str, Any] | None = None
    turns: list[dict[str, Any]] | None = None


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class RevokeBody(BaseModel):
    token: str = Field(min_length=1)


class GrantBody(BaseModel):
    grantor: str
    session_id: str
    purposes: list[str] | None = None


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or Settings()
    # One runtime model-response cache, shared by the client and the forgetting purge.
    settings = replace(settings, runtime_cache_dir=runtime_cache_path(settings))
    conn = db.connect(settings.db_path)
    llm = llm or build_client(settings)
    adapter = MockDayAdapter(settings.demo_script)
    engine = MemoryEngine(conn, llm, adapter.owner, adapter.names)
    demo = DemoRunner(engine, adapter, settings.revocation_secret)
    recall = RecallService(conn, llm)
    try:
        red_team = [q["question"] for q in load_acts().get("red_team", [])]
    except OSError:
        red_team = []
    revoker = RevocationEngine(
        conn, settings.revocation_secret, llm, adapter.owner,
        db_path=None if settings.db_path == ":memory:" else os.path.abspath(settings.db_path),
        cache_dir=settings.runtime_cache_dir, red_team_questions=red_team)
    data_dir = None if settings.db_path == ":memory:" else os.path.dirname(os.path.abspath(
        settings.db_path))

    app = FastAPI(title="MemoryAtlas")
    app.state.conn, app.state.engine, app.state.demo = conn, engine, demo

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "llm_mode": llm.mode}

    @app.get("/graph")
    def graph(at: str | None = None, include: str | None = None) -> dict:
        return build_graph(conn, at, include_history=include == "history")

    @app.get("/privacy/media")
    def media() -> dict:
        retained = conn.execute("SELECT COALESCE(SUM(media_bytes_retained),0) FROM sources"
                                ).fetchone()[0]
        on_disk = media_bytes_on_disk(*( [data_dir] if data_dir else []), recursive=False)
        on_disk += media_bytes_on_disk(settings.cache_dir, settings.runtime_cache_dir)
        return {"raw_media_bytes_retained": retained, "media_bytes_on_disk": on_disk}

    @app.post("/consent/grants")
    def grant(body: GrantBody) -> dict:
        gid, token = create_grant(conn, settings.revocation_secret, body.grantor,
                                  body.session_id, body.purposes)
        return {"grant_id": gid, "revocation_token": token}

    @app.get("/consent/grants")
    def grants() -> list[dict]:
        # receipt_id lets another browser tab (the person withdrawing consent) tell this one
        # which receipt to show, without the two pages talking to each other directly.
        return [dict(r) for r in conn.execute(
            "SELECT g.grant_id, g.grantor, g.scope, g.scope_ref, g.granted_at, g.revoked_at,"
            " (SELECT r.receipt_id FROM forgetting_receipts r WHERE r.grant_id = g.grant_id"
            "  ORDER BY r.created_at LIMIT 1) AS receipt_id"
            " FROM consent_grants g ORDER BY g.granted_at, g.grant_id")]

    @app.post("/consent/grants/{grant_id}/revoke")
    def revoke(grant_id: str, body: RevokeBody, red_team: bool = True) -> dict:
        """Withdraw consent: forget everything only this grant supported. The token is the
        proof that the person who consented is the one asking."""
        try:
            return revoker.revoke(grant_id, body.token, run_red_team=red_team)
        except UnknownGrant:
            raise HTTPException(404, "unknown grant") from None
        except BadToken:
            raise HTTPException(403, "wrong revocation token") from None

    @app.get("/receipts/{receipt_id}")
    def receipt(receipt_id: str) -> dict:
        found = revoker.get_receipt(receipt_id)
        if found is None:
            raise HTTPException(404, "unknown receipt")
        return found

    @app.get("/export")
    def export() -> dict:
        return export_memories(conn)

    @app.post("/capture/{kind}")
    def capture(kind: str, body: CaptureBody) -> dict:
        if kind not in KINDS:
            raise HTTPException(404, f"kind must be one of {', '.join(KINDS)}")
        cap = RawCapture(
            kind=kind, session_id=body.session_id, captured_at=body.captured_at, lat=body.lat,
            lon=body.lon, text=body.text, ends_at=body.ends_at, place_name=body.place_name,
            attendees=body.attendees, participants=body.participants,
            speaker_map=body.speaker_map, keywords=body.keywords, perception=body.perception,
            turns=body.turns,
            image=base64.b64decode(body.image_b64) if body.image_b64 else None,
            audio=base64.b64decode(body.audio_b64) if body.audio_b64 else None)
        try:
            results = engine.ingest(cap)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return {"results": [{"status": r.ingest.status, "reason": r.ingest.reason,
                             "source_id": r.ingest.observation.source_id if r.ingest.observation
                             else None,
                             "claims": len(r.compiled.claim_ids) if r.compiled else 0,
                             "compile_rejected": r.compiled.rejected if r.compiled else None}
                            for r in results]}

    @app.post("/recall/ask")
    def ask(body: AskBody) -> dict:
        try:
            return recall.ask(body.question)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.get("/claims/{claim_id}/provenance")
    def provenance(claim_id: str) -> dict:
        out = recall.provenance(claim_id)
        if "error" in out:
            raise HTTPException(404, out["error"])
        return out

    @app.get("/demo/grants")
    def demo_grants() -> list[dict]:
        """DEMO ONLY: the revocation tokens a real person would hold on their own device, so
        the demo can act as 'Alex scans the QR code'. Never expose this outside a demo."""
        out = []
        for g in grants():
            out.append({**g, "demo_token": demo.tokens.get(f"{g['grantor']}:{g['scope_ref']}")})
        return out

    @app.get("/demo/status")
    def demo_status() -> dict:
        return {**demo.status(), "llm_mode": llm.mode}

    @app.post("/demo/reset")
    def demo_reset() -> dict:
        demo.reset()
        return demo.status()

    @app.post("/demo/advance")
    def demo_advance(steps: int = 1) -> dict:
        try:
            played = demo.advance(max(1, min(steps, 50)))
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return {"played": played, **demo.status()}

    @app.post("/demo/live/{event_id}")
    def demo_live(event_id: str) -> dict:
        if event_id not in demo.status()["live_uploads"]:
            raise HTTPException(404, "not a live-upload event")
        try:
            results = demo.play(event_id)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return {"ingested": sum(r.ingest.status == "ingested" for r in results)}

    return app
