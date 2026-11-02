import pytest

from app.capture.gateway import Gateway, content_hash
from app.capture.models import RawCapture
from app.capture.redact import redact
from app.privacy.consent import create_grant, verify_token

from .fakes import FakeLLM


def grants(conn, *pairs):
    return {p: create_grant(conn, "s", *p) for p in pairs}


def test_redaction_removes_identifiers_and_keeps_counts_only():
    text, counts = redact("Call 415-555-0134 or mail sam@example.com, card 4111 1111 1111 1111.")
    assert "415" not in text and "example.com" not in text and "4111" not in text
    assert counts == {"card": 1, "email": 1, "phone": 1}


def test_redaction_leaves_ordinary_numbers_alone():
    text, counts = redact("Meeting at 400 Market St at 12:30, order 1234567890123")
    assert text.startswith("Meeting at 400 Market St at 12:30") and counts["card"] == 0


def test_revocation_token_is_stored_as_hmac_only(conn):
    gid, token = create_grant(conn, "secret", "alex", "s1")
    row = conn.execute("SELECT token_hash FROM consent_grants WHERE grant_id=?", (gid,)).fetchone()
    assert token not in row["token_hash"]
    assert verify_token("secret", token, row["token_hash"])
    assert not verify_token("secret", token + "x", row["token_hash"])


def audio_cap(**kw):
    base = dict(kind="audio", session_id="s1", captured_at="2026-10-29T12:35:00",
                participants=["me", "alex"], speaker_map={"A": "me", "B": "alex"},
                turns=[{"turn_id": 1, "start_ms": 0, "end_ms": 5, "speaker": "B",
                        "text": "I'll send you the proposal by Friday."},
                       {"turn_id": 2, "start_ms": 60000, "end_ms": 61000, "speaker": "A",
                        "text": "Great."}])
    base.update(kw)
    return RawCapture(**base)


def test_audio_dropped_unless_every_participant_consented(conn):
    grants(conn, ("me", "s1"))  # Alex has not consented
    llm = FakeLLM()
    out = Gateway(conn, llm).ingest(audio_cap(audio=b"RIFFxxxx", turns=None))
    assert [r.reason for r in out] == ["no_consent"]
    assert llm.transcribed == []                       # nothing was sent for transcription
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0


def test_audio_segments_are_stored_under_the_speakers_grant(conn):
    g = grants(conn, ("me", "s1"), ("alex", "s1"))
    out = Gateway(conn, FakeLLM()).ingest(audio_cap())
    rows = {r.observation.speaker: r.observation for r in out}
    assert rows["alex"].grant_id == g[("alex", "s1")][0]
    assert rows["me"].grant_id == g[("me", "s1")][0]
    assert rows["alex"].text == "Alex: I'll send you the proposal by Friday."
    assert rows["alex"].captured_at == "2026-10-29T12:35:00"
    assert rows["me"].captured_at == "2026-10-29T12:36:00"   # start_ms offsets the clock


def test_unknown_speaker_goes_under_the_other_participants_grant(conn):
    g = grants(conn, ("me", "s1"), ("alex", "s1"))
    cap = audio_cap(speaker_map={}, turns=[{"turn_id": 1, "start_ms": 0, "speaker": "B",
                                            "text": "Hello there."}])
    (res,) = Gateway(conn, FakeLLM()).ingest(cap)
    assert res.observation.text == "Speaker B: Hello there."
    assert res.observation.grant_id == g[("alex", "s1")][0]


def test_raw_audio_is_transcribed_then_dropped(conn):
    grants(conn, ("me", "s1"), ("alex", "s1"))
    llm = FakeLLM()
    cap = audio_cap(audio=b"RIFFxxxx", turns=None)
    out = Gateway(conn, llm).ingest(cap)
    assert out[0].status == "ingested" and cap.audio is None
    assert "Alex" in llm.keywords                       # names bias recognition


def test_frame_bytes_are_perceived_into_text_and_dropped(conn):
    grants(conn, ("me", "s1"))
    llm = FakeLLM()
    cap = RawCapture(kind="frame", session_id="s1", captured_at="2026-10-29T09:10:00",
                     image=b"\xff\xd8\xff-jpeg-bytes")
    (res,) = Gateway(conn, llm).ingest(cap)
    assert cap.image is None and llm.described == [b"\xff\xd8\xff-jpeg-bytes"]
    row = conn.execute("SELECT * FROM sources").fetchone()
    assert "wallet" in row["text"] and "Blue Door" in row["text"]
    assert row["media_bytes_retained"] == 0 and res.status == "ingested"


def test_frame_without_consent_is_not_perceived(conn):
    llm = FakeLLM()
    cap = RawCapture(kind="frame", session_id="s1", captured_at="2026-10-29T09:10:00", image=b"x")
    (res,) = Gateway(conn, llm).ingest(cap)
    assert res.reason == "no_consent" and llm.described == []


def test_blocked_hash_stops_reingest(conn):
    grants(conn, ("me", "s1"))
    note = RawCapture(kind="note", session_id="s1", captured_at="2026-10-29T10:00:00",
                      text="Alex lives on Pine Street")
    conn.execute("INSERT INTO blocked_hashes VALUES (?, 'revoked')",
                 (content_hash("alex lives on  PINE street"),))
    (res,) = Gateway(conn, FakeLLM()).ingest(note)
    assert res.reason == "blocked"


def test_replaying_the_same_capture_is_idempotent(conn):
    grants(conn, ("me", "s1"))
    mk = lambda: RawCapture(kind="note", session_id="s1", captured_at="2026-10-29T10:00:00",
                            text="Remember the milk")
    g = Gateway(conn, FakeLLM())
    assert g.ingest(mk())[0].status == "ingested"
    assert g.ingest(mk())[0].reason == "duplicate"


def test_text_is_redacted_before_it_is_stored(conn):
    grants(conn, ("me", "s1"))
    note = RawCapture(kind="note", session_id="s1", captured_at="2026-10-29T10:00:00",
                      text="Sam's number is 415-555-0134")
    Gateway(conn, FakeLLM()).ingest(note)
    assert "555" not in conn.execute("SELECT text FROM sources").fetchone()["text"]


@pytest.mark.parametrize("kind", ["frame", "calendar", "note"])
def test_missing_payload_is_rejected(conn, kind):
    grants(conn, ("me", "s1"))
    (res,) = Gateway(conn, FakeLLM()).ingest(
        RawCapture(kind=kind, session_id="s1", captured_at="2026-10-29T10:00:00"))
    assert res.status == "rejected"
