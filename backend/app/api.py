import base64
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from .capture.audit import media_bytes_on_disk
from .jobs import Busy, JobBoard
from .capture.commit import Answers, CommitError, commit as commit_draft, plan as plan_commit
from .capture.media_info import MediaError
from .capture.models import KINDS, RawCapture
from .capture.preview import BadRequest, TooLarge, build_preview
from .config import Settings
from .corrections import CorrectionError, correct_claim
from .graph import build_graph
from .insights.coverage import coverage, memory_days
from .insights.usage import usage_summary
from .llm.base import LLMClient, LLMUnavailable
from .llm.metered import usage_purpose
from .privacy import clock
from .privacy.consent import active_grant, create_grant
from .privacy.export import export_memories
from .privacy.revocation import BadToken, UnknownGrant
from .profiles.registry import Registry
from .profiles.limits import Budget, RateLimiter
from .profiles.routes import client_ip, make_router
from .profiles.runtime import ProfileRuntime, Runtimes
from .profiles import snapshots
from .profiles.session import current_profile, open_runtime, resolve_runtime
from .todos import count_open, list_todos, set_todo_state
from .tracking import MAX_FRAMES, MAX_FRAME_BYTES, PhraseError, clean_phrases, follow_objects, perception_for

_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


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


TodoFilter = Literal["open", "done", "dismissed", "all"]


class TodoBody(BaseModel):
    state: Literal["open", "done", "dismissed"]


class PreviewBody(BaseModel):
    kind: Literal["frame", "audio", "note", "video", "photos"]
    data_b64: str | None = None                 # frame: the image. audio: the WAV
    frames_b64: list[str] = Field(default_factory=list)       # video: 1 to 8 JPEG frames. photos: 1 to 8 photos
    photo_times: list[str | None] = Field(default_factory=list)   # photos: each file's own time, naive ISO, or none
    frame_offsets_ms: list[int] = Field(default_factory=list)
    audio_b64: str | None = None                # video: the audio track as WAV
    text: str | None = None
    file_modified_at: str | None = None         # local time of the file, naive ISO


class CommitBody(BaseModel):
    draft_id: str
    answers: Answers = Field(default_factory=Answers)


class TrackBody(BaseModel):
    """A few evenly spaced frames from a video, and the objects to look for in them. Nothing is stored until the
    objects have been found, and only words are kept."""
    frames_b64: list[str] = Field(min_length=1, max_length=MAX_FRAMES)
    offsets_ms: list[int] = Field(min_length=1, max_length=MAX_FRAMES)
    phrases: list[str] = Field(min_length=1, max_length=8)
    clip_start: str
    duration_ms: int = Field(ge=0, le=24 * 3600 * 1000)

    @field_validator("clip_start")
    @classmethod
    def _when(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except ValueError as e:
            raise ValueError("clip_start must be a date and time like 2026-10-29T12:42:10") from e
        return v

    @field_validator("phrases")
    @classmethod
    def _words(cls, v: list[str]) -> list[str]:
        try:
            return clean_phrases(v)
        except PhraseError as e:
            raise ValueError(str(e)) from e

    @field_validator("offsets_ms")
    @classmethod
    def _offsets(cls, v: list[int]) -> list[int]:
        if any(o < 0 for o in v) or v != sorted(v):
            raise ValueError("offsets_ms must be increasing, from the start of the clip")
        return v


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")   # the day "today" means

    @field_validator("as_of")
    @classmethod
    def _real_day(cls, v: str | None) -> str | None:
        if v is not None:
            date.fromisoformat(v)          # 2026-10-32 is not a day: a ValueError becomes a 422
        return v


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


def _grants(conn) -> list[dict]:
    # receipt_id lets another browser tab (the person withdrawing consent) tell this one
    # which receipt to show, without the two pages talking to each other directly.
    return [dict(r) for r in conn.execute(
        "SELECT g.grant_id, g.grantor, g.scope, g.scope_ref, g.granted_at, g.revoked_at,"
        " g.expires_at, g.ended_reason,"
        " (SELECT r.receipt_id FROM forgetting_receipts r WHERE r.grant_id = g.grant_id"
        "  ORDER BY r.created_at LIMIT 1) AS receipt_id"
        " FROM consent_grants g ORDER BY g.granted_at, g.grant_id")]


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="MemoryAtlas")
    registry: Registry | None = None
    if settings.auth:
        if settings.data_dir:
            root = settings.data_dir
        elif settings.db_path == ":memory:":
            root = tempfile.mkdtemp(prefix="memoryatlas-profiles-")
        else:
            root = os.path.dirname(os.path.abspath(settings.db_path))
        os.makedirs(root, exist_ok=True)
        registry = Registry(os.path.join(root, "profiles.db"))
        runtimes = Runtimes(settings, llm, root)
    else:
        runtimes = Runtimes(settings, llm, None)
        default = runtimes.get("local", "Local", True)       # seeded exactly as before profiles existed
        app.state.conn, app.state.engine, app.state.demo, app.state.drafts = (
            default.conn, default.engine, default.demo, default.drafts)
    app.state.registry, app.state.runtimes = registry, runtimes
    app.include_router(make_router(settings, registry, runtimes))

    def get_runtime(request: Request) -> ProfileRuntime:
        """The caller's own runtime. Every data route depends on this and on nothing else for its data."""
        if registry is None:
            rt = runtimes.get("local", "Local", True)
        else:
            rt = resolve_runtime(request, registry, runtimes)
        rt.sweep()
        return rt

    app.state.budget = Budget()
    jobs = app.state.jobs = JobBoard()

    def spend(request: Request, rt: ProfileRuntime = Depends(get_runtime)) -> None:
        """Every route that calls the model costs the owner money; count it against the profile and the address."""
        if registry is None:
            return
        profile = current_profile(request, registry)
        wait = app.state.budget.check(profile.profile_id, bool(profile.demo_kind), client_ip(request))
        if wait:
            raise HTTPException(429, "You have used a lot of Muse calls. Try again in a little while.",
                                headers={"Retry-After": str(int(wait) + 1)})

    @app.get("/health")
    def health() -> dict:
        mode = llm.mode if llm else settings.llm_mode
        return {"status": "ok", "llm_mode": mode, "auth": settings.auth}

    @app.get("/graph")
    def graph(at: str | None = None, include: str | None = None,
              rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        return build_graph(rt.conn, at, include_history=include == "history")

    @app.get("/insights")
    def insights(day: str | None = Query(None), rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        if day is not None:
            try:
                if not _DAY.fullmatch(day):
                    raise ValueError(day)
                date.fromisoformat(day)
            except ValueError:
                raise HTTPException(422, "day must be a real date like 2026-10-29") from None
        days = memory_days(rt.conn)
        chosen = day or (days[-1] if days else None)
        return {"day": chosen, "days": days,
                "coverage": coverage(rt.conn, chosen) if chosen else None,
                "usage": usage_summary(rt.conn, chosen),
                "todos_open": count_open(rt.conn, rt.engine.gateway.owner)}

    @app.get("/todos")
    def todos(state: TodoFilter = "open", rt: ProfileRuntime = Depends(get_runtime)) -> list[dict]:
        return list_todos(rt.conn, rt.engine.gateway.owner, state)

    @app.post("/todos/{claim_id}")
    def todo_state(claim_id: str, body: TodoBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        owner = rt.engine.gateway.owner
        try:
            set_todo_state(rt.conn, claim_id, body.state, owner)
        except KeyError:
            raise HTTPException(404, "That is not one of your to-dos.") from None
        return next(t for t in list_todos(rt.conn, owner, "all") if t["claim_id"] == claim_id)

    @app.get("/privacy/media")
    def media(rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        retained = rt.conn.execute("SELECT COALESCE(SUM(media_bytes_retained),0) FROM sources"
                                   ).fetchone()[0]
        data_dir = None if rt.db_path is None else os.path.dirname(rt.db_path)
        on_disk = media_bytes_on_disk(*([data_dir] if data_dir else []), recursive=False)
        on_disk += media_bytes_on_disk(rt.settings.cache_dir, rt.cache_dir)
        return {"raw_media_bytes_retained": retained, "media_bytes_on_disk": on_disk}

    @app.post("/consent/grants")
    def grant(body: GrantBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        expires = clock.now() + timedelta(hours=body.valid_for_hours) if body.valid_for_hours else None
        gid, token = create_grant(rt.conn, rt.settings.revocation_secret, body.grantor,
                                  body.session_id, body.purposes, expires_at=expires)
        return {"grant_id": gid, "revocation_token": token,
                "expires_at": clock.iso(expires) if expires else None}

    @app.get("/consent/grants")
    def grants(rt: ProfileRuntime = Depends(get_runtime)) -> list[dict]:
        return _grants(rt.conn)

    @app.post("/consent/grants/{grant_id}/revoke")
    def revoke(grant_id: str, body: RevokeBody, red_team: bool = True,
               rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Withdraw consent: forget everything only this grant supported. The token is the
        proof that the person who consented is the one asking."""
        try:
            return rt.revoker.revoke(grant_id, body.token, run_red_team=red_team)
        except UnknownGrant:
            raise HTTPException(404, "unknown grant") from None
        except BadToken:
            raise HTTPException(403, "wrong revocation token") from None

    @app.post("/consent/expire-due")
    def expire_due(rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Forget what rested on grants that have lapsed. The API does this by itself before each request;
        call this from a scheduler to do it on time even when nobody is using the app."""
        receipts = rt.sweep()
        return {"expired": [{"grant_id": r["grant_id"], "receipt_id": r["receipt_id"]} for r in receipts]}

    @app.get("/receipts/{receipt_id}")
    def receipt(receipt_id: str, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        found = rt.revoker.get_receipt(receipt_id)
        if found is None:
            raise HTTPException(404, "unknown receipt")
        return found

    @app.get("/export")
    def export(rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        return export_memories(rt.conn)

    def require_live(rt: ProfileRuntime) -> None:
        # In record mode every model response is written to the cache, including a transcript of someone
        # who then says no. Uploads therefore run only on the live client, which keeps nothing.
        if rt.llm.mode != "live":
            raise HTTPException(409, "Adding memories needs live mode (a model key); this app is in "
                                     f"{rt.llm.mode} mode.")

    @app.post("/capture/preview", dependencies=[Depends(spend)])
    def capture_preview(body: PreviewBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Read an upload with Muse and return what it understood and what it still needs to
        ask. Stores nothing; the commit step does that."""
        require_live(rt)
        try:
            draft = build_preview(
                rt.llm, body.kind, data_b64=body.data_b64, frames_b64=body.frames_b64,
                frame_offsets_ms=body.frame_offsets_ms, audio_b64=body.audio_b64, text=body.text,
                file_modified_at=body.file_modified_at, photo_times=body.photo_times)
        except TooLarge as e:
            raise HTTPException(413, str(e)) from None
        except BadRequest as e:
            raise HTTPException(422, str(e)) from None
        except MediaError as e:
            raise HTTPException(415, str(e)) from None
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return rt.drafts.put(draft).model_dump()

    def take_confirmed_draft(rt: ProfileRuntime, body: CommitBody):
        """Check a confirmed draft and take it (from here on a second call gets 404). Consent is decided here,
        in code, from the answers."""
        require_live(rt)
        try:
            draft = rt.drafts.peek(body.draft_id)
        except KeyError:
            raise HTTPException(404, "draft expired or unknown") from None
        try:
            decided = plan_commit(draft, body.answers, rt.engine.gateway.owner)
        except CommitError as e:
            raise HTTPException(e.status, e.message) from None
        try:
            rt.drafts.take(body.draft_id)
        except KeyError:
            raise HTTPException(404, "draft expired or unknown") from None
        return draft, decided

    @app.post("/capture/commit", dependencies=[Depends(spend)])
    def capture_commit(body: CommitBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Store a confirmed draft and wait for it (kept for scripts; the page uses /capture/commit/start)."""
        draft, decided = take_confirmed_draft(rt, body)
        try:
            return commit_draft(rt.conn, rt.engine, rt.settings.revocation_secret, draft, decided)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.post("/capture/commit/start", status_code=202, dependencies=[Depends(spend)])
    def capture_commit_start(body: CommitBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Store a confirmed draft in the background and return at once: a slow model must not hold the request
        open until the proxy gives up. Poll `GET /capture/commit/jobs/{job_id}` for the outcome."""
        if jobs.busy(rt.profile_id):
            raise HTTPException(409, "A memory is already being saved. Wait for it to finish.")
        draft, decided = take_confirmed_draft(rt, body)
        try:
            job = jobs.start(rt.profile_id, lambda: commit_draft(
                rt.conn, rt.engine, rt.settings.revocation_secret, draft, decided))
        except Busy:
            rt.drafts.put(draft)                     # lost the race for the one running slot: keep the draft
            raise HTTPException(409, "A memory is already being saved. Wait for it to finish.") from None
        return {"job_id": job.job_id}

    @app.get("/capture/commit/jobs/{job_id}")
    def capture_commit_job(job_id: str, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        job = jobs.get(rt.profile_id, job_id)
        if job is None:
            raise HTTPException(404, "unknown save")
        return JobBoard.status(job)

    track_limit = app.state.track_limit = RateLimiter(5, 3600.0)      # five videos an hour per profile

    @app.post("/capture/track", status_code=202, dependencies=[Depends(spend)])
    def capture_track(body: TrackBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Opt-in: look for named objects in a video's frames (SAM 3.1, one image at a time) and keep a text note of
        when each was visible. Runs in the background like a save; poll `GET /capture/commit/jobs/{job_id}`."""
        if len(body.frames_b64) != len(body.offsets_ms):
            raise HTTPException(422, "send one offset for each frame")
        if rt.llm.mode != "live":
            raise HTTPException(409, "Object tracking needs the live model, and this copy is not connected to it.")
        try:
            frames = [base64.b64decode(f, validate=True) for f in body.frames_b64]
        except ValueError:
            raise HTTPException(422, "frames must be base64") from None
        if any(not f or len(f) > MAX_FRAME_BYTES for f in frames):
            raise HTTPException(422, "each frame must be a JPEG or PNG under 2 MB")
        if jobs.busy(rt.profile_id):
            raise HTTPException(409, "Something is already being saved. Wait for it to finish.")
        if not track_limit.allow(rt.profile_id):
            raise HTTPException(429, "You have tracked a lot of videos. Try again in a little while.",
                                headers={"Retry-After": str(int(track_limit.retry_after(rt.profile_id)) + 1)})
        day = body.clip_start[:10]

        def work() -> dict:
            with usage_purpose("read_memory", day):
                objects = follow_objects(rt.llm, frames, body.offsets_ms, body.phrases)
            found = [o for o in objects if o["found"]]
            grants: list[dict] = []
            if found:
                session = f"upload-{day}"
                owner = rt.engine.gateway.owner
                if not active_grant(rt.conn, owner, session):
                    gid, token = create_grant(rt.conn, rt.settings.revocation_secret, owner, session)
                    grants.append({"person": owner, "grant_id": gid, "revocation_token": token})
                with usage_purpose("read_memory", day):
                    rt.engine.ingest(RawCapture(kind="frame", session_id=session, captured_at=body.clip_start,
                                                perception=perception_for(objects)))
            return {"objects": objects, "stored": bool(found), "grants": grants}

        try:
            job = jobs.start(rt.profile_id, work)
        except Busy:
            raise HTTPException(409, "Something is already being saved. Wait for it to finish.") from None
        return {"job_id": job.job_id}

    @app.post("/capture/{kind}", dependencies=[Depends(spend)])
    def capture(kind: str, body: CaptureBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
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
            results = rt.engine.ingest(cap)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return {"results": [{"status": r.ingest.status, "reason": r.ingest.reason,
                             "source_id": r.ingest.observation.source_id if r.ingest.observation
                             else None,
                             "claims": len(r.compiled.claim_ids) if r.compiled else 0,
                             "compile_rejected": r.compiled.rejected if r.compiled else None}
                            for r in results]}

    @app.post("/recall/ask", dependencies=[Depends(spend)])
    def ask(body: AskBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        try:
            return rt.recall.ask(body.question, body.as_of)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.get("/chat")
    def chat(rt: ProfileRuntime = Depends(get_runtime)) -> list[dict]:
        """The conversation so far, so the assistant shows the same thread after a reload and on every page."""
        return rt.recall.history()

    @app.get("/claims/{claim_id}/provenance")
    def provenance(claim_id: str, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        out = rt.recall.provenance(claim_id)
        if "error" in out:
            raise HTTPException(404, out["error"])
        return out

    @app.post("/claims/{claim_id}/correct", dependencies=[Depends(spend)])
    def correct(claim_id: str, body: CorrectBody, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """The user says a remembered fact is wrong: replace it with `text`, or `retract` it. The old
        fact stays as history; answers stop using it (and anything derived only from it)."""
        try:
            return correct_claim(rt.engine, claim_id, body.text, body.retract, body.at)
        except CorrectionError as e:
            raise HTTPException(e.code, e.message) from None
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e

    @app.get("/demo/grants")
    def demo_grants(rt: ProfileRuntime = Depends(get_runtime)) -> list[dict]:
        """DEMO ONLY: the revocation tokens a real person would hold on their own device, so
        the demo can act as 'Alex scans the QR code'. Never expose this outside a demo."""
        return [{**g, "demo_token": rt.demo.tokens.get(f"{g['grantor']}:{g['scope_ref']}")}
                for g in _grants(rt.conn)]

    @app.post("/demo/grants/{grant_id}/expire")
    def demo_expire(grant_id: str, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """DEMO ONLY: let a grant lapse now, so the demo can show expiry without waiting. Never expose this
        outside a demo."""
        if not rt.conn.execute("SELECT 1 FROM consent_grants WHERE grant_id=? AND revoked_at IS NULL",
                               (grant_id,)).fetchone():
            raise HTTPException(404, "unknown or already ended grant")
        with rt.sweep_lock:
            rt.conn.execute("UPDATE consent_grants SET expires_at=? WHERE grant_id=?",
                            (clock.iso(clock.now() - timedelta(seconds=1)), grant_id))
            rt.conn.commit()
        receipts = rt.sweep()
        return {"expired": [{"grant_id": r["grant_id"], "receipt_id": r["receipt_id"]} for r in receipts]}

    @app.get("/demo/status")
    def demo_status(rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        return {**rt.demo.status(), "llm_mode": rt.llm.mode}

    @app.post("/demo/reset")
    def demo_reset(request: Request, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        if registry is None:
            rt.demo.reset()
            return rt.demo.status()
        profile = current_profile(request, registry)
        if not profile.demo_kind:
            raise HTTPException(403, "Only demo profiles can be reset. Use Settings to delete your profile.")
        with runtimes.exclusive(profile.profile_id):         # nobody rebuilds this profile while its database is swapped
            try:
                snapshots.restore(runtimes, profile)
            except FileNotFoundError:
                if profile.demo_kind != "staged":
                    raise HTTPException(
                        503, f"The {profile.demo_kind} demo snapshot is not installed on this server.") from None
                rt.demo.reset()              # no snapshot yet: replay the script into the profile
                return rt.demo.status()
        return open_runtime(profile, runtimes).demo.status()

    @app.post("/demo/load-sample", dependencies=[Depends(spend)])
    def demo_load_sample(request: Request, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        """Fill an empty profile with the scripted sample day, for anyone with nothing to upload yet."""
        if registry is not None:
            if rt.conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
                raise HTTPException(409, "This profile already has memories")
            profile = current_profile(request, registry)
            if os.path.isfile(snapshots.snapshot_path("staged")):
                # Playing the day through a live model takes minutes and outlasts the proxy's timeout, so copy
                # the committed snapshot in (text only, no model calls), as a demo profile's reset does.
                with runtimes.exclusive(profile.profile_id):
                    if runtimes.get(profile.profile_id, profile.name, False).conn.execute(
                            "SELECT 1 FROM sources LIMIT 1").fetchone():
                        raise HTTPException(409, "This profile already has memories")
                    snapshots.restore(runtimes, profile, "staged")
                    fresh = runtimes.get(profile.profile_id, profile.name, False)
                    fresh.demo.rekey()
                    fresh.demo.mark_all_played()
                return fresh.demo.status()
            rt.demo.reset()
        try:
            rt.demo.advance(50)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return rt.demo.status()

    @app.post("/demo/advance", dependencies=[Depends(spend)])
    def demo_advance(steps: int = 1, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        try:
            played = rt.demo.advance(max(1, min(steps, 50)))
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return {"played": played, **rt.demo.status()}

    @app.post("/demo/live/{event_id}", dependencies=[Depends(spend)])
    def demo_live(event_id: str, rt: ProfileRuntime = Depends(get_runtime)) -> dict:
        if event_id not in rt.demo.status()["live_uploads"]:
            raise HTTPException(404, "not a live-upload event")
        try:
            results = rt.demo.play(event_id)
        except LLMUnavailable as e:
            raise HTTPException(503, str(e)) from e
        return {"ingested": sum(r.ingest.status == "ingested" for r in results)}

    return app
