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
import threading
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


_INSERT = ("INSERT OR IGNORE INTO model_calls (call_id, at, model, kind, purpose, memory_day, "
           "served_from, duration_ms, ok, images, words_in, words_out, audio_ms, "
           "tokens_in, tokens_out) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
_BUSY_TIMEOUT_S = 0.1     # a usage row never makes a request wait long
_MAX_PENDING = 500


class MeteredLLM:
    def __init__(self, inner: LLMClient, conn: sqlite3.Connection, models: dict[str, str]):
        self._inner, self._conn, self._models = inner, conn, models
        self._lock = threading.Lock()
        self._pending: list[tuple] = []     # rows waiting for the database to be free

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
                self._write(self._row(kind, elapsed, ok, result, words_in, images))
            except Exception as e:  # noqa: BLE001  metering must never fail a model call
                log.warning("could not log model call: %s", type(e).__name__)

    def _row(self, kind: str, duration_ms: int, ok: int, result: Any,
             words_in: int, images: int) -> tuple:
        # Read the per-call labels first, on this thread, before anything else can overwrite them.
        purpose, memory_day = _purpose.get()
        served = getattr(self._inner, "last_served", "live")
        usage = self._usage(served) if ok else None
        if kind == "asr":
            turns = result or []
            words_out = sum(_words(t.get("text")) for t in turns)
            audio_ms = max((int(t.get("end_ms") or 0) for t in turns), default=0)
        else:
            words_out, audio_ms = _result_words(result), 0
        model = self._models["asr" if kind == "asr" else "text"]
        return (uuid.uuid4().hex, clock.now_iso(), model, kind, purpose, memory_day, served,
                duration_ms, ok, images, words_in, words_out, audio_ms,
                usage["tokens_in"] if usage else None, usage["tokens_out"] if usage else None)

    def _db_file(self) -> str | None:
        """The database file behind the request connection, or None for an in-memory database."""
        try:
            for row in self._conn.execute("PRAGMA database_list"):
                if row[1] == "main":
                    return row[2] or None
        except Exception:  # noqa: BLE001  not a real connection: use it as it is
            return None
        return None

    def flush(self) -> None:
        """Write any rows that were held back while a request was mid-transaction. Call it once the
        request's own work is committed; it never raises."""
        try:
            self._write(None)
        except Exception as e:  # noqa: BLE001
            log.warning("could not flush model call log: %s", type(e).__name__)

    def _write(self, row: tuple | None) -> None:
        """Store one row without touching the request's own transaction.

        A file database gets a short-lived connection of its own (WAL), so committing the usage
        row never commits, or waits behind, another handler's half-done work on the shared request
        connection. If that write cannot proceed right away (a request is mid-transaction), the
        row waits in memory and goes out with the next one (or with `flush()`). An in-memory database (tests) has no
        second connection to open, so the shared one is used under a lock, rolled back on failure.
        """
        path = self._db_file()
        if path is None:
            if row is None:
                return
            with self._lock:
                try:
                    self._conn.execute(_INSERT, row)
                    self._conn.commit()
                except Exception:
                    with contextlib.suppress(Exception):
                        self._conn.rollback()
                    raise
            return
        with self._lock:
            if row is not None:
                self._pending.append(row)
            if self._conn.in_transaction:
                # A request is mid-transaction: the side connection would only wait and fail. Hold the
                # row; `flush()` (or the next call outside a transaction) writes it.
                del self._pending[:-_MAX_PENDING]
                return
            batch = list(self._pending)
        if not batch:
            return
        try:
            side = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_S)
            try:
                with side:
                    side.executemany(_INSERT, batch)
            finally:
                side.close()
        except sqlite3.Error as e:
            with self._lock:
                del self._pending[:-_MAX_PENDING]
            log.warning("model call log busy, will retry: %s", type(e).__name__)
            return
        with self._lock:
            self._pending[:] = [r for r in self._pending if r not in batch]

    def _usage(self, served: str) -> dict[str, int] | None:
        """Token counts reported by the live API for the call just made (none for a cache hit)."""
        if served != "live":
            return None
        client = self._inner
        # A record/replay cache wraps the live client; look through it.
        usage = getattr(client, "last_usage", None) or getattr(
            getattr(client, "_inner", None), "last_usage", None)
        return usage if isinstance(usage, dict) else None
