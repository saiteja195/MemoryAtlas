import base64
import logging
import os
import threading
from datetime import timedelta
from dataclasses import replace
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from . import db
from .capture.adapters import MockDayAdapter
from .capture.audit import media_bytes_on_disk
from .capture.commit import Answers, CommitError, commit as commit_draft, plan as plan_commit
from .capture.draft import DraftStore
from .capture.media_info import MediaError
from .capture.models import KINDS, RawCapture
from .capture.preview import BadRequest, TooLarge, build_preview
from .corrections import CorrectionError, correct_claim
from .config import Settings, runtime_cache_path
from .demo import DemoRunner
from .demo_acts import load_acts
from .engine import MemoryEngine
from .graph import build_graph
from .llm.base import LLMClient, LLMUnavailable
from .llm.factory import build_client
from .privacy import clock
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


class PreviewBody(BaseModel):
    kind: Literal["frame", "audio", "note", "video"]
    data_b64: str | None = None                 # frame: the image. audio: the WAV
    frames_b64: list[str] = Field(default_factory=list)       # video: 1 to 4 JPEG frames
    frame_offsets_ms: list[int] = Field(default_factory=list)
    audio_b64: str | None = None                # video: the audio track as WAV
    text: str | None = None
    file_modified_at: str | None = None         # local time of the file, naive ISO


class CommitBody(BaseModel):
    draft_id: str
    answers: Answers = Field(default_factory=Answers)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class RevokeBody(BaseModel):
    token: str = Field(min_length=1)


class CorrectBody(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    retract: bool = False
    at: str | None = None


class GrantBody(BaseModel):
    grantor: str
    session_id: str
    purposes: list[str] | None = None
    # How long the consent lasts. Omitted: until the person withdraws it. When it lapses, everything that
    # rested only on it is forgotten, exactly as if they had withdrawn it.
    valid_for_hours: float | None = Field(default=None, gt=0, le=8760)


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
    sweep_lock = threading.Lock()
    log = logging.getLogger("memoryatlas")

    def sweep() -> list[dict]:
        """Purge grants that have expired. Safe to call at any time; one at a time."""
        with sweep_lock:
            try:
                return revoker.sweep()
            except Exception:       # a failed purge must not take the API down; the filter still refuses the data
                log.exception("expiry sweep failed")
                return []

    def sweep_before_request(request: Request) -> None:
        if request.url.path != "/health":       # the health check must stay instant
            sweep()

    data_dir = None if settings.db_path == ":memory:" else os.path.dirname(os.path.abspath(
        settings.db_path))

    sweep()                                     # anything that lapsed while the app was off
    app = FastAPI(title="MemoryAtlas", dependencies=[Depends(sweep_before_request)])
    drafts = DraftStore()
    app.state.conn, app.state.engine, app.state.demo, app.state.drafts = conn, engine, demo, drafts

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
        expires = clock.now() + timedelta(hours=body.valid_for_hours) if body.valid_for_hours else None
        gid, token = create_grant(conn, settings.revocation_secret, body.grantor,
                                  body.session_id, body.purposes, expires_at=expires)
        return {"grant_id": gid, "revocation_token": token,
                "expires_at": clock.iso(expires) if expires else None}

    @app.get("/consent/grants")
    def grants() -> list[dict]:
        # receipt_id lets another browser tab (the person withdrawing consent) tell this one
        # which receipt to show, without the two pages talking to each other directly.
        return [dict(r) for r in conn.execute(
            "SELECT g.grant_id, g.grantor, g.scope, g.scope_ref, g.granted_at, g.revoked_at,"
            " g.expires_at, g.ended_reason,"
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

    @app.post("/consent/expire-due")
    def expire_due() -> dict:
        """Forget what rested on grants that have lapsed. The API does this by itself before each request;
        call this from a scheduler to do it on time even when nobody is using the app."""
        receipts = sweep()
        return {"expired": [{"grant_id": r["grant_id"], "receipt_id": r["receipt_id"]} for r in receipts]}

    @app.get("/receipts/{receipt_id}")
    def receipt(receipt_id: str) -> dict:
        found = revoker.get_receipt(receipt_id)
        if found is None:
            raise HTTPException(404, "unknown receipt")
        return found

    @app.get("/export")
    def export() -> dict:
        return export_memories(conn)

    @app.post("/capture/preview")
    def capture_preview(body: PreviewBody) -> dict:
        """Read an upload with Muse and return what it understood and what it still needs to
        ask. Stores nothing; the commit step does that."""
        try:
            draft = build_preview(
                llm, body.kind, data_b64=body.data_b64, frames_b64=body.frames_b64,
                frame_offsets_ms=body.frame_offsets_ms, audio_b64=body.audio_b64, text=body.text,
                file_modified_at=body.file_modified_at)
        except TooLarge as e:
            raise HTTPException(413, str(e)) from None
        except BadRequest as e:
            raise HTTPException(422, str(e)) from None
        except MediaError as e:
            raise HTTPException(415, str(e)) from None
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return drafts.put(draft).model_dump()

    @app.post("/capture/commit")
    def capture_commit(body: CommitBody) -> dict:
        """Store a confirmed draft. Consent is decided here, in code, from the answers."""
        try:
            draft = drafts.peek(body.draft_id)
        except KeyError:
            raise HTTPException(404, "draft expired or unknown") from None
        try:
            decided = plan_commit(draft, body.answers, engine.gateway.owner)
        except CommitError as e:
            raise HTTPException(e.status, e.message) from None
        try:
            drafts.take(body.draft_id)          # from here on a second call gets 404
        except KeyError:
            raise HTTPException(404, "draft expired or unknown") from None
        try:
            return commit_draft(conn, engine, settings.revocation_secret, draft, decided)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e

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

    @app.post("/claims/{claim_id}/correct")
    def correct(claim_id: str, body: CorrectBody) -> dict:
        """The user says a remembered fact is wrong: replace it with `text`, or `retract` it. The old
        fact stays as history; answers stop using it (and anything derived only from it)."""
        try:
            return correct_claim(engine, claim_id, body.text, body.retract, body.at)
        except CorrectionError as e:
            raise HTTPException(e.code, e.message) from None
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.get("/demo/grants")
    def demo_grants() -> list[dict]:
        """DEMO ONLY: the revocation tokens a real person would hold on their own device, so
        the demo can act as 'Alex scans the QR code'. Never expose this outside a demo."""
        out = []
        for g in grants():
            out.append({**g, "demo_token": demo.tokens.get(f"{g['grantor']}:{g['scope_ref']}")})
        return out

    @app.post("/demo/grants/{grant_id}/expire")
    def demo_expire(grant_id: str) -> dict:
        """DEMO ONLY: let a grant lapse now, so the demo can show expiry without waiting. Never expose this
        outside a demo."""
        if not conn.execute("SELECT 1 FROM consent_grants WHERE grant_id=? AND revoked_at IS NULL",
                            (grant_id,)).fetchone():
            raise HTTPException(404, "unknown or already ended grant")
        with sweep_lock:
            conn.execute("UPDATE consent_grants SET expires_at=? WHERE grant_id=?",
                         (clock.iso(clock.now() - timedelta(seconds=1)), grant_id))
            conn.commit()
        receipts = sweep()
        return {"expired": [{"grant_id": r["grant_id"], "receipt_id": r["receipt_id"]} for r in receipts]}

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
