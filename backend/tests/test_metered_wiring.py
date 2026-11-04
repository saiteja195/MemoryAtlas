from app.llm.metered import MeteredLLM

from .fakes import FakeLLM
from .test_profiles_api import make_app, new_client, signup
from .test_runtime import settings
from app.profiles.runtime import Runtimes


def calls(rt):
    return [dict(r) for r in rt.conn.execute("SELECT * FROM model_calls")]


def test_ingest_logs_read_memory_with_the_memory_day(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    rt = rts.get("aaaaaaaaaaaa", "A", False)
    rt.demo.advance(2)
    rows = calls(rt)
    assert rows and all(r["purpose"] == "read_memory" for r in rows)
    assert {r["memory_day"] for r in rows} == {"2026-10-29"}
    rts.close_all()


def test_ask_logs_answer_calls(tmp_path):
    llm = FakeLLM()
    app = make_app(tmp_path, llm)
    c = new_client(app)
    pid = signup(c).json()["profile"]["profile_id"]
    llm.recall_replies[:] = [
        {"action": "final", "status": "abstained", "answer": "No record.",
         "cited_claim_ids": [], "uncertainty_note": ""}]
    assert c.post("/recall/ask", json={"question": "Where did I have coffee?"}).status_code == 200
    rt = app.state.runtimes.get(pid, "x", False)
    rows = [r for r in calls(rt) if r["purpose"] == "answer"]
    assert rows and all(r["memory_day"] is None for r in rows)


def test_usage_is_per_profile(tmp_path):
    rts = Runtimes(settings(tmp_path), FakeLLM(), str(tmp_path / "data"))
    a, b = rts.get("aaaaaaaaaaaa", "A", False), rts.get("bbbbbbbbbbbb", "B", False)
    a.demo.advance(2)
    assert calls(a)
    assert calls(b) == []
    rts.close_all()


def test_injected_test_llm_is_still_wrapped(tmp_path):
    fake = FakeLLM()
    app = make_app(tmp_path, fake)
    c = new_client(app)
    pid = signup(c).json()["profile"]["profile_id"]
    rt = app.state.runtimes.get(pid, "x", False)
    assert isinstance(rt.llm, MeteredLLM) and rt.llm._inner is fake
    out = rt.llm.describe_image(b"x", "p")
    assert out["caption"] == "A wallet on a table"
    assert [r["kind"] for r in calls(rt)][-1] == "vision"


def test_preview_calls_are_logged_as_read_memory(tmp_path):
    app = make_app(tmp_path, FakeLLM())
    c = new_client(app)
    pid = signup(c).json()["profile"]["profile_id"]
    import base64, struct
    wav = (b"RIFF" + struct.pack("<I", 36 + 3200) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
           + b"data" + struct.pack("<I", 3200) + b"\0" * 3200)
    r = c.post("/capture/preview", json={"kind": "audio", "data_b64": base64.b64encode(wav).decode(),
                                         "file_modified_at": "2026-10-31T10:00:00"})
    assert r.status_code == 200, r.text
    rt = app.state.runtimes.get(pid, "x", False)
    [row] = [r for r in calls(rt) if r["kind"] == "asr"]
    assert row["purpose"] == "read_memory" and row["memory_day"] == "2026-10-31"


def test_flush_writes_rows_held_back_during_a_transaction(tmp_path):
    from app import db
    conn = db.connect(str(tmp_path / "p.db"))
    llm = MeteredLLM(FakeLLM(), conn, {"text": "t", "asr": "a"})
    conn.execute("INSERT INTO blocked_hashes VALUES ('h', 'half-done')")
    llm.describe_image(b"x", "p")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 0
    llm.flush()
    assert conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0] == 1
    llm.flush()                                          # nothing left: harmless
