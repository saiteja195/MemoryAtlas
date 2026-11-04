import sqlite3

import pytest

from app import db
from app.llm.base import LLMUnavailable
from app.llm.metered import MeteredLLM, usage_purpose
from app.llm.replay import RecordReplayClient

MODELS = {"text": "text-model-x", "asr": "asr-model-y"}


class Inner:
    mode = "live"

    def __init__(self, fail=False):
        self.fail = fail

    def complete_json(self, system, user, schema):
        if self.fail:
            raise LLMUnavailable("down")
        return {"answer": "ok"}

    def describe_image(self, image, prompt):
        return {"caption": "a wallet"}

    def transcribe(self, audio, keywords=None):
        return [{"turn_id": 1, "start_ms": 0, "end_ms": 2000, "speaker": "A", "text": "hello there"},
                {"turn_id": 2, "start_ms": 2500, "end_ms": 5000, "speaker": "B", "text": "hi"}]


def rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM model_calls ORDER BY at")]


def test_text_call_is_logged_with_purpose_and_sizes():
    conn = db.connect()
    llm = MeteredLLM(Inner(), conn, MODELS)
    with usage_purpose("answer"):
        out = llm.complete_json("sys words", "user words here", {})
    assert out == {"answer": "ok"}
    [r] = rows(conn)
    assert r["kind"] == "text" and r["purpose"] == "answer" and r["words_in"] == 5
    assert r["ok"] == 1 and r["served_from"] == "live" and r["model"] == "text-model-x"
    assert r["words_out"] >= 1 and r["duration_ms"] >= 0 and r["call_id"] and r["at"]
    assert r["tokens_in"] is None and r["tokens_out"] is None


def test_purpose_defaults_to_other_and_records_memory_day():
    conn = db.connect()
    llm = MeteredLLM(Inner(), conn, MODELS)
    llm.complete_json("s", "u", {})
    with usage_purpose("compile", "2026-11-02"):
        llm.complete_json("s", "u", {})
    a, b = sorted(rows(conn), key=lambda r: r["purpose"])
    assert (a["purpose"], a["memory_day"]) == ("compile", "2026-11-02")
    assert (b["purpose"], b["memory_day"]) == ("other", None)


def test_vision_call_counts_one_image():
    conn = db.connect()
    MeteredLLM(Inner(), conn, MODELS).describe_image(b"img", "describe this")
    [r] = rows(conn)
    assert r["kind"] == "vision" and r["images"] == 1 and r["model"] == "text-model-x"


def test_asr_call_counts_audio_ms_from_turns():
    conn = db.connect()
    MeteredLLM(Inner(), conn, MODELS).transcribe(b"wav")
    [r] = rows(conn)
    assert r["kind"] == "asr" and r["audio_ms"] == 5000 and r["model"] == "asr-model-y"


def test_cache_hit_is_logged_as_cache(tmp_path):
    cache = RecordReplayClient(str(tmp_path), "record", inner=Inner())
    cache.complete_json("s", "u", {})
    replay = RecordReplayClient(str(tmp_path), "replay")
    conn = db.connect()
    llm = MeteredLLM(replay, conn, MODELS)
    assert llm.mode == "replay"
    llm.complete_json("s", "u", {})
    assert [r["served_from"] for r in rows(conn)] == ["cache"]


def test_record_mode_first_call_is_live_then_cache(tmp_path):
    conn = db.connect()
    llm = MeteredLLM(RecordReplayClient(str(tmp_path), "record", inner=Inner()), conn, MODELS)
    llm.complete_json("s", "u", {})
    llm.complete_json("s", "u", {})
    assert sorted(r["served_from"] for r in rows(conn)) == ["cache", "live"]


def test_failure_is_logged_and_reraised():
    conn = db.connect()
    with pytest.raises(LLMUnavailable):
        MeteredLLM(Inner(fail=True), conn, MODELS).complete_json("s", "u", {})
    [r] = rows(conn)
    assert r["ok"] == 0 and r["words_out"] == 0


def test_logging_error_never_fails_the_call():
    class Broken:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("disk full")

        def commit(self):
            raise sqlite3.OperationalError("disk full")

    out = MeteredLLM(Inner(), Broken(), MODELS).complete_json("s", "u", {})
    assert out == {"answer": "ok"}


def test_no_content_is_stored():
    conn = db.connect()
    llm = MeteredLLM(Inner(), conn, MODELS)
    with usage_purpose("answer"):
        llm.complete_json("secretsystem", "secretprompt", {})
    llm.transcribe(b"wav")
    for r in conn.execute("SELECT * FROM model_calls"):
        for value in tuple(r):
            assert "secretprompt" not in str(value) and "secretsystem" not in str(value)
            assert "hello there" not in str(value)
