import itertools
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

from .fakes import FakeLLM

_ips = itertools.count(1)


def make_app(tmp_path, llm=None, **kw):
    s = Settings(db_path=str(tmp_path / "x.db"), llm_mode="live", cache_dir=str(tmp_path / "seed"),
                 auth=True, **kw)
    return create_app(s, llm or FakeLLM())


def new_client(app) -> TestClient:
    return TestClient(app)


def ip() -> dict:
    return {"X-Forwarded-For": f"10.1.0.{next(_ips)}"}


def signup(c, name="Ada Lovelace", passcode="analytical-engine", headers=None, **extra):
    return c.post("/auth/signup", json={"name": name, "passcode": passcode, **extra},
                  headers=headers or ip())


def signin(c, name="Ada Lovelace", passcode="analytical-engine", headers=None):
    return c.post("/auth/signin", json={"name": name, "passcode": passcode}, headers=headers or ip())


DATA_ROUTES = [("GET", "/graph"), ("GET", "/privacy/media"), ("GET", "/consent/grants"),
               ("GET", "/export"), ("GET", "/demo/status"), ("POST", "/recall/ask")]


@pytest.mark.parametrize("method,path", DATA_ROUTES)
def test_data_routes_need_a_session(tmp_path, method, path):
    c = new_client(make_app(tmp_path))
    r = c.request(method, path, json={"question": "where did I eat?"} if method == "POST" else None)
    assert r.status_code == 401


def test_health_is_public(tmp_path):
    c = new_client(make_app(tmp_path))
    assert c.get("/health").json()["auth"] is True


def test_signup_signs_in_and_me_returns_the_profile(tmp_path):
    c = new_client(make_app(tmp_path))
    r = signup(c, goals=["trips"])
    assert r.status_code == 201
    p = r.json()["profile"]
    assert p["name"] == "Ada Lovelace" and p["goals"] == ["trips"] and p["onboarded"] is False
    assert p["demo_kind"] is None and len(p["profile_id"]) == 12
    me = c.get("/auth/me").json()
    assert me["auth"] is True and me["profile"] == p
    assert c.get("/graph").status_code == 200


def test_me_without_a_session_is_401(tmp_path):
    assert new_client(make_app(tmp_path)).get("/auth/me").status_code == 401


def test_me_with_auth_off_is_the_local_profile(tmp_path):
    c = TestClient(create_app(Settings(db_path=":memory:", llm_mode="live", auth=False), FakeLLM()))
    assert c.get("/auth/me").json() == {"auth": False, "profile": {
        "profile_id": "local", "name": "Local", "goals": [], "onboarded": True, "demo_kind": None}}


def test_cookie_flags(tmp_path):
    c = new_client(make_app(tmp_path))
    plain = signup(c, "Plain Http").headers["set-cookie"].lower()
    assert "httponly" in plain and "samesite=lax" in plain and "secure" not in plain and "path=/" in plain
    secure = signup(c, "Over Https", headers={**ip(), "X-Forwarded-Proto": "https"}).headers["set-cookie"].lower()
    assert "secure" in secure and "httponly" in secure


def test_session_survives_across_requests_and_signout_ends_it(tmp_path):
    c = new_client(make_app(tmp_path))
    signup(c)
    assert c.get("/graph").status_code == 200 and c.get("/graph").status_code == 200
    assert c.post("/auth/signout").status_code == 204
    assert c.get("/graph").status_code == 401 and c.get("/auth/me").status_code == 401


def test_signin_after_signout(tmp_path):
    app = make_app(tmp_path)
    a = new_client(app)
    signup(a)
    a.post("/auth/signout")
    r = signin(a)
    assert r.status_code == 200 and r.json()["profile"]["name"] == "Ada Lovelace"
    assert a.get("/graph").status_code == 200


def test_unknown_name_and_wrong_passcode_look_identical(tmp_path):
    app = make_app(tmp_path)
    signup(new_client(app))
    c = new_client(app)
    unknown = signin(c, "Nobody Here", "analytical-engine")
    wrong = signin(c, "Ada Lovelace", "not-the-passcode")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "Wrong name or passcode"}
    assert "set-cookie" not in unknown.headers and "set-cookie" not in wrong.headers


def test_five_wrong_passcodes_return_423_even_for_the_right_one_then(tmp_path):
    app = make_app(tmp_path)
    signup(new_client(app))
    c = new_client(app)
    codes = [signin(c, passcode="wrong-wrong").status_code for _ in range(5)]
    assert codes == [401] * 5
    locked = signin(c)                                     # the right passcode is refused too
    assert locked.status_code == 423 and int(locked.headers["retry-after"]) > 800


def test_unknown_names_lock_after_five_tries_the_same_way(tmp_path):
    c = new_client(make_app(tmp_path))
    codes = [signin(c, "Nobody Here", "whatever-1").status_code for _ in range(6)]
    assert codes == [401] * 5 + [423]


def test_locking_profile_a_does_not_lock_b(tmp_path):
    app = make_app(tmp_path)
    signup(new_client(app), "Profile Aaa", "passcode-aaa")
    signup(new_client(app), "Profile Bbb", "passcode-bbb")
    c = new_client(app)
    for _ in range(5):
        signin(c, "Profile Aaa", "wrong-wrong")
    assert signin(c, "Profile Bbb", "passcode-bbb").status_code == 200


def test_signup_and_signin_are_rate_limited_per_ip(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    same = {"X-Forwarded-For": "203.0.113.9"}
    codes = [signup(c, f"Person {i:02d}", headers=same).status_code for i in range(6)]
    assert codes == [201] * 5 + [429]
    assert "retry-after" in signup(c, "Person 99", headers=same).headers
    assert signup(c, "Person 77", headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 201
    other = {"X-Forwarded-For": "198.51.100.4"}
    codes = [signin(c, "Person 00", "analytical-engine", headers=other).status_code for _ in range(21)]
    assert codes[-1] == 429


def test_duplicate_name_is_409_and_bad_input_is_422(tmp_path):
    c = new_client(make_app(tmp_path))
    signup(c)
    assert signup(c, "ada   LOVELACE").status_code == 409
    assert signup(c, "x").status_code == 422
    assert signup(c, "Short Code", "12345").status_code == 422


def test_profile_cap_is_503(tmp_path):
    app = make_app(tmp_path)
    app.state.registry.max_profiles = 1
    c = new_client(app)
    assert signup(c, "First One").status_code == 201
    assert signup(c, "Second One").status_code == 503


def test_invalid_goals_are_422(tmp_path):
    c = new_client(make_app(tmp_path))
    assert signup(c, goals=["world_domination"]).status_code == 422
    assert signup(c, goals=["trips"] * 6 + ["remember_day"]).status_code in (201, 422)
    ok = signup(c, "Goal Setter")
    assert ok.status_code == 201
    assert c.post("/auth/goals", json={"goals": ["nope"]}).status_code == 422
    assert c.post("/auth/goals", json={"goals": ["trips", "work_meetings"]}).status_code == 200
    assert c.get("/auth/me").json()["profile"]["goals"] == ["trips", "work_meetings"]


def test_consent_marks_the_profile_onboarded(tmp_path):
    c = new_client(make_app(tmp_path))
    signup(c)
    assert c.get("/auth/me").json()["profile"]["onboarded"] is False
    assert c.post("/auth/consent").status_code == 200
    assert c.get("/auth/me").json()["profile"]["onboarded"] is True


def test_goals_and_consent_need_a_session(tmp_path):
    c = new_client(make_app(tmp_path))
    assert c.post("/auth/goals", json={"goals": []}).status_code == 401
    assert c.post("/auth/consent").status_code == 401


def test_delete_needs_the_passcode_and_removes_everything(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    pid = signup(c).json()["profile"]["profile_id"]
    assert c.get("/graph").status_code == 200                 # builds the runtime and its files
    folder = Path(app.state.runtimes.profile_dir(pid))
    assert (folder / "memoryatlas.db").exists()
    assert c.request("DELETE", "/auth/me", json={"passcode": "wrong-wrong"}).status_code == 401
    assert c.get("/graph").status_code == 200                 # still signed in, still there
    assert c.request("DELETE", "/auth/me", json={"passcode": "analytical-engine"}).status_code == 204
    assert not folder.exists()                                # database, WAL files and cache all gone
    assert c.get("/graph").status_code == 401 and c.get("/auth/me").status_code == 401
    assert not folder.exists()                                # the old cookie recreated nothing
    assert signup(c).status_code == 201                       # the name can be used again


def test_delete_with_another_profiles_cookie_cannot_delete_it(tmp_path):
    app = make_app(tmp_path)
    a, b = new_client(app), new_client(app)
    signup(a, "Profile Aaa", "passcode-aaa")
    signup(b, "Profile Bbb", "passcode-bbb")
    r = b.request("DELETE", "/auth/me", json={"passcode": "passcode-aaa"})
    assert r.status_code == 401
    assert signin(new_client(app), "Profile Aaa", "passcode-aaa").status_code == 200


def test_expired_session_cookie_gets_401(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    signup(c)
    app.state.registry.conn.execute("UPDATE sessions SET expires_at = 0")
    app.state.registry.conn.commit()
    assert c.get("/graph").status_code == 401 and c.get("/auth/me").status_code == 401


def test_a_forged_cookie_is_401(tmp_path):
    c = new_client(make_app(tmp_path))
    c.cookies.set("ma_session", "not-a-real-token")
    assert c.get("/graph").status_code == 401


# -- isolation ----------------------------------------------------------------------------------

def add_note(c, text, when):
    d = c.post("/capture/preview", json={"kind": "note", "text": text, "file_modified_at": when}).json()
    r = c.post("/capture/commit", json={"draft_id": d["draft_id"], "answers": {}})
    assert r.status_code == 200, r.text
    return d["draft_id"], r.json()


def test_isolation(tmp_path):
    app = make_app(tmp_path)
    a, b = new_client(app), new_client(app)
    a_id = signup(a, "Profile Aaa", "passcode-aaa").json()["profile"]["profile_id"]
    b_id = signup(b, "Profile Bbb", "passcode-bbb").json()["profile"]["profile_id"]

    add_note(a, "Coffee at Blue Door Cafe, secret-marker-aaa", "2026-10-29T09:00:00")
    _, second = add_note(a, "Lunch at Orbit Fitness canteen", "2026-10-30T12:00:00")
    a_rt = app.state.runtimes.get(a_id, "Profile Aaa", False)
    claim_id = a_rt.conn.execute("SELECT claim_id FROM claims LIMIT 1").fetchone()[0]
    grant = second["grants"][0]
    receipt_id = a.post(f"/consent/grants/{grant['grant_id']}/revoke",
                        json={"token": grant["revocation_token"]}, params={"red_team": "false"}).json()["receipt_id"]
    draft_for_b = a.post("/capture/preview", json={"kind": "note", "text": "a pending draft",
                                                   "file_modified_at": "2026-10-31T10:00:00"}).json()["draft_id"]
    first_grant = a.get("/consent/grants").json()[0]["grant_id"]

    assert a.get("/graph").json()["nodes"] and a.get(f"/claims/{claim_id}/provenance").status_code == 200
    assert a.get(f"/receipts/{receipt_id}").status_code == 200

    assert b.get("/graph").json()["nodes"] == []
    assert "secret-marker-aaa" not in b.get("/export").text
    assert b.get("/consent/grants").json() == []
    assert b.get(f"/claims/{claim_id}/provenance").status_code == 404
    assert b.post(f"/claims/{claim_id}/correct", json={"retract": True}).status_code == 404
    assert b.get(f"/receipts/{receipt_id}").status_code == 404
    assert b.post(f"/consent/grants/{first_grant}/revoke",
                  json={"token": grant["revocation_token"]}).status_code == 404
    assert b.post("/capture/commit", json={"draft_id": draft_for_b, "answers": {}}).status_code == 404
    b_rt = app.state.runtimes.get(b_id, "Profile Bbb", False)
    b_rt.llm._inner.recall_replies[:] = [
        {"action": "tool", "tool": "search_claims", "args": {"query": "coffee"}},
        {"action": "final", "status": "abstained", "answer": "I have no memory of that.",
         "cited_claim_ids": [], "uncertainty_note": ""}]
    asked = b.post("/recall/ask", json={"question": "Where did I have coffee?"})
    assert asked.status_code == 200
    assert "secret-marker-aaa" not in asked.text and "Blue Door" not in asked.text
    assert b_rt.llm._inner.recall_payloads and all("Blue Door" not in str(p) for p in b_rt.llm._inner.recall_payloads)

    assert a.get(f"/claims/{claim_id}/provenance").status_code == 200       # A is untouched
    assert a.post("/capture/commit", json={"draft_id": draft_for_b, "answers": {}}).status_code == 200


def test_uploads_still_need_live_mode(tmp_path):
    class Recording(FakeLLM):
        mode = "record"
    app = make_app(tmp_path, Recording())
    c = new_client(app)
    signup(c)
    r = c.post("/capture/preview", json={"kind": "note", "text": "hello there"})
    assert r.status_code == 409
