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
