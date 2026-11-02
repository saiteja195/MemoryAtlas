"""Small, authenticated phone ingress. Never expose the unauthenticated demo API to a LAN."""
import base64
import binascii
import hmac
import os
import threading
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from . import db
from .capture.models import RawCapture
from .config import Settings
from .engine import MemoryEngine
from .llm.base import LLMClient, LLMUnavailable
from .llm.factory import build_client
from .privacy.consent import create_grant

MAX_PHOTO_BYTES = 2 * 1024 * 1024


class PhotoUpload(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    captured_at: AwareDatetime
    image_b64: str = Field(min_length=4, max_length=4 * ((MAX_PHOTO_BYTES + 2) // 3))


def create_mobile_app(settings: Settings | None = None, llm: LLMClient | None = None,
                      token: str | None = None) -> FastAPI:
    settings = settings or Settings()
    token = token if token is not None else os.getenv("MEMORYATLAS_MOBILE_TOKEN", "")
    if len(token) < 32 or token.strip() != token:
        raise RuntimeError("Set MEMORYATLAS_MOBILE_TOKEN to at least 32 non-whitespace characters")
    conn = db.connect(settings.db_path)
    client = llm or build_client(settings)
    engine = MemoryEngine(conn, client)
    lock = threading.RLock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        conn.close()

    app = FastAPI(title="MemoryAtlas phone gateway", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error):
        # Pydantic's normal error includes the rejected input (potentially a whole photo).
        return JSONResponse(status_code=422, content={"detail": "Invalid photo request: check "
                            "the timestamp, session and JPEG size (maximum 2 MiB)."})

    def authorize(authorization: Annotated[str | None, Header()] = None):
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Invalid phone access token", headers={"WWW-Authenticate": "Bearer"})

    def require_live():
        if client.mode != "live":
            raise HTTPException(409, "Real glasses photos require MEMORYATLAS_LLM_MODE=live")
        if llm is None and not settings.llm_api_key:
            raise HTTPException(503, "Set MODEL_API_KEY on the backend before capturing")

    protected = [Depends(authorize)]

    @app.get("/mobile/health", dependencies=protected)
    def health():
        require_live()
        return {"status": "ok", "llm_mode": client.mode, "max_photo_bytes": MAX_PHOTO_BYTES}

    @app.post("/mobile/sessions", dependencies=protected)
    def session():
        require_live()
        with lock:
            sid = f"glasses-{uuid.uuid4().hex}"
            gid, revocation_token = create_grant(conn, settings.revocation_secret, "me", sid)
        return {"session_id": sid, "grant_id": gid, "revocation_token": revocation_token}

    @app.post("/mobile/photos", dependencies=protected)
    def photo(body: PhotoUpload):
        require_live()
        try:
            raw = base64.b64decode(body.image_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Photo must be valid base64 JPEG data") from None
        if not raw or len(raw) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "Photo exceeds the 2 MiB limit")
        if not (raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")):
            raise HTTPException(422, "Expected JPEG data")
        # Existing compiler timestamps are naive LOCAL wall time. Keep the phone's timezone
        # explicit at the boundary, then convert to the Mac's local zone before episode binding.
        local_time = body.captured_at.astimezone().replace(tzinfo=None).isoformat()
        capture = RawCapture(kind="frame", session_id=body.session_id,
                             captured_at=local_time, image=raw)
        try:
            with lock:
                own = conn.execute(
                    "SELECT 1 FROM consent_grants WHERE scope_ref=? AND grantor='me'"
                    " AND scope='capture_session' AND revoked_at IS NULL", (body.session_id,)
                ).fetchone()
                if not body.session_id.startswith("glasses-") or not own:
                    raise HTTPException(403, "Start a new consented glasses session")
                (result,) = engine.ingest(capture)
                if not result.ingest.observation:
                    raise HTTPException(422, f"Photo not accepted: {result.ingest.reason}")
                compiled = result.compiled
                if not compiled or compiled.rejected or not compiled.claim_ids:
                    raise HTTPException(422, "The photo was processed but no memory was compiled. "
                                        "Try a clear photo of an object or sign.")
                source = result.ingest.observation
                return {"status": "stored", "source_id": source.source_id,
                        "claim_ids": compiled.claim_ids, "claims": len(compiled.claim_ids),
                        "observation": source.text, "event_time": local_time,
                        "raw_media_bytes_retained": 0}
        except LLMUnavailable:
            # Provider diagnostics must not echo a photo, token or model request into the UI.
            raise HTTPException(503, "Model unavailable; check the backend configuration and retry") from None
        finally:
            capture.image = None
            raw = b""

    return app
