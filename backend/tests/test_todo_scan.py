"""The to-do scan: a second, separate pass that finds promises and requests in what was said."""
from app import db
from app.capture.models import RawCapture
from app.engine import MemoryEngine
from app.llm.base import LLMUnavailable
from app.privacy.consent import create_grant

from .fakes import FakeLLM, claim

SCAN = "You find promises and requests"
AT = "2026-10-29T12:35:00"


def world(rules=None):
    conn = db.connect()
    llm = FakeLLM(rules=rules or [])
    engine = MemoryEngine(conn, llm, "me", {"me": "Me", "alex": "Alex"})
    for person in ("me", "alex"):
        create_grant(conn, "secret", person, "s1")
    return conn, llm, engine


def talk(engine, line: str, at: str = AT):
    turns = [{"turn_id": 1, "start_ms": 0, "end_ms": 500, "speaker": "B", "text": line}]
    return engine.ingest(RawCapture(kind="audio", session_id="s1", captured_at=at, turns=turns,
                                    participants=["alex"], speaker_map={"A": "me", "B": "alex"}))


def scan_calls(llm):
    return [c for c in llm.calls if c[0].startswith(SCAN)]


def claims(conn, predicate):
    return conn.execute(
        "SELECT c.*, s.name AS subject, o.name AS obj FROM claims c JOIN entities s"
        " ON s.entity_id = c.subject_id LEFT JOIN entities o ON o.entity_id = c.object_id"
        " WHERE c.predicate=?", (predicate,)).fetchall()


def test_request_aimed_at_the_owner_is_stored():
    conn, llm, engine = world()
    llm.todo_replies.append({"claims": [claim(
        "Alex", "requested", "Me", object_type="person", value="send the notes",
        text="Alex asked me to send the notes")]})
    [got] = talk(engine, "Could you send me the notes?")
    rows = claims(conn, "requested")
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "active" and row["subject"] == "Alex" and row["obj"] == "Me"
    assert row["object_value"] == "send the notes"
    sources = {r[0] for r in conn.execute("SELECT source_id FROM justifications WHERE claim_id=?",
                                          (row["claim_id"],))}
    assert sources == {got.ingest.observation.source_id}
    assert len(scan_calls(llm)) == 1


def test_promise_missed_by_extraction_is_added_once():
    promise = claim("Alex", "committed_to", value="send the proposal by Friday",
                    text="Alex committed to send the proposal by Friday")
    conn, llm, engine = world(rules=[("proposal", [promise])])
    llm.todo_replies.append({"claims": [dict(promise, text="Alex promised the proposal by Friday")]})
    talk(engine, "I'll send the proposal by Friday.")
    assert len(claims(conn, "committed_to")) == 1


def test_scan_unavailable_does_not_reject_the_memory():
    promise = claim("Alex", "committed_to", value="send the proposal by Friday")
    conn, llm, engine = world(rules=[("proposal", [promise])])
    llm.todo_replies.append(LLMUnavailable("no recorded response for complete_json (x.json)"))
    [got] = talk(engine, "I'll send the proposal by Friday.")
    assert got.ingest.status == "ingested"
    assert got.compiled is not None and got.compiled.rejected is None
    assert len(claims(conn, "committed_to")) == 1
    assert len(scan_calls(llm)) == 1          # no retry after the model is unavailable


def test_invalid_scan_reply_is_dropped():
    conn, llm, engine = world()
    bad = {"claims": [claim("Alex", "promised_maybe", value="send the notes")]}
    llm.todo_replies += [bad, bad]
    [got] = talk(engine, "Could you send me the notes?")
    assert got.ingest.status == "ingested" and got.compiled.rejected is None
    assert len(scan_calls(llm)) == 2          # one repair attempt, then nothing
    assert "invalid" in scan_calls(llm)[1][1]
    assert conn.execute("SELECT COUNT(*) FROM claims WHERE predicate IN"
                        " ('requested', 'committed_to')").fetchone()[0] == 0


def test_typed_note_is_scanned():
    conn, llm, engine = world()
    llm.todo_replies.append({"claims": [claim(
        "Alex", "requested", "Me", object_type="person", value="book the room",
        text="Alex asked me to book the room")]})
    [got] = engine.ingest(RawCapture(kind="note", session_id="s1", captured_at=AT,
                                     text="Alex asked me to book the room"))
    assert got.ingest.observation.kind == "user_confirmation"
    assert len(scan_calls(llm)) == 1 and len(claims(conn, "requested")) == 1


def test_a_correction_is_not_scanned():
    conn, llm, engine = world()
    engine.ingest(RawCapture(kind="note", session_id="s1", captured_at=AT, ref="correction",
                             text="Actually, Alex asked me to book the room"))
    assert scan_calls(llm) == []


def test_scan_skips_frames_and_calendar():
    conn, llm, engine = world()
    engine.ingest(RawCapture(kind="frame", session_id="s1", captured_at=AT, perception={
        "caption": "Alex asked me to send the notes", "ocr_text": [], "objects": [],
        "scene": "office"}))
    engine.ingest(RawCapture(kind="calendar", session_id="s1", captured_at=AT,
                             ends_at="2026-10-29T13:00:00", text="Send the notes to Alex"))
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
    assert scan_calls(llm) == []


def test_scan_calls_are_metered_as_todo_scan():
    from app.llm.metered import MeteredLLM
    conn = db.connect()
    fake = FakeLLM(rules=[])
    llm = MeteredLLM(fake, conn, {"text": "t", "asr": "a"})
    engine = MemoryEngine(conn, llm, "me", {"me": "Me", "alex": "Alex"})
    for person in ("me", "alex"):
        create_grant(conn, "secret", person, "s1")
    talk(engine, "Could you send me the notes?")
    rows = conn.execute("SELECT purpose, memory_day FROM model_calls").fetchall()
    assert ("todo_scan", "2026-10-29") in [tuple(r) for r in rows]
    assert ("read_memory", "2026-10-29") in [tuple(r) for r in rows]
