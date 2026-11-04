"""What a background job is doing, as far as the person can be told: how many model calls it has started and
finished, and how long the current one has been running. The metering client reports each call here; nothing
else about the call (no prompt, no reply) is kept."""
import contextlib
import contextvars
import threading
import time
from typing import Iterator


class Progress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls_started = 0
        self.calls_done = 0
        self._call_began: float | None = None

    def call_started(self) -> None:
        with self._lock:
            self.calls_started += 1
            self._call_began = time.monotonic()

    def call_finished(self) -> None:
        with self._lock:
            self.calls_done += 1
            self._call_began = None

    def snapshot(self) -> tuple[int, int, float]:
        """(started, done, seconds the current call has been running; 0 when none is)."""
        with self._lock:
            working = time.monotonic() - self._call_began if self._call_began is not None else 0.0
            return self.calls_started, self.calls_done, working


_current: contextvars.ContextVar[Progress | None] = contextvars.ContextVar("progress", default=None)


@contextlib.contextmanager
def tracking(progress: Progress) -> Iterator[None]:
    """Model calls made inside this block, on this thread, are counted on `progress`."""
    token = _current.set(progress)
    try:
        yield
    finally:
        _current.reset(token)


def call_started() -> None:
    p = _current.get()
    if p is not None:
        p.call_started()


def call_finished() -> None:
    p = _current.get()
    if p is not None:
        p.call_finished()
