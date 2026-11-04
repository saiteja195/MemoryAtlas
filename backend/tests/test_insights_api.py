import json

import pytest

from app.insights.usage import usage_summary
from app import db

from .test_profiles_api import make_app, new_client, signup, signin, ip


def call(conn, n, *, at="2026-11-03T10:00:00", model="text-m", kind="text", purpose="other",
         memory_day=None, served="live", ms=100, ok=1, images=0, words_in=0, words_out=0, audio_ms=0):
    conn.execute(
        "INSERT INTO model_calls(call_id, at, model, kind, purpose, memory_day, served_from, duration_ms,"
        " ok, images, words_in, words_out, audio_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"c{n}", at, model, kind, purpose, memory_day, served, ms, ok, images, words_in, words_out,
         audio_ms))
    conn.commit()


def seed(conn):
    call(conn, 1, purpose="read_memory", memory_day="2026-10-29", ms=100, images=1, words_in=50,
         at="2026-11-01T09:00:00")
    call(conn, 2, purpose="read_memory", memory_day="2026-10-29", ms=300, kind="vision", images=1,
         words_in=30)
    call(conn, 3, purpose="answer", ms=200, words_in=20, served="cache")
    call(conn, 4, purpose="answer", memory_day=None, ms=600, words_in=10, ok=0)
    call(conn, 5, purpose="compile", model="asr-m", kind="asr", ms=900, audio_ms=90000, memory_day="2026-10-30")
    call(conn, 6, purpose="compile", model="asr-m", kind="asr", ms=100, audio_ms=48000, memory_day="2026-10-30")


def test_usage_summary_totals_and_split():
    conn = db.connect()
    seed(conn)
    u = usage_summary(conn, "2026-10-29")
    assert u["recorded"] is True and u["since"] == "2026-11-01T09:00:00"
    assert u["total"] == {"calls": 6, "live": 5, "cache": 1, "failed": 1, "reading": 2, "answering": 2,
                          "photos": 2, "words_read": 110, "audio_minutes": 2.3, "avg_ms": 400}
    assert u["day"] == {"calls": 2, "live": 2, "cache": 0, "failed": 0, "reading": 2, "answering": 0,
                        "photos": 2, "words_read": 80, "audio_minutes": 0.0, "avg_ms": 200}
    text, asr = u["models"]
    assert text == {"model": "text-m", "kind_label": "Reads and answers", "calls": 4, "photos": 2,
                    "words_read": 110, "audio_minutes": 0.0, "avg_ms": 333, "reading": 2,
                    "answering": 2, "cache": 1}
    assert asr["model"] == "asr-m" and asr["kind_label"] == "Transcribes" and asr["audio_minutes"] == 2.3
    assert asr["avg_ms"] == 500 and asr["calls"] == 2


def test_no_rows_means_not_recorded():
    u = usage_summary(db.connect(), "2026-10-29")
    zero = {"calls": 0, "live": 0, "cache": 0, "failed": 0, "reading": 0, "answering": 0, "photos": 0,
            "words_read": 0, "audio_minutes": 0.0, "avg_ms": 0}
    assert u == {"recorded": False, "since": None, "total": zero, "day": None, "models": []}


def test_day_bucket_uses_memory_day_not_call_time():
    conn = db.connect()
    call(conn, 1, at="2026-11-03T10:00:00", memory_day="2026-10-29", purpose="read_memory")
    call(conn, 2, at="2026-10-29T10:00:00", memory_day=None, purpose="answer")
    assert usage_summary(conn, "2026-10-29")["day"]["calls"] == 1
    assert usage_summary(conn, "2026-11-03")["day"] is None
    assert usage_summary(conn)["day"] is None


# -- route ---------------------------------------------------------------------------------------

def add_source(conn, sid, at):
    conn.execute("INSERT OR IGNORE INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes,"
                 " token_hash, granted_at) VALUES ('g1','me','capture_session','s',?, 'h', ?)",
                 (json.dumps(["personal_recall"]), at))
    conn.execute("INSERT INTO sources(source_id, kind, grant_id, captured_at, ingested_at, content_hash)"
                 " VALUES (?,?,?,?,?,?)", (sid, "frame_observation", "g1", at, at, sid))
    conn.commit()


def profile_rt(app, c):
    pid = c.get("/auth/me").json()["profile"]["profile_id"]
    return app.state.runtimes.get(pid, "x", False)


@pytest.fixture
def signed(tmp_path):
    app = make_app(tmp_path)
    c = new_client(app)
    assert signup(c).status_code == 201
    return app, c, profile_rt(app, c)


def test_insights_defaults_to_the_latest_day(signed):
    app, c, rt = signed
    add_source(rt.conn, "a", "2026-10-28T09:00:00")
    add_source(rt.conn, "b", "2026-10-29T12:30:00")
    body = c.get("/insights").json()
    assert body["day"] == "2026-10-29" and body["days"] == ["2026-10-28", "2026-10-29"]
    assert body["coverage"]["day"] == "2026-10-29" and body["coverage"]["covered_hours"] == 1
    assert body["coverage"]["busiest_hour"] == 12
    assert body["usage"]["recorded"] is False


def test_insights_with_a_chosen_day(signed):
    app, c, rt = signed
    add_source(rt.conn, "a", "2026-10-28T09:00:00")
    add_source(rt.conn, "b", "2026-10-29T12:30:00")
    call(rt.conn, 1, purpose="read_memory", memory_day="2026-10-28")
    body = c.get("/insights", params={"day": "2026-10-28"}).json()
    assert body["day"] == "2026-10-28" and body["coverage"]["busiest_hour"] == 9
    assert body["usage"]["day"]["calls"] == 1 and body["usage"]["total"]["calls"] == 1


def test_unknown_day_has_zero_coverage_and_bad_day_is_422(signed):
    app, c, rt = signed
    add_source(rt.conn, "a", "2026-10-28T09:00:00")
    r = c.get("/insights", params={"day": "2030-01-01"})
    assert r.status_code == 200
    assert r.json()["day"] == "2030-01-01" and r.json()["coverage"]["covered_hours"] == 0
    for bad in ["yesterday", "2026-13-01", "2026-1-1", "20261029", "2026-10-29T10:00", ""]:
        assert c.get("/insights", params={"day": bad}).status_code == 422, bad


def test_insights_requires_sign_in_and_is_private(tmp_path):
    app = make_app(tmp_path)
    assert new_client(app).get("/insights").status_code == 401
    a = new_client(app)
    signup(a, name="Ada Lovelace")
    call(profile_rt(app, a).conn, 1, purpose="answer")
    add_source(profile_rt(app, a).conn, "a", "2026-10-29T09:00:00")
    b = new_client(app)
    signup(b, name="Grace Hopper", passcode="cobol-forever")
    assert a.get("/insights").json()["usage"]["total"]["calls"] == 1
    other = b.get("/insights").json()
    assert other["usage"]["recorded"] is False and other["usage"]["total"]["calls"] == 0
    assert other["day"] is None and other["days"] == []


def test_insights_for_an_empty_profile(signed):
    app, c, rt = signed
    body = c.get("/insights").json()
    assert body["day"] is None and body["days"] == [] and body["coverage"] is None
    assert body["usage"]["recorded"] is False and body["usage"]["day"] is None


def test_a_todo_scan_counts_as_reading_not_answering():
    conn = db.connect()
    call(conn, 1, purpose="todo_scan", memory_day="2026-10-29")
    u = usage_summary(conn, "2026-10-29")
    assert u["total"]["reading"] == 1 and u["total"]["answering"] == 0
    assert u["day"]["reading"] == 1 and u["models"][0]["reading"] == 1
