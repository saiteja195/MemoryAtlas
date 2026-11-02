import pytest
from fastapi.testclient import TestClient

from app import db
from app.llm.base import LLMUnavailable
from app.llm.replay import RecordReplayClient


class FakeInner:
    mode = "live"

    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user, schema):
        self.calls += 1
        return {"echo": user}


def test_schema_loads_and_enforces_zero_media():
    conn = db.connect()
    conn.execute("INSERT INTO sources(source_id, kind, captured_at, ingested_at, content_hash)"
                 " VALUES ('s1', 'frame_observation', 't', 't', 'h')")
    with pytest.raises(Exception):
        conn.execute("UPDATE sources SET media_bytes_retained = 5 WHERE source_id = 's1'")


def test_source_justification_requires_source_id():
    conn = db.connect()
    conn.execute("INSERT INTO entities VALUES ('e1', 'person', 'Alex', NULL)")
    conn.execute("INSERT INTO claims VALUES ('c1','e1','said',NULL,'x',NULL,NULL,NULL,"
                 "'direct_observation',0.9,NULL,'x','active',NULL,'t')")
    with pytest.raises(Exception):
        conn.execute("INSERT INTO justifications VALUES ('j1','c1','source',NULL,NULL)")


def test_record_then_replay(tmp_path):
    inner = FakeInner()
    rec = RecordReplayClient(str(tmp_path), "record", inner)
    assert rec.complete_json("s", "hi", {}) == {"echo": "hi"}
    rep = RecordReplayClient(str(tmp_path), "replay")
    assert rep.complete_json("s", "hi", {}) == {"echo": "hi"}
    assert inner.calls == 1


def test_replay_miss_raises_instead_of_guessing(tmp_path):
    with pytest.raises(LLMUnavailable):
        RecordReplayClient(str(tmp_path), "replay").complete_json("s", "unseen", {})


def test_health_reports_llm_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORYATLAS_DB", ":memory:")
    monkeypatch.setenv("MEMORYATLAS_CACHE_DIR", str(tmp_path))
    from app.main import app
    body = TestClient(app).get("/health").json()
    assert body == {"status": "ok", "llm_mode": "replay"}
