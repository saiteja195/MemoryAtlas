"""Usage metering for model calls.

`MeteredLLM` wraps any `LLMClient` and writes one `model_calls` row per call: when, which model,
what it was for, how long it took, and sizes (words, images, audio milliseconds, tokens when the
API reports them). It never stores prompts, replies, transcripts or media, and a failure to write
the row is logged and swallowed: metering must not break a model call.
"""
import contextlib
import contextvars
import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Iterator

from ..privacy import clock
from .base import LLMClient

log = logging.getLogger(__name__)

_purpose: contextvars.ContextVar[tuple[str, str | None]] = contextvars.ContextVar(
    "model_call_purpose", default=("other", None))


@contextlib.contextmanager
def usage_purpose(name: str, memory_day: str | None = None) -> Iterator[None]:
    """Label the model calls made inside the block (and the memory day they concern, if any)."""
    token = _purpose.set((name, memory_day))
    try:
        yield
    finally:
        _purpose.reset(token)


def _words(text: str | None) -> int:
    return len((text or "").split())


def _result_words(result: Any) -> int:
    if result is None:
        return 0
    try:
        return _words(json.dumps(result, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return 0


class MeteredLLM:
    def __init__(self, inner: LLMClient, conn: sqlite3.Connection, models: dict[str, str]):
        self._inner, self._conn, self._models = inner, conn, models

    @property
    def mode(self) -> str:
        return self._inner.mode

    # -- the LLMClient surface ---------------------------------------------------------------

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        return self._run("text", "complete_json", (system, user, schema),
                         words_in=_words(system) + _words(user))

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]:
        return self._run("vision", "describe_image", (image, prompt),
                         words_in=_words(prompt), images=1)

    def transcribe(self, audio: bytes, keywords: list[str] | None = None) -> list[dict[str, Any]]:
        return self._run("asr", "transcribe", (audio, keywords),
                         words_in=sum(_words(k) for k in keywords or []))

    # -- internals ---------------------------------------------------------------------------

    def _run(self, kind: str, method: str, args: tuple, *, words_in: int, images: int = 0) -> Any:
        started, ok, result = time.perf_counter(), 0, None
        try:
            result = getattr(self._inner, method)(*args)
            ok = 1
            return result
        finally:
            elapsed = int((time.perf_counter() - started) * 1000)
            try:
                self._record(kind, elapsed, ok, result, words_in, images)
            except Exception as e:  # noqa: BLE001  metering must never fail a model call
                log.warning("could not log model call: %s", type(e).__name__)

    def _record(self, kind: str, duration_ms: int, ok: int, result: Any,
                words_in: int, images: int) -> None:
        purpose, memory_day = _purpose.get()
        served = getattr(self._inner, "last_served", "live")
        if kind == "asr":
            turns = result or []
            words_out = sum(_words(t.get("text")) for t in turns)
            audio_ms = max((int(t.get("end_ms") or 0) for t in turns), default=0)
        else:
            words_out, audio_ms = _result_words(result), 0
        usage = self._usage(served) if ok else None
        model = self._models["asr" if kind == "asr" else "text"]
        try:
            self._conn.execute(
                "INSERT INTO model_calls (call_id, at, model, kind, purpose, memory_day, "
                "served_from, duration_ms, ok, images, words_in, words_out, audio_ms, "
                "tokens_in, tokens_out) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, clock.now_iso(), model, kind, purpose, memory_day, served,
                 duration_ms, ok, images, words_in, words_out, audio_ms,
                 usage["tokens_in"] if usage else None, usage["tokens_out"] if usage else None))
            self._conn.commit()
        except sqlite3.Error as e:
            log.warning("could not log model call: %s", type(e).__name__)

    def _usage(self, served: str) -> dict[str, int] | None:
        """Token counts reported by the live API for the call just made (none for a cache hit)."""
        if served != "live":
            return None
        client = self._inner
        # A record/replay cache wraps the live client; look through it.
        usage = getattr(client, "last_usage", None) or getattr(
            getattr(client, "_inner", None), "last_usage", None)
        return usage if isinstance(usage, dict) else None
