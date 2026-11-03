"""Turns a request into the runtime of the profile it belongs to."""
from fastapi import HTTPException, Request

from .registry import Registry
from .runtime import ProfileRuntime, Runtimes

COOKIE = "ma_session"


def resolve_runtime(request: Request, registry: Registry, runtimes: Runtimes) -> ProfileRuntime:
    raise HTTPException(401, "Sign in to continue")        # replaced in the next step
