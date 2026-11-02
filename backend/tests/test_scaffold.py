import json
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


def test_health_reports_llm_mode(tmp_path):
    # Built explicitly: importing app.main would create a database file in the working directory.
    from app.api import create_app
    from app.config import Settings
    app = create_app(Settings(db_path=":memory:", llm_mode="replay", cache_dir=str(tmp_path)))
    assert TestClient(app).get("/health").json() == {"status": "ok", "llm_mode": "replay"}


def test_record_mode_returns_exactly_what_replay_will(tmp_path):
    """Key order must not differ between modes: callers serialise results into later prompts."""
    class Unordered:
        mode = "live"

        def complete_json(self, system, user, schema):
            return {"z": 1, "a": {"y": 2, "b": 3}}

    rec = RecordReplayClient(str(tmp_path), "record", Unordered())
    out = rec.complete_json("s", "u", {})
    replayed = RecordReplayClient(str(tmp_path), "replay").complete_json("s", "u", {})
    assert out == replayed
    assert list(out) == list(replayed) == ["a", "z"]
    assert json.dumps(out) == json.dumps(replayed)


def test_unusable_model_replies_are_recorded_and_replayed_but_outages_are_not(tmp_path):
    class Flaky:
        mode = "live"

        def complete_json(self, system, user, schema):
            if user == "bad":
                raise LLMUnavailable("model did not return valid JSON: nope")
            raise LLMUnavailable("/v1/responses returned 503: down")

    rec = RecordReplayClient(str(tmp_path), "record", Flaky())
    with pytest.raises(LLMUnavailable, match="valid JSON"):
        rec.complete_json("s", "bad", {})
    with pytest.raises(LLMUnavailable, match="503"):
        rec.complete_json("s", "outage", {})
    assert len(list(tmp_path.glob("*.json"))) == 1              # only the content failure
    rep = RecordReplayClient(str(tmp_path), "replay")
    with pytest.raises(LLMUnavailable, match="valid JSON"):     # same failure, no live call
        rep.complete_json("s", "bad", {})
    with pytest.raises(LLMUnavailable, match="no recorded response"):
        rep.complete_json("s", "outage", {})
