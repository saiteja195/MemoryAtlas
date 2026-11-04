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


def test_replay_miss_is_logged_as_failed_cache_not_live(tmp_path):
    conn = db.connect()
    llm = MeteredLLM(RecordReplayClient(str(tmp_path), "replay"), conn, MODELS)
    with pytest.raises(LLMUnavailable):
        llm.complete_json("never", "recorded", {})
    [r] = rows(conn)
    assert r["ok"] == 0 and r["served_from"] == "cache"


def test_overlapping_calls_on_a_shared_client_keep_their_own_labels(tmp_path):
    import threading
    started, release = threading.Event(), threading.Event()

    class SlowInner(Inner):
        def complete_json(self, system, user, schema):
            if system == "slow":
                started.set()
                assert release.wait(5)
            return {"answer": system}

    shared = RecordReplayClient(str(tmp_path), "record", inner=SlowInner())
    shared.complete_json("fast", "u", {})            # recorded, so the next one is a cache hit
    conn = db.connect()
    llm = MeteredLLM(shared, conn, MODELS)
    slow = threading.Thread(target=lambda: llm.complete_json("slow", "u", {}))
    slow.start()
    assert started.wait(5)
    with usage_purpose("fast-one"):
        llm.complete_json("fast", "u", {})           # cache hit while the live call is in flight
    release.set()
    slow.join(5)
    by_purpose = {r["purpose"]: r["served_from"] for r in rows(conn)}
    assert by_purpose == {"fast-one": "cache", "other": "live"}


def test_commit_failure_is_swallowed_and_leaves_no_open_transaction():
    real = db.connect()

    class CommitFails:
        def __init__(self):
            self.fail = True

        def execute(self, *a, **k):
            return real.execute(*a, **k)

        def commit(self):
            if self.fail:
                raise sqlite3.OperationalError("database is locked")
            real.commit()

        def rollback(self):
            real.rollback()

    proxy = CommitFails()
    out = MeteredLLM(Inner(), proxy, MODELS).complete_json("s", "u", {})
    assert out == {"answer": "ok"}
    assert not real.in_transaction
    assert real.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 0
    proxy.fail = False
    real.execute("INSERT INTO blocked_hashes VALUES ('h', 'r')")    # the connection is still usable
    real.commit()


def test_file_database_metering_does_not_commit_the_request_connections_work(tmp_path):
    path = str(tmp_path / "p.db")
    conn = db.connect(path)
    llm = MeteredLLM(Inner(), conn, MODELS)
    conn.execute("INSERT INTO blocked_hashes VALUES ('h', 'half-done')")   # not committed yet
    llm.complete_json("s", "u", {})
    other = sqlite3.connect(path)
    assert other.execute("SELECT COUNT(*) FROM blocked_hashes").fetchone()[0] == 0
    assert conn.in_transaction                          # the request's transaction is untouched
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM blocked_hashes").fetchone()[0] == 0
    llm.complete_json("s", "u", {})                      # the busy row is flushed with this one
    assert other.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 2
    other.close()


def test_file_database_rows_are_written_without_the_request_connection(tmp_path):
    path = str(tmp_path / "p.db")
    conn = db.connect(path)
    MeteredLLM(Inner(), conn, MODELS).complete_json("s", "u", {})
    assert not conn.in_transaction
    other = sqlite3.connect(path)
    assert other.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 1
    other.close()
