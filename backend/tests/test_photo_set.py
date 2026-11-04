"""Several photos added together: each is read like a video frame (in parallel), the findings merge into one memory,
the memory's time is the earliest photo's, and people in any photo are asked about."""
import io
import threading

import pytest
from PIL import Image

from app.capture.draft import build_draft
from app.compiler.perceive import Perception, merge_perceptions, perception_to_text, split_for_extraction

from .fakes import FakeLLM
from .test_media_info import jpeg_with_exif, png
from .test_upload_api import b64, commit, make, source_texts


def jpeg_taken(stamp: str) -> bytes:
    """A small JPEG whose metadata says it was taken at `stamp` (EXIF form, 2026:10:29 09:05:00), with no GPS."""
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = stamp
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


class Each(FakeLLM):
    """A different object in each photo (by the order they arrive)."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()

    def describe_image(self, image, prompt):
        with self.lock:
            n = len(self.described)
            self.described.append(image)
        return {"caption": f"Photo number {n} shows thing {n}.", "ocr_text": [], "scene": "room",
                "objects": [{"label": f"thing{n}", "attrs": {}}]}


def body(photos, times=None):
    out = {"kind": "photos", "frames_b64": [b64(p) for p in photos]}
    if times is not None:
        out["photo_times"] = times
    return out


# -- the preview -------------------------------------------------------------------------------------

def test_photos_are_read_one_model_call_each_and_listed_together():
    fake = Each()
    c, _ = make(fake)
    r = c.post("/capture/preview", json=body([png(), png(), png()], ["2026-10-29T12:00:00"] * 3))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["kind"] == "photos" and len(d["perceptions"]) == 3 and len(fake.described) == 3
    seen = next(f for f in d["fields"] if f["key"] == "seen")
    assert sorted(seen["value"].split(", ")) == ["thing0", "thing1", "thing2"]      # objects from all photos


def test_photos_are_read_at_the_same_time():
    barrier = threading.Barrier(3, timeout=5)

    class Together(Each):
        def describe_image(self, image, prompt):
            barrier.wait()                          # returns only if all three readings are in flight together
            return super().describe_image(image, prompt)

    c, _ = make(Together())
    assert c.post("/capture/preview", json=body([png()] * 3, [None] * 3)).status_code == 200


@pytest.mark.parametrize("n,ok", [(1, True), (8, True), (9, False), (0, False)])
def test_one_to_eight_photos(n, ok):
    c, _ = make()
    r = c.post("/capture/preview", json=body([png()] * n, ["2026-10-29T12:00:00"] * n))
    assert (r.status_code == 200) is ok and (ok or r.status_code == 422)


def test_a_time_for_only_some_photos_is_refused():
    c, _ = make()
    assert c.post("/capture/preview", json=body([png()] * 3, ["2026-10-29T12:00:00"])).status_code == 422


def test_a_photo_that_is_not_an_image_is_refused_before_any_model_call():
    fake = Each()
    c, _ = make(fake)
    r = c.post("/capture/preview", json={"kind": "photos", "frames_b64": [b64(png()), b64(b"not an image")]})
    assert r.status_code == 415 and fake.described == []


# -- when --------------------------------------------------------------------------------------------

def field(d, key):
    return next(f for f in d["fields"] if f["key"] == key)


def test_when_is_the_earliest_photo_time():
    c, _ = make()
    d = c.post("/capture/preview", json=body([png(), png(), png()],
               ["2026-10-29T15:00:00", "2026-10-29T09:30:00", "2026-10-29T12:00:00"])).json()
    assert d["captured_at"] == "2026-10-29T09:30:00" and field(d, "when")["source"] == "file"


def test_a_photos_own_metadata_counts_and_the_earliest_of_both_kinds_wins():
    c, _ = make()
    d = c.post("/capture/preview", json=body([jpeg_taken("2026:10:29 09:05:00"), png()],
               ["2026-10-30T18:00:00", "2026-10-29T08:00:00"])).json()
    assert d["captured_at"] == "2026-10-29T08:00:00" and field(d, "when")["source"] == "file"
    d = c.post("/capture/preview", json=body([jpeg_taken("2026:10:29 09:05:00"), png()],
               ["2026-10-30T18:00:00", "2026-10-29T10:00:00"])).json()
    assert d["captured_at"] == "2026-10-29T09:05:00" and field(d, "when")["source"] == "exif"


def test_without_any_time_the_person_is_asked():
    c, _ = make()
    d = c.post("/capture/preview", json=body([png(), png()])).json()
    assert d["captured_at"] is None and any(q["id"] == "when" for q in d["questions"])


def test_the_first_gps_fix_among_the_photos_is_used():
    c, _ = make()
    d = c.post("/capture/preview", json=body([png(), jpeg_with_exif()])).json()
    assert d["lat"] == pytest.approx(37.7749, abs=1e-3) and d["captured_at"] == "2026-10-29T12:42:10"


# -- people ------------------------------------------------------------------------------------------

def perception(people=0):
    return {"caption": "x", "ocr_text": [], "scene": "", "objects": [{"label": "person", "attrs": {}}] * people}


def test_people_in_different_photos_add_up_where_frames_of_one_clip_do_not():
    shots = [perception(1), perception(1)]
    photos = build_draft("photos", perceptions=shots, file_modified_at="2026-10-29T12:00:00")
    clip = build_draft("video", perceptions=shots, frame_offsets_ms=[0, 1000], file_modified_at="2026-10-29T12:00:00")
    assert len([q for q in photos.questions if q.kind == "consent"]) == 2
    assert len([q for q in clip.questions if q.kind == "consent"]) == 1


def test_people_asked_about_are_capped_at_three():
    d = build_draft("photos", perceptions=[perception(2)] * 4, file_modified_at="2026-10-29T12:00:00")
    assert len([q for q in d.questions if q.kind == "consent"]) == 3


# -- saving ------------------------------------------------------------------------------------------

def test_photos_are_saved_as_one_memory_at_the_earliest_time():
    fake = Each()
    c, _ = make(fake)
    d = c.post("/capture/preview", json=body([png(), png(), png()],
               ["2026-10-29T15:00:00", "2026-10-29T09:30:00", "2026-10-29T12:00:00"])).json()
    r = commit(c, d, people=[])
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["results"]] == ["ingested"]
    rows = c.app.state.conn.execute("SELECT captured_at, text FROM sources WHERE kind='frame_observation' "
                                    "AND session_id LIKE 'upload-%'").fetchall()
    assert len(rows) == 1 and rows[0][0] == "2026-10-29T09:30:00"
    assert rows[0][1].startswith("Photo: ") and all(f"thing{i}" in rows[0][1] for i in range(3))


def test_a_person_who_did_not_agree_means_nothing_from_any_photo_is_saved():
    class Person(Each):
        def describe_image(self, image, prompt):
            out = super().describe_image(image, prompt)
            if len(self.described) == 2:
                out["objects"].append({"label": "person", "attrs": {}})
            return out

    c, _ = make(Person())
    d = c.post("/capture/preview", json=body([png(), png()], ["2026-10-29T12:00:00"] * 2)).json()
    r = commit(c, d, people=[{"ref": "visible1", "consented": False}])
    assert r.json()["results"][0]["reason"] == "no_consent" and source_texts(c) == []


def test_a_long_list_of_objects_from_many_photos_is_saved_a_few_at_a_time():
    shots = [{"caption": f"Shot {i}.", "ocr_text": [], "scene": "", "objects": [{"label": f"item{i}-{j}", "attrs": {}}
             for j in range(3)]} for i in range(8)]
    merged = merge_perceptions(shots, "Photo")
    parts = split_for_extraction(merged, per_source=6)
    assert [len(p["objects"]) for p in parts] == [6, 6, 6, 6] and merged["medium"] == "Photo"
    assert all(p["medium"] == "Photo" for p in parts)
    assert parts[1]["caption"] == "More from the same photos"
    assert perception_to_text(Perception.model_validate(parts[1])).startswith("Photo: More from the same photos")


def test_nothing_is_stored_by_previewing_photos():
    c, _ = make()
    before = c.app.state.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    c.post("/capture/preview", json=body([png(), png()], ["2026-10-29T12:00:00"] * 2))
    assert c.app.state.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before
