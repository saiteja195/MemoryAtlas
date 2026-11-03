import os

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.profiles import snapshots
from app.profiles.runtime import Runtimes

from .fakes import FakeLLM
from .test_profiles_api import add_note, new_client, signin, signup


def make_app(tmp_path, llm=None):
    s = Settings(db_path=str(tmp_path / "x.db"), llm_mode="live", cache_dir=str(tmp_path / "seed"), auth=True)
    return create_app(s, llm or FakeLLM())


def build_snapshot(tmp_path, steps=2) -> str:
    """A tiny demo snapshot: the first events of the staged day, saved the way seed_profiles will."""
    s = Settings(db_path=str(tmp_path / "x.db"), llm_mode="live", cache_dir=str(tmp_path / "seed"), auth=True)
    rts = Runtimes(s, FakeLLM(), str(tmp_path / "build"))
    rt = rts.get("snapsnapsnap", "Snap", True)
    rt.demo.advance(steps)
    out = str(tmp_path / "snap.db")
    rt.conn.execute("VACUUM INTO ?", (out,))
    rts.close_all()
    return out


def make_demo(app, name="Demo Staged", kind="staged", passcode="published-pass"):
    app.state.registry.create(name, passcode, demo_kind=kind)
    c = new_client(app)
    assert signin(c, name, passcode).status_code == 200
    return c


def pid_of(c) -> str:
    return c.get("/auth/me").json()["profile"]["profile_id"]


def sources(app, pid) -> list[str]:
    rt = app.state.runtimes.get(pid, "x", False)
    return [r[0] for r in rt.conn.execute("SELECT text FROM sources ORDER BY captured_at")]


def test_new_profile_has_no_grants_and_no_memories(tmp_path):
    c = new_client(make_app(tmp_path))
    signup(c)
    assert c.get("/consent/grants").json() == []
    assert c.get("/graph").json()["nodes"] == []
    assert c.get("/demo/status").json()["cursor"] == 0


def test_load_sample_fills_an_empty_profile(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    signup(c)
    r = c.post("/demo/load-sample")
    assert r.status_code == 200 and r.json()["cursor"] == r.json()["total"] > 0
    assert c.get("/graph").json()["nodes"]
    rt = app.state.runtimes.get(pid_of(c), "x", False)
    assert rt.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] > 0


def test_load_sample_refuses_a_profile_with_memories(tmp_path):
    c = new_client(make_app(tmp_path))
    signup(c)
    assert c.post("/demo/load-sample").status_code == 200
    again = c.post("/demo/load-sample")
    assert again.status_code == 409 and again.json()["detail"] == "This profile already has memories"


def test_load_sample_refuses_after_a_note_was_added(tmp_path):
    c = new_client(make_app(tmp_path))
    signup(c)
    add_note(c, "Coffee at Blue Door Cafe", "2026-10-29T09:00:00")
    assert c.post("/demo/load-sample").status_code == 409


def test_load_sample_with_auth_off_is_advance(tmp_path):
    c = TestClient(create_app(Settings(db_path=":memory:", llm_mode="live", auth=False), FakeLLM()))
    assert c.post("/demo/load-sample").json()["cursor"] > 0


def test_reset_is_forbidden_for_a_normal_profile(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    signup(c)
    c.post("/demo/load-sample")
    before = c.get("/graph").json()
    r = c.post("/demo/reset")
    assert r.status_code == 403
    assert r.json()["detail"] == "Only demo profiles can be reset. Use Settings to delete your profile."
    assert c.get("/graph").json() == before


def test_reset_restores_a_demo_profile_snapshot(tmp_path, monkeypatch):
    snap = build_snapshot(tmp_path)
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: snap)
    app = make_app(tmp_path)
    c = make_demo(app)
    pid = pid_of(c)
    assert c.post("/demo/reset").status_code == 200
    restored = sources(app, pid)
    assert restored
    add_note(c, "A visitor wrote this note", "2026-10-29T20:00:00")
    assert "A visitor wrote this note" in sources(app, pid)
    assert c.post("/demo/reset").status_code == 200
    assert sources(app, pid) == restored and "A visitor wrote this note" not in sources(app, pid)


def test_restored_demo_profile_has_working_demo_tokens(tmp_path, monkeypatch):
    snap = build_snapshot(tmp_path)
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: snap)
    app = make_app(tmp_path)
    c = make_demo(app)
    c.post("/demo/reset")
    grants = c.get("/demo/grants").json()
    assert grants and all(g["demo_token"] for g in grants if not g["revoked_at"])
    g = grants[0]
    r = c.post(f"/consent/grants/{g['grant_id']}/revoke", json={"token": g["demo_token"]},
               params={"red_team": "false"})
    assert r.status_code == 200


def test_restored_demo_profile_does_not_replay_the_day(tmp_path, monkeypatch):
    snap = build_snapshot(tmp_path)
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: snap)
    app = make_app(tmp_path)
    c = make_demo(app)
    st = c.post("/demo/reset").json()
    assert st["cursor"] == st["total"] and all(e["played"] for e in st["events"])
    n = len(sources(app, pid_of(c)))
    assert c.post("/demo/advance", params={"steps": 5}).json()["played"] == []
    assert len(sources(app, pid_of(c))) == n


def test_reset_of_one_demo_profile_does_not_touch_another(tmp_path, monkeypatch):
    snap = build_snapshot(tmp_path)
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: snap)
    app = make_app(tmp_path)
    staged = make_demo(app, "Demo Staged", "staged")
    real = make_demo(app, "Demo Real", "real")
    staged.post("/demo/reset"), real.post("/demo/reset")
    add_note(real, "Only in the real profile", "2026-10-29T20:00:00")
    add_note(staged, "Only in the staged profile", "2026-10-29T20:30:00")
    staged.post("/demo/reset")
    assert "Only in the real profile" in sources(app, pid_of(real))
    assert "Only in the staged profile" not in sources(app, pid_of(staged))


def test_reset_after_the_runtime_was_cached_uses_a_fresh_connection(tmp_path, monkeypatch):
    snap = build_snapshot(tmp_path)
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: snap)
    app = make_app(tmp_path)
    c = make_demo(app)
    pid = pid_of(c)
    assert c.get("/graph").status_code == 200
    old = app.state.runtimes.get(pid, "x", False)
    assert c.post("/demo/reset").status_code == 200
    new = app.state.runtimes.get(pid, "x", False)
    assert new is not old and new.conn is not old.conn
    with pytest.raises(Exception):
        old.conn.execute("SELECT 1")                       # the stale connection was closed
    assert c.get("/graph").status_code == 200
    d = os.path.dirname(new.db_path)
    assert not any(f.endswith(".tmp") for f in os.listdir(d))        # no half-copied file left behind


def test_reset_missing_snapshot_for_real_kind_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: str(tmp_path / f"{kind}-missing.db"))
    app = make_app(tmp_path)
    c = make_demo(app, "Demo Real", "real")
    r = c.post("/demo/reset")
    assert r.status_code == 503 and "real" in r.json()["detail"]
    assert c.get("/graph").status_code == 200              # profile still usable


def test_reset_missing_snapshot_for_staged_falls_back_to_the_script(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "snapshot_path", lambda kind: str(tmp_path / f"{kind}-missing.db"))
    app = make_app(tmp_path)
    c = make_demo(app)
    r = c.post("/demo/reset")
    assert r.status_code == 200 and r.json()["cursor"] == 0
    assert c.post("/demo/advance", params={"steps": 2}).status_code == 200
