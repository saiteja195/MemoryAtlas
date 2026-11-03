"""Turns a request into the profile, and the runtime, it belongs to."""
from fastapi import HTTPException, Request

from .registry import Profile, Registry
from .runtime import ProfileRuntime, Runtimes

COOKIE = "ma_session"


def current_profile(request: Request, registry: Registry) -> Profile:
    profile = registry.profile_for_token(request.cookies.get(COOKIE, ""))
    if profile is None:
        raise HTTPException(401, "Sign in to continue")
    return profile


def resolve_runtime(request: Request, registry: Registry, runtimes: Runtimes) -> ProfileRuntime:
    """Only a valid session reaches a runtime; a deleted or expired one stops here and creates nothing."""
    profile = current_profile(request, registry)
    return runtimes.get(profile.profile_id, profile.name, False)
