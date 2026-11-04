"""Bounded, profile-scoped background work. Inputs and results stay in RAM, never raw-media files.

Jobs survive browser navigation, not a server restart. Preview results expire with their drafts.
Independent read/preview lanes may run together; one save per profile protects the existing compiler.
"""
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import HTTPException

from .llm.base import LLMUnavailable
from .progress import Progress, tracking

log = logging.getLogger("memoryatlas")
KEEP_FINISHED_S = 3600.0


class Busy(Exception):
    """The profile lane or the server's bounded work capacity is full."""


@dataclass
class Job:
    job_id: str
    profile_id: str
    kind: str = "save"
    lane: str = "write"
    state: str = "queued"
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    progress: Progress = field(default_factory=Progress)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    generation: int = 0


class JobBoard:
    def __init__(self, workers: int = 4, capacity: int = 16) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="memory-job")
        self._capacity = capacity
        self._generation: dict[str, int] = {}

    def busy(self, profile_id: str, lane: str | None = "write") -> bool:
        with self._lock:
            return any(j.profile_id == profile_id and j.state in ("queued", "running")
                       and (lane is None or j.lane == lane) for j in self._jobs.values())

    def start(self, profile_id: str, work: Callable[[], dict[str, Any]], *,
              kind: str = "save", lane: str = "write") -> Job:
        with self._lock:
            self._forget_old()
            if self.busy(profile_id, lane) or sum(j.state in ("queued", "running") for j in self._jobs.values()) >= self._capacity:
                raise Busy(profile_id)
            job = Job(uuid.uuid4().hex, profile_id, kind=kind, lane=lane,
                      generation=self._generation.get(profile_id, 0))
            self._jobs[job.job_id] = job
            self._pool.submit(self._run, job, work)
            return job

    def get(self, profile_id: str, job_id: str) -> Job | None:
        with self._lock:
            self._forget_old()
            job = self._jobs.get(job_id)
            return job if job is not None and job.profile_id == profile_id else None

    def list(self, profile_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._forget_old()
            return [self.status(j) for j in self._jobs.values() if j.profile_id == profile_id]

    def dismiss(self, profile_id: str, job_id: str) -> None:
        with self._lock:
            job = self.get(profile_id, job_id)
            if job and job.state not in ("queued", "running"):
                self._jobs.pop(job_id, None)

    def consume_preview(self, profile_id: str, draft_id: str) -> None:
        with self._lock:
            for job in list(self._jobs.values()):
                if job.profile_id == profile_id and job.kind == "preview" and job.result and job.result.get("draft_id") == draft_id:
                    self._jobs.pop(job.job_id, None)

    def invalidate(self, profile_id: str) -> None:
        """A privacy change must also forget job copies and prevent late results being published."""
        with self._lock:
            self._generation[profile_id] = self._generation.get(profile_id, 0) + 1
            for job in list(self._jobs.values()):
                if job.profile_id == profile_id:
                    job.result = None
                    if job.state in ("queued", "running"):
                        job.error = {"status": 409, "message": "Memories or permissions changed. Start again."}
                        job.state = "error"
                    else:
                        self._jobs.pop(job.job_id, None)

    @staticmethod
    def status(job: Job) -> dict[str, Any]:
        started, done, working = job.progress.snapshot()
        end = job.finished if job.finished is not None else time.monotonic()
        return {"job_id": job.job_id, "kind": job.kind, "state": job.state,
                "elapsed_s": round(end - job.started, 1), "calls_started": started,
                "calls_done": done, "working_s": round(working, 1), "result": job.result, "error": job.error}

    def _forget_old(self) -> None:
        now = time.monotonic()
        for jid in [j.job_id for j in self._jobs.values() if j.finished is not None
                    and now - j.finished > (900 if j.kind == "preview" else KEEP_FINISHED_S)]:
            del self._jobs[jid]

    def _run(self, job: Job, work: Callable[[], dict[str, Any]]) -> None:
        with self._lock:
            if job.state == "error":
                return
            job.state = "running"
        try:
            with tracking(job.progress):
                result = work()
            with self._lock:
                if job.generation == self._generation.get(job.profile_id, 0):
                    job.result, job.state = result, "done"
        except (LLMUnavailable, HTTPException) as e:
            with self._lock:
                job.error = {"status": e.status_code if isinstance(e, HTTPException) else 503,
                             "message": str(e.detail) if isinstance(e, HTTPException) else str(e)}
                job.state = "error"
        except Exception:
            log.exception("background processing failed")
            with self._lock:
                job.error, job.state = {"status": 500, "message": "Processing failed. Please try again."}, "error"
        finally:
            job.finished = time.monotonic()
