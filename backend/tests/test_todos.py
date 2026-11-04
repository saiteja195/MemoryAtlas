"""To-dos: the owner's promises and the requests made of the owner, with done and dismiss."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import create_app
from app.capture.models import RawCapture
from app.config import Settings
from app.privacy.consent import create_grant
from app.todos import count_open, list_todos, set_todo_state

from .fakes import DEMO_RULES, FakeLLM, claim
from .test_profiles_api import ip, make_app, new_client, signup

PROMISE = claim("Me", "committed_to", value="send Sam the budget", text="I will send Sam the budget")
ASK = claim("Alex", "requested", "Me", object_type="person", value="review the draft",
            text="Alex asked me to review the draft")


def app_client():
    fake = FakeLLM(rules=DEMO_RULES + [("the budget", [PROMISE])])
    client = TestClient(create_app(Settings(auth=False, db_path=":memory:", llm_mode="replay"), fake))
    return client, fake


def add_owner_todos(client, fake):
    """The staged day (which holds Alex's own promise) plus one promise and one request for the owner."""
    client.post("/demo/advance", params={"steps": 50})
    engine, conn = client.app.state.engine, client.app.state.conn
    for person in ("me", "alex"):
        create_grant(conn, "secret", person, "talk")
    fake.todo_replies.append({"claims": [ASK]})
    turns = [{"turn_id": 1, "start_ms": 0, "end_ms": 500, "speaker": "B", "text": "Can you review the draft?"}]
    engine.ingest(RawCapture(kind="audio", session_id="talk", captured_at="2026-10-29T15:05:00", turns=turns,
                             participants=["alex"], speaker_map={"A": "me", "B": "alex"}))
    gid, token = create_grant(conn, "secret", "me", "jot")
    engine.ingest(RawCapture(kind="note", session_id="jot", captured_at="2026-10-29T16:40:00",
                             text="Remember: I will send Sam the budget"))
    return gid, token


def by_text(items):
    return {t["text"]: t for t in items}


def test_owner_promise_and_request_become_todos():
    client, fake = app_client()
    add_owner_todos(client, fake)
    items = client.get("/todos").json()
    got = by_text(items)
    assert set(got) == {"send Sam the budget", "review the draft"}
    promise, request = got["send Sam the budget"], got["review the draft"]
    assert promise["kind"] == "promise" and promise["who"] is None and promise["when"] == "16:40"
    assert promise["source_label"] == "note" and promise["state"] == "open"
    assert request["kind"] == "request" and request["who"] == "Alex" and request["when"] == "15:05"
    assert request["source_label"] == "conversation"
    for t in items:
        [cite] = t["citations"]
        assert cite["claim_id"] == t["claim_id"] and cite["supported_by"]
    assert client.get("/insights").json()["todos_open"] == 2


def test_other_peoples_promise_is_not_a_todo():
    client, fake = app_client()
    client.post("/demo/advance", params={"steps": 50})
    conn = client.app.state.conn
    promise = conn.execute("SELECT claim_id FROM claims WHERE predicate='committed_to'").fetchone()[0]
    assert client.get("/todos", params={"state": "all"}).json() == []
    assert client.post(f"/todos/{promise}", json={"state": "done"}).status_code == 404
    assert client.get("/insights").json()["todos_open"] == 0


def test_state_changes_and_filters():
    client, fake = app_client()
    add_owner_todos(client, fake)
    first, second = client.get("/todos").json()
    r = client.post(f"/todos/{first['claim_id']}", json={"state": "done"})
    assert r.status_code == 200 and r.json()["state"] == "done" and r.json()["claim_id"] == first["claim_id"]
    assert [t["claim_id"] for t in client.get("/todos").json()] == [second["claim_id"]]
    assert [t["claim_id"] for t in client.get("/todos", params={"state": "done"}).json()] == [first["claim_id"]]
    assert client.get("/todos", params={"state": "dismissed"}).json() == []
    assert len(client.get("/todos", params={"state": "all"}).json()) == 2
    assert client.get("/insights").json()["todos_open"] == 1
    client.post(f"/todos/{second['claim_id']}", json={"state": "dismissed"})
    assert [t["claim_id"] for t in client.get("/todos", params={"state": "dismissed"}).json()] == [second["claim_id"]]
    r = client.post(f"/todos/{first['claim_id']}", json={"state": "open"})
    assert r.json()["state"] == "open"
    assert [t["claim_id"] for t in client.get("/todos").json()] == [first["claim_id"]]
    assert client.get("/todos", params={"state": "done"}).json() == []


def test_bad_state_is_422():
    client, fake = app_client()
    add_owner_todos(client, fake)
    [first, _] = client.get("/todos").json()
    assert client.get("/todos", params={"state": "later"}).status_code == 422
    assert client.post(f"/todos/{first['claim_id']}", json={"state": "later"}).status_code == 422
    assert client.post(f"/todos/{first['claim_id']}", json={}).status_code == 422
    assert client.post("/todos/clm-nope", json={"state": "done"}).status_code == 404


def test_forgetting_removes_the_todo_and_its_state():
    client, fake = app_client()
    gid, token = add_owner_todos(client, fake)
    conn = client.app.state.conn
    note = by_text(client.get("/todos").json())["send Sam the budget"]["claim_id"]
    client.post(f"/todos/{note}", json={"state": "done"})
    assert conn.execute("SELECT COUNT(*) FROM todo_state WHERE claim_id=?", (note,)).fetchone()[0] == 1
    client.app.state.runtimes.get("local", "Local", True).revoker.secret = "secret"
    assert client.post(f"/consent/grants/{gid}/revoke", json={"token": token}, params={"red_team": False}
                       ).status_code == 200
    assert "send Sam the budget" not in by_text(client.get("/todos", params={"state": "all"}).json())
    assert conn.execute("SELECT COUNT(*) FROM todo_state WHERE claim_id=?", (note,)).fetchone()[0] == 0
    assert client.post(f"/todos/{note}", json={"state": "open"}).status_code == 404
    assert "review the draft" in by_text(client.get("/todos").json())      # the other grant stands


def test_an_expired_grant_hides_the_todo_even_before_the_purge():
    client, fake = app_client()
    add_owner_todos(client, fake)
    conn = client.app.state.conn
    conn.execute("UPDATE consent_grants SET revoked_at='t' WHERE scope_ref='jot'")
    conn.commit()
    assert "send Sam the budget" not in by_text(client.get("/todos", params={"state": "all"}).json())


def test_superseded_or_retracted_claim_drops_out():
    client, fake = app_client()
    add_owner_todos(client, fake)
    request = by_text(client.get("/todos").json())["review the draft"]
    client.post(f"/todos/{request['claim_id']}", json={"state": "done"})
    assert client.post(f"/claims/{request['claim_id']}/correct", json={"retract": True}).status_code == 200
    assert client.get("/todos", params={"state": "all"}).json().__len__() == 1
    assert client.get("/todos", params={"state": "done"}).json() == []
    assert client.post(f"/todos/{request['claim_id']}", json={"state": "open"}).status_code == 404


def test_todo_ids_are_private_to_a_profile(tmp_path):
    fake = FakeLLM(rules=[("the budget", [PROMISE])])
    app = make_app(tmp_path, fake)
    a, b = new_client(app), new_client(app)
    signup(a, name="Ada Lovelace")
    signup(b, name="Grace Hopper", passcode="cobol-forever")
    pid = a.get("/auth/me").json()["profile"]["profile_id"]
    rt = app.state.runtimes.get(pid, "x", False)
    create_grant(rt.conn, "secret", "me", "jot")
    rt.engine.ingest(RawCapture(kind="note", session_id="jot", captured_at="2026-10-29T16:40:00",
                                text="I will send Sam the budget"))
    [mine] = a.get("/todos").json()
    assert b.get("/todos", params={"state": "all"}).json() == []
    assert b.post(f"/todos/{mine['claim_id']}", json={"state": "done"}).status_code == 404
    assert a.get("/todos").json()[0]["state"] == "open"
    assert a.post(f"/todos/{mine['claim_id']}", json={"state": "done"}).status_code == 200
    assert new_client(app).get("/todos").status_code == 401


def test_the_text_falls_back_to_the_claim_wording():
    conn = db.connect()
    conn.execute("INSERT INTO entities(entity_id, type, name, attrs) VALUES ('me','person','Me','{}')")
    gid, _ = create_grant(conn, "secret", "me", "s")
    conn.execute("INSERT INTO sources(source_id, kind, grant_id, captured_at, ingested_at, content_hash)"
                 " VALUES ('src','user_confirmation',?,'2026-10-29T09:00:00','2026-10-29T09:00:00','h')", (gid,))
    conn.execute("INSERT INTO claims(claim_id, subject_id, predicate, event_time, evidence_type, confidence,"
                 " status, text, created_at) VALUES ('c1','me','committed_to','2026-10-29T09:00:00','direct_observation',"
                 " 0.9,'active','Me will call the bank','2026-10-29T09:00:00')")
    conn.execute("INSERT INTO justifications(justification_id, claim_id, kind, source_id) VALUES"
                 " ('j1','c1','source','src')")
    conn.commit()
    [t] = list_todos(conn, "me")
    assert t["text"] == "Me will call the bank" and t["who"] is None
    assert count_open(conn, "me") == 1
    with pytest.raises(KeyError):
        set_todo_state(conn, "nope", "done")
    with pytest.raises(ValueError):
        set_todo_state(conn, "c1", "later")


def test_db_reset_clears_todo_state():
    conn = db.connect()
    conn.execute("INSERT INTO todo_state(claim_id, state, updated_at) VALUES ('c','done','t')")
    conn.commit()
    db.reset(conn)
    assert conn.execute("SELECT COUNT(*) FROM todo_state").fetchone()[0] == 0
