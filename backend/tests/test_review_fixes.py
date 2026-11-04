"""Regression tests for the whole-branch review of the profiles work."""
import shutil
import threading

import pytest

from app.profiles import registry as reg, snapshots
from app.profiles.registry import BadCredentials, Locked, Registry
from app.profiles.runtime import ProfileGone, Runtimes

from .fakes import FakeLLM
from .test_profiles_api import make_app, new_client, signin, signup
from .test_profiles_demo import build_snapshot, make_demo, pid_of, sources
from .test_profiles_registry import Clock


# -- C1: a published demo profile cannot be deleted ---------------------------------------------------
def test_a_demo_profile_cannot_be_deleted(tmp_path):
    app = make_app(tmp_path)
    c = make_demo(app)
    r = c.request("DELETE", "/auth/me", json={"passcode": "published-pass"})
    assert r.status_code == 403
    assert signin(new_client(app), "Demo Staged", "published-pass").status_code == 200
    assert signup(new_client(app), "Demo Staged", "squatter-pass").status_code == 409


# -- I1: a request during a demo reset must not cache a stale runtime ----------------------------------
def test_a_request_during_a_reset_does_not_leave_a_stale_runtime(tmp_path, monkeypatch):
    snap = build_snapshot(tmp_path)
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: snap)
    app = make_app(tmp_path)
    c = make_demo(app)
    pid = pid_of(c)
    runtimes = app.state.runtimes
    c.get("/graph")
    c.post("/demo/reset")
    snap_sources = sources(app, pid)
    c.post("/demo/advance", params={"steps": 1})               # no-op on a played day; keeps the cache warm

    racers: list[threading.Thread] = []
    order: list[str] = []
    real_copy = shutil.copyfile

    def copy_with_a_racing_request(src, dst):
        def visitor():
            runtimes.get(pid, "x", False)                        # another visitor arrives mid-reset
            order.append("rebuilt")
        t = threading.Thread(target=visitor)
        t.start()
        racers.append(t)
        t.join(0.3)                                             # it must wait for the swap, not rebuild on the old file
        out = real_copy(src, dst)
        order.append("copied")
        return out

    monkeypatch.setattr(shutil, "copyfile", copy_with_a_racing_request)
    assert c.post("/demo/reset").status_code == 200
    for t in racers:
        t.join(5)
    fresh = runtimes.get(pid, "x", False)
    assert order == ["copied", "rebuilt"]                       # the visitor's runtime was built after the swap
    assert sources(app, pid) == snap_sources
    # What the cached runtime writes must land in the file on disk (a runtime on a replaced file writes into the void).
    fresh.conn.execute("INSERT INTO entities(entity_id, type, name) VALUES ('zz','person','Marker')")
    fresh.conn.commit()
    import sqlite3
    on_disk = sqlite3.connect(fresh.db_path)
    assert on_disk.execute("SELECT COUNT(*) FROM entities WHERE name='Marker'").fetchone()[0] == 1
    on_disk.close()


# -- M4 (graded Important): a request in flight cannot bring a deleted profile back ---------------------
def test_a_deleted_profile_cannot_be_rebuilt_by_a_late_request(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    pid = signup(c).json()["profile"]["profile_id"]
    c.get("/graph")
    runtimes = app.state.runtimes
    folder = runtimes.profile_dir(pid)
    assert c.request("DELETE", "/auth/me", json={"passcode": "analytical-engine"}).status_code == 204
    with pytest.raises(ProfileGone):
        runtimes.get(pid, "Ada", False)                         # the late request that already passed its session check
    import os
    assert not os.path.exists(folder)


# -- I3: lockout holds against parallel guesses, and a locked profile costs one hash like an unknown one ----
def test_a_correct_guess_in_flight_when_the_lock_lands_is_refused(monkeypatch):
    clock = Clock()
    r = Registry(":memory:", clock=clock)
    r.create("Sai Teja", "secret-pass")
    real_verify = reg.verify_passcode
    state = {"nested": False}

    def verify_while_others_guess(passcode, salt, digest):
        ok = real_verify(passcode, salt, digest)
        if not state["nested"]:
            state["nested"] = True                              # four more guesses finish while this one hashes
            for _ in range(4):
                with pytest.raises(BadCredentials):
                    r.authenticate("Sai Teja", "nope-nope")
        return ok

    monkeypatch.setattr(reg, "verify_passcode", verify_while_others_guess)
    with pytest.raises(Locked):
        r.authenticate("Sai Teja", "secret-pass")
    monkeypatch.setattr(reg, "verify_passcode", real_verify)


def test_the_fifth_attempt_can_still_succeed():
    r = Registry(":memory:", clock=Clock())
    r.create("Sai Teja", "secret-pass")
    for _ in range(4):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    assert r.authenticate("Sai Teja", "secret-pass").name == "Sai Teja"


def test_a_locked_real_profile_still_burns_a_hash(monkeypatch):
    r = Registry(":memory:", clock=Clock())
    r.create("Sai Teja", "secret-pass")
    for _ in range(5):
        with pytest.raises(BadCredentials):
            r.authenticate("Sai Teja", "nope-nope")
    calls = []
    monkeypatch.setattr(reg, "burn_hash", lambda p: calls.append(p))
    with pytest.raises(Locked):
        r.authenticate("Sai Teja", "secret-pass")
    assert calls == ["secret-pass"]


# -- I2: model-calling routes are limited, so open sign-up cannot spend the owner's key --------------------
def test_model_routes_are_limited_per_profile(tmp_path):
    from app.profiles.limits import RateLimiter
    app = make_app(tmp_path)
    app.state.budget.per_profile = RateLimiter(2, 3600)
    a, b = new_client(app), new_client(app)
    signup(a, "Profile Aaa", "passcode-aaa")
    signup(b, "Profile Bbb", "passcode-bbb")
    fake = app.state.runtimes.get(pid_of(a), "x", False).llm._inner
    fake.recall_replies[:] = [{"action": "final", "status": "abstained", "answer": "No record.",
                               "cited_claim_ids": [], "uncertainty_note": ""}] * 6
    ask = lambda c: c.post("/recall/ask", json={"question": "Where did I eat?"})
    assert [ask(a).status_code for _ in range(3)] == [200, 200, 429]
    assert "retry-after" in ask(a).headers
    assert ask(b).status_code == 200                            # another profile has its own allowance
    assert a.post("/demo/load-sample").status_code == 429       # every model route shares the allowance
    assert a.get("/graph").status_code == 200                   # reads are free


def test_model_routes_are_limited_per_address_and_demo_profiles_share_only_that(tmp_path):
    from app.profiles.limits import RateLimiter
    app = make_app(tmp_path)
    app.state.budget.per_profile = RateLimiter(1, 3600)
    app.state.budget.per_ip = RateLimiter(3, 3600)
    demo = make_demo(app)
    fake = app.state.runtimes.get(pid_of(demo), "x", False).llm._inner
    fake.recall_replies[:] = [{"action": "final", "status": "abstained", "answer": "No record.",
                               "cited_claim_ids": [], "uncertainty_note": ""}] * 6
    ask = lambda: demo.post("/recall/ask", json={"question": "Where did I eat?"})
    assert [ask().status_code for _ in range(4)] == [200, 200, 200, 429]    # not the per-profile cap of 1
