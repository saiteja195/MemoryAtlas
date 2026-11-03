"""Sign-up, sign-in, sign-out and the signed-in profile's own settings."""
import shutil

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import Settings
from .limits import RateLimiter
from .registry import (SESSION_SECONDS, BadCredentials, Locked, NameTaken, Profile, Registry,
                       TooManyProfiles)
from .runtime import Runtimes
from .session import COOKIE, current_profile

LOCAL = {"profile_id": "local", "name": "Local", "goals": [], "onboarded": True, "demo_kind": None}


class SignUpBody(BaseModel):
    name: str = Field(max_length=200)
    passcode: str = Field(max_length=1000)
    goals: list[str] = Field(default_factory=list, max_length=10)


class SignInBody(BaseModel):
    name: str = Field(max_length=200)
    passcode: str = Field(max_length=1000)


class GoalsBody(BaseModel):
    goals: list[str] = Field(max_length=10)


class DeleteBody(BaseModel):
    passcode: str = Field(max_length=1000)


def profile_json(p: Profile) -> dict:
    return {"profile_id": p.profile_id, "name": p.name, "goals": p.goals, "onboarded": p.onboarded,
            "demo_kind": p.demo_kind}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    return first or (request.client.host if request.client else "unknown")


def _is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", "").lower() == "https" or request.url.scheme == "https"


def make_router(settings: Settings, registry: Registry | None, runtimes: Runtimes) -> APIRouter:
    router = APIRouter(prefix="/auth")
    signups = RateLimiter(5, 3600)
    signins = RateLimiter(20, 600)

    def limited(limiter: RateLimiter, request: Request) -> None:
        key = client_ip(request)
        if not limiter.allow(key):
            wait = max(1, int(limiter.retry_after(key)) + 1)
            raise HTTPException(429, "Too many attempts. Try again later.", headers={"Retry-After": str(wait)})

    def start(response: Response, request: Request, profile: Profile) -> None:
        token = registry.start_session(profile.profile_id)          # type: ignore[union-attr]
        response.set_cookie(COOKIE, token, max_age=int(SESSION_SECONDS), httponly=True, samesite="lax",
                            secure=_is_https(request), path="/")

    def require_registry() -> Registry:
        if registry is None:
            raise HTTPException(404, "Profiles are switched off in this app")
        return registry

    @router.post("/signup", status_code=201)
    def signup(body: SignUpBody, request: Request, response: Response) -> dict:
        reg = require_registry()
        limited(signups, request)
        try:
            profile = reg.create(body.name, body.passcode, goals=body.goals)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except NameTaken:
            raise HTTPException(409, "That name is taken. Pick another, or sign in.") from None
        except TooManyProfiles:
            raise HTTPException(503, "This app has reached its profile limit.") from None
        start(response, request, profile)
        return {"profile": profile_json(profile)}

    @router.post("/signin")
    def signin(body: SignInBody, request: Request, response: Response) -> dict:
        reg = require_registry()
        limited(signins, request)
        try:
            profile = reg.authenticate(body.name, body.passcode)
        except BadCredentials as e:
            raise HTTPException(401, str(e)) from None
        except Locked as e:
            raise HTTPException(423, str(e), headers={"Retry-After": str(int(e.retry_after) + 1)}) from None
        start(response, request, profile)
        return {"profile": profile_json(profile)}

    @router.post("/signout", status_code=204)
    def signout(request: Request, response: Response) -> Response:
        if registry is not None:
            registry.end_session(request.cookies.get(COOKIE, ""))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    @router.get("/me")
    def me(request: Request) -> dict:
        if registry is None:
            return {"auth": False, "profile": LOCAL}
        return {"auth": True, "profile": profile_json(current_profile(request, registry))}

    @router.post("/goals")
    def goals(body: GoalsBody, request: Request) -> dict:
        if registry is None:
            return {"auth": False, "profile": LOCAL}
        profile = current_profile(request, registry)
        try:
            registry.set_goals(profile.profile_id, body.goals)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return {"auth": True, "profile": profile_json(registry.get(profile.profile_id))}   # type: ignore[arg-type]

    @router.post("/consent")
    def consent(request: Request) -> dict:
        if registry is None:
            return {"auth": False, "profile": LOCAL}
        profile = current_profile(request, registry)
        registry.accept_consent(profile.profile_id)
        return {"auth": True, "profile": profile_json(registry.get(profile.profile_id))}   # type: ignore[arg-type]

    @router.delete("/me", status_code=204)
    def delete_me(body: DeleteBody, request: Request) -> Response:
        reg = require_registry()
        profile = current_profile(request, reg)
        if profile.demo_kind:
            raise HTTPException(403, "A demo profile cannot be deleted. Use Settings to reset it.")
        limited(signins, request)
        try:
            checked = reg.authenticate(profile.name, body.passcode)
        except BadCredentials as e:
            raise HTTPException(401, str(e)) from None
        except Locked as e:
            raise HTTPException(423, str(e), headers={"Retry-After": str(int(e.retry_after) + 1)}) from None
        if checked.profile_id != profile.profile_id:
            raise HTTPException(401, "Wrong name or passcode")
        runtimes.forget(profile.profile_id)        # a late request can no longer rebuild it
        reg.delete(profile.profile_id)
        shutil.rmtree(runtimes.profile_dir(profile.profile_id), ignore_errors=True)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    return router
