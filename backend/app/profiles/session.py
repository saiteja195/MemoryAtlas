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


def open_runtime(profile: Profile, runtimes: Runtimes) -> ProfileRuntime:
    """The profile's runtime. A demo profile's runtime is prepared once: its database came from a snapshot,
    which holds no revocation tokens and no record of which events were played."""
    rt = runtimes.get(profile.profile_id, profile.name, False)
    if profile.demo_kind and not rt.demo_ready:
        rt.demo_ready = True
        if rt.conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
            rt.demo.rekey()
            rt.demo.mark_all_played()
    return rt


def resolve_runtime(request: Request, registry: Registry, runtimes: Runtimes) -> ProfileRuntime:
    """Only a valid session reaches a runtime; a deleted or expired one stops here and creates nothing."""
    return open_runtime(current_profile(request, registry), runtimes)
