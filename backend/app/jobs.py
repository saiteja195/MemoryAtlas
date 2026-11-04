"""Background saves. A slow model must never hold a web request open (the proxy gives up after a few minutes), so
saving a memory starts a job and returns at once; the page polls `status` until it is done. Jobs live in memory,
belong to one profile, allow one running job per profile, and are forgotten an hour after they finish."""
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import HTTPException

from .llm.base import LLMUnavailable
from .progress import Progress, tracking

log = logging.getLogger("memoryatlas")
KEEP_FINISHED_S = 3600.0


class Busy(Exception):
    """This profile already has a save running."""


@dataclass
class Job:
    job_id: str
    profile_id: str
    state: str = "running"                   # running | done | error
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    progress: Progress = field(default_factory=Progress)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class JobBoard:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def busy(self, profile_id: str) -> bool:
        with self._lock:
            return any(j.profile_id == profile_id and j.state == "running" for j in self._jobs.values())

    def start(self, profile_id: str, work: Callable[[], dict[str, Any]]) -> Job:
        with self._lock:
            self._forget_old()
            if any(j.profile_id == profile_id and j.state == "running" for j in self._jobs.values()):
                raise Busy(profile_id)
            job = Job(uuid.uuid4().hex, profile_id)
            self._jobs[job.job_id] = job
        threading.Thread(target=self._run, args=(job, work), daemon=True, name=f"save-{job.job_id[:6]}").start()
        return job

    def get(self, profile_id: str, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return job if job is not None and job.profile_id == profile_id else None

    @staticmethod
    def status(job: Job) -> dict[str, Any]:
        started, done, working = job.progress.snapshot()
        end = job.finished if job.finished is not None else time.monotonic()
        return {"job_id": job.job_id, "state": job.state, "elapsed_s": round(end - job.started, 1),
                "calls_started": started, "calls_done": done, "working_s": round(working, 1),
                "result": job.result, "error": job.error}

    def _forget_old(self) -> None:
        now = time.monotonic()
        for jid in [j.job_id for j in self._jobs.values()
                    if j.finished is not None and now - j.finished > KEEP_FINISHED_S]:
            del self._jobs[jid]

    @staticmethod
    def _run(job: Job, work: Callable[[], dict[str, Any]]) -> None:
        try:
            with tracking(job.progress):
                job.result = work()
            job.state = "done"
        except LLMUnavailable as e:
            job.error, job.state = {"status": 503, "message": str(e)}, "error"
        except HTTPException as e:
            job.error, job.state = {"status": e.status_code, "message": str(e.detail)}, "error"
        except Exception:  # noqa: BLE001  the person gets a plain message; the details go to the server log
            log.exception("background save failed")
            job.error, job.state = {"status": 500, "message": "Saving failed unexpectedly. Please try again."}, "error"
        finally:
            job.finished = time.monotonic()
