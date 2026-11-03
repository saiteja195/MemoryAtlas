import base64

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.llm.base import LLMUnavailable

from .fakes import FakeLLM
from .test_media_info import jpeg_with_exif, png, wav


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def make(fake=None):
    fake = fake or FakeLLM()
    c = TestClient(create_app(Settings(db_path=":memory:", llm_mode="live"), fake))
    return c, fake


def count(c, table: str) -> int:
    return c.app.state.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def field(draft: dict, key: str):
    return next(f for f in draft["fields"] if f["key"] == key)


# -- preview ------------------------------------------------------------------------------------

def test_preview_photo_returns_fields_and_stores_nothing():
    c, fake = make()
    grants_before = count(c, "consent_grants")      # the demo day seeds its own grants
    r = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(jpeg_with_exif())})
    assert r.status_code == 200
    d = r.json()
    assert d["draft_id"] and d["kind"] == "frame"
    assert field(d, "when")["source"] == "exif" and d["captured_at"] == "2026-10-29T12:42:10"
    assert len(fake.described) == 1
    assert count(c, "sources") == 0 and count(c, "consent_grants") == grants_before


def test_preview_photo_without_exif_asks_when_and_never_invents_it():
    c, _ = make()
    d = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(png())}).json()
    assert d["captured_at"] is None
    assert "when" in [q["id"] for q in d["questions"]]


def test_preview_uses_the_file_time_as_a_check_when_there_is_no_exif():
    c, _ = make()
    d = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(png()),
                                         "file_modified_at": "2026-10-30T09:00:00"}).json()
    assert (field(d, "when")["source"], field(d, "when")["confidence"]) == ("file", "check")


def test_preview_ignores_an_unparseable_file_time():
    c, _ = make()
    d = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(png()),
                                         "file_modified_at": "yesterday-ish"}).json()
    assert d["captured_at"] is None


def test_preview_rejects_non_image_with_415():
    c, fake = make()
    r = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(b"not an image")})
    assert r.status_code == 415 and "image" in r.json()["detail"]
    assert fake.described == []


def test_preview_rejects_mp3_as_audio_with_415():
    c, fake = make()
    mp3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" * 50
    r = c.post("/capture/preview", json={"kind": "audio", "data_b64": b64(mp3)})
    assert r.status_code == 415 and "WAV" in r.json()["detail"]
    assert fake.transcribed == []


def test_preview_rejects_bad_base64_with_422():
    c, _ = make()
    assert c.post("/capture/preview", json={"kind": "frame", "data_b64": "!!!not base64!!!"}).status_code == 422


def test_preview_oversize_is_413_before_decoding():
    c, fake = make()
    too_big = "A" * (10 * 1024 * 1024 * 4 // 3 + 64)
    r = c.post("/capture/preview", json={"kind": "frame", "data_b64": too_big})
    assert r.status_code == 413
    assert fake.described == []


def test_preview_audio_transcribes_and_keeps_turns():
    c, fake = make()
    d = c.post("/capture/preview", json={"kind": "audio", "data_b64": b64(wav(1.0)),
                                         "file_modified_at": "2026-10-29T12:00:00"}).json()
    assert len(fake.transcribed) == 1
    assert d["turns"] and d["speakers"] == ["B"]
    assert count(c, "sources") == 0


def test_preview_note_returns_doing():
    c, _ = make()
    d = c.post("/capture/preview", json={"kind": "note", "text": "Lunch with Alex",
                                         "file_modified_at": "2026-10-29T12:00:00"}).json()
    assert field(d, "doing")["value"] == "Lunch with Alex"


def test_preview_note_over_5000_characters_is_422():
    c, _ = make()
    assert c.post("/capture/preview", json={"kind": "note", "text": "x" * 5001}).status_code == 422


def test_preview_frame_without_data_is_422():
    c, _ = make()
    assert c.post("/capture/preview", json={"kind": "frame"}).status_code == 422


class NoRecording(FakeLLM):
    def describe_image(self, image, prompt):
        raise LLMUnavailable("no recorded response for this request")


def test_preview_replay_unrecorded_is_503():
    c, _ = make(NoRecording())
    r = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(png())})
    assert r.status_code == 503 and "no recorded response" in r.json()["detail"]


def test_preview_video_describes_each_frame_and_transcribes_audio():
    c, fake = make()
    body = {"kind": "video", "frames_b64": [b64(png()) for _ in range(3)],
            "frame_offsets_ms": [1000, 2000, 3000], "audio_b64": b64(wav(1.0)),
            "file_modified_at": "2026-10-29T12:00:00"}
    d = c.post("/capture/preview", json=body).json()
    assert len(fake.described) == 3 and len(fake.transcribed) == 1
    assert d["frame_offsets_ms"] == [1000, 2000, 3000] and len(d["perceptions"]) == 3


def test_preview_video_without_audio_has_no_speakers():
    c, fake = make()
    body = {"kind": "video", "frames_b64": [b64(png())], "frame_offsets_ms": [500],
            "file_modified_at": "2026-10-29T12:00:00"}
    d = c.post("/capture/preview", json=body).json()
    assert d["speakers"] == [] and fake.transcribed == []


@pytest.mark.parametrize("frames,offsets", [(5, [1, 2, 3, 4, 5]), (2, [1]), (0, [])])
def test_preview_video_bad_frame_counts_are_422(frames, offsets):
    c, _ = make()
    body = {"kind": "video", "frames_b64": [b64(png())] * frames, "frame_offsets_ms": offsets}
    assert c.post("/capture/preview", json=body).status_code == 422


# -- commit -------------------------------------------------------------------------------------

class Voices(FakeLLM):
    """Two speakers, and a photo with a person in it."""

    def describe_image(self, image, prompt):
        out = super().describe_image(image, prompt)
        out["objects"] = out["objects"] + [{"label": "person", "attrs": {}}]
        return out

    def transcribe(self, audio, keywords=None):
        self.transcribed.append(audio)
        return [{"turn_id": 1, "start_ms": 0, "end_ms": 1000, "speaker": "A", "text": "Where to for lunch?"},
                {"turn_id": 2, "start_ms": 1000, "end_ms": 2000, "speaker": "B",
                 "text": "You have to try the taco place across the street."}]


def preview_photo(c, data=None, **extra):
    r = c.post("/capture/preview", json={"kind": "frame", "data_b64": b64(data or jpeg_with_exif()), **extra})
    assert r.status_code == 200, r.text
    return r.json()


def preview_audio(c):
    r = c.post("/capture/preview", json={"kind": "audio", "data_b64": b64(wav(1.0)),
                                         "file_modified_at": "2026-10-29T12:35:00"})
    assert r.status_code == 200, r.text
    return r.json()


def commit(c, draft, **answers):
    return c.post("/capture/commit", json={"draft_id": draft["draft_id"], "answers": answers})


def source_texts(c) -> list[str]:
    return [r[0] for r in c.app.state.conn.execute("SELECT text FROM sources WHERE session_id LIKE 'upload-%'")]


def test_commit_photo_ingests_and_creates_the_owner_grant():
    c, _ = make()
    r = commit(c, preview_photo(c))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == "upload-2026-10-29"
    assert [x["status"] for x in body["results"]] == ["ingested"] and body["results"][0]["claims"] > 0
    assert [g["person"] for g in body["grants"]] == ["me"] and body["grants"][0]["revocation_token"]
    row = c.app.state.conn.execute(
        "SELECT media_bytes_retained, captured_at FROM sources WHERE session_id='upload-2026-10-29'").fetchone()
    assert row["media_bytes_retained"] == 0 and row["captured_at"] == "2026-10-29T12:42:10"


def test_commit_twice_second_is_404_and_stores_once():
    c, _ = make()
    d = preview_photo(c)
    assert commit(c, d).status_code == 200
    assert commit(c, d).status_code == 404
    assert len(source_texts(c)) == 1


def test_commit_unknown_draft_is_404():
    c, _ = make()
    assert c.post("/capture/commit", json={"draft_id": "nope", "answers": {}}).status_code == 404


def test_commit_missing_when_is_422_and_keeps_the_draft():
    c, _ = make()
    d = preview_photo(c, png())
    assert commit(c, d).status_code == 422
    ok = commit(c, d, when="2026-10-28T08:15:00")
    assert ok.status_code == 200 and ok.json()["session_id"] == "upload-2026-10-28"


def test_commit_unparseable_when_is_422():
    c, _ = make()
    assert commit(c, preview_photo(c, png()), when="soon").status_code == 422


def test_commit_uses_the_answered_place():
    c, _ = make()
    assert commit(c, preview_photo(c), where="Mikado Ramen").status_code == 200
    assert any("Location: Mikado Ramen" in t for t in source_texts(c))


def test_commit_duplicate_photo_reports_duplicate():
    c, _ = make()
    first, second = commit(c, preview_photo(c)), commit(c, preview_photo(c))
    assert first.json()["results"][0]["status"] == "ingested"
    assert (second.json()["results"][0]["status"], second.json()["results"][0]["reason"]) == ("rejected", "duplicate")


def test_commit_audio_creates_a_grant_for_the_consenting_person():
    c, fake = make(Voices())
    d = preview_audio(c)
    assert d["speakers"] == ["A", "B"]
    r = commit(c, d, owner_speaker="A", people=[{"ref": "B", "name": "Alex", "consented": True}])
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(g["person"] for g in body["grants"]) == ["alex", "me"]
    assert [x["status"] for x in body["results"]] == ["ingested", "ingested"]
    assert len(fake.transcribed) == 1                      # preview only; commit did not call Muse again


def test_commit_audio_without_owner_speaker_is_422():
    c, _ = make(Voices())
    assert commit(c, preview_audio(c), people=[{"ref": "B", "name": "Alex", "consented": True}]).status_code == 422


def test_commit_audio_without_an_answer_for_the_other_speaker_is_422():
    c, _ = make(Voices())
    assert commit(c, preview_audio(c), owner_speaker="A").status_code == 422


def test_commit_consenting_person_needs_a_name():
    c, _ = make(Voices())
    r = commit(c, preview_audio(c), owner_speaker="A", people=[{"ref": "B", "name": " ", "consented": True}])
    assert r.status_code == 422


def test_commit_person_cannot_be_named_as_the_owner():
    c, _ = make(Voices())
    r = commit(c, preview_audio(c), owner_speaker="A", people=[{"ref": "B", "name": "Me", "consented": True}])
    assert r.status_code == 422


def test_commit_person_declines_stores_nothing_and_creates_no_grant():
    c, _ = make(Voices())
    d = preview_audio(c)
    grants_before = count(c, "consent_grants")
    r = commit(c, d, owner_speaker="A", people=[{"ref": "B", "name": "Alex", "consented": False}])
    assert r.status_code == 200
    assert [(x["status"], x["reason"]) for x in r.json()["results"]] == [("rejected", "no_consent")]
    assert r.json()["grants"] == []
    assert source_texts(c) == [] and count(c, "consent_grants") == grants_before


def test_commit_visible_person_declines_rejects_the_photo():
    c, _ = make(Voices())
    d = preview_photo(c)
    assert [q["id"] for q in d["questions"] if q["kind"] == "consent"] == ["person_visible1"]
    grants_before = count(c, "consent_grants")
    r = commit(c, d, people=[{"ref": "visible1", "consented": False}])
    assert r.json()["results"][0]["reason"] == "no_consent"
    assert source_texts(c) == [] and count(c, "consent_grants") == grants_before


def test_commit_visible_person_consents_and_photo_is_stored():
    c, _ = make(Voices())
    r = commit(c, preview_photo(c), people=[{"ref": "visible1", "consented": True}])
    assert r.json()["results"][0]["status"] == "ingested"


def video_body(frames=3, audio=True):
    body = {"kind": "video", "frames_b64": [b64(png())] * frames,
            "frame_offsets_ms": [1000 * (i + 1) for i in range(frames)],
            "file_modified_at": "2026-10-29T12:35:00"}
    if audio:
        body["audio_b64"] = b64(wav(1.0))
    return body


def test_commit_video_ingests_frames_and_audio():
    c, _ = make(Voices())
    d = c.post("/capture/preview", json=video_body()).json()
    r = commit(c, d, owner_speaker="A", people=[{"ref": "B", "name": "Alex", "consented": True},
                                                {"ref": "visible1", "consented": True}])
    assert r.status_code == 200, r.text
    statuses = [x["status"] for x in r.json()["results"]]
    assert statuses == ["ingested"] * 5                    # 3 frames, 2 spoken turns
    times = sorted(t for t in (x[0] for x in c.app.state.conn.execute(
        "SELECT captured_at FROM sources WHERE kind='frame_observation' AND session_id LIKE 'upload-%'")))
    assert times == ["2026-10-29T12:35:01", "2026-10-29T12:35:02", "2026-10-29T12:35:03"]


def test_commit_video_person_declines_stores_nothing():
    c, _ = make(Voices())
    d = c.post("/capture/preview", json=video_body(audio=False)).json()
    r = commit(c, d, people=[{"ref": "visible1", "consented": False}])
    assert r.json()["results"][0]["reason"] == "no_consent" and source_texts(c) == []


# -- review fixes -------------------------------------------------------------------------------

class Recording(FakeLLM):
    mode = "record"


def test_preview_and_commit_need_live_mode_so_nothing_is_cached():
    c, fake = make(Recording())
    r = c.post("/capture/preview", json={"kind": "note", "text": "hello there"})
    assert r.status_code == 409 and "live" in r.json()["detail"]
    assert c.post("/capture/commit", json={"draft_id": "x", "answers": {}}).status_code == 409
    assert fake.described == [] and fake.transcribed == []


def test_commit_lets_the_person_correct_the_file_date():
    c, _ = make()
    d = preview_photo(c, png(), file_modified_at="2026-10-30T09:00:00")
    r = commit(c, d, when="2026-10-28T08:15:00")
    assert r.status_code == 200 and r.json()["session_id"] == "upload-2026-10-28"
    row = c.app.state.conn.execute("SELECT captured_at FROM sources WHERE session_id='upload-2026-10-28'").fetchone()
    assert row["captured_at"] == "2026-10-28T08:15:00"


def test_commit_keeps_the_draft_date_when_no_correction_is_sent():
    c, _ = make()
    d = preview_photo(c, png(), file_modified_at="2026-10-30T09:00:00")
    assert commit(c, d).json()["session_id"] == "upload-2026-10-30"
