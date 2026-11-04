"""Reading a video well and cheaply: frames are read in parallel, the findings of all frames become one memory (one
extraction call, not one per frame), the review shows what was seen, and printed text is not mistaken for a place."""
import base64
import threading

from app.capture.draft import build_draft
from app.compiler.perceive import merge_perceptions, perception_to_text, Perception

from .fakes import FakeLLM
from .test_upload_api import b64, commit, make, png, source_texts


def frame(caption="", ocr=(), objects=(), scene=""):
    return {"caption": caption, "ocr_text": list(ocr), "objects": [{"label": o, "attrs": {}} for o in objects], "scene": scene}


# -- merging -----------------------------------------------------------------------------------------

def test_the_frames_of_a_video_become_one_description_without_repeats():
    merged = merge_perceptions([
        frame("Two laptops on a desk.", ocr=["Cisco"], objects=["laptop", "mouse"], scene="desk"),
        frame("Two laptops on a wooden desk.", ocr=["cisco", "Logitech"], objects=["Laptop", "glasses"], scene="desk"),
        frame("A notebook with a to-do list.", objects=["notebook", "mouse"], scene="office"),
    ])
    assert [o["label"] for o in merged["objects"]] == ["laptop", "mouse", "glasses", "notebook"]
    assert merged["ocr_text"] == ["Cisco", "Logitech"]
    assert merged["caption"].count("laptops") == 1                       # the near-repeat caption is dropped
    assert "notebook" in merged["caption"] and merged["medium"] == "Video"
    text = perception_to_text(Perception.model_validate(merged))
    assert text.startswith("Video: ") and "Objects: laptop; mouse; glasses; notebook" in text


def test_merging_is_bounded_and_copes_with_empty_frames():
    many = [frame(f"Scene {i} with thing {i}.", ocr=[f"Sign {i}"], objects=[f"thing{i}" for i in range(10)]) for i in range(8)]
    m = merge_perceptions(many)
    assert len(m["objects"]) <= 25 and len(m["ocr_text"]) <= 10 and m["caption"].count(".") <= 3
    assert merge_perceptions([frame()])["caption"] == ""
    assert merge_perceptions([]) == {"caption": "", "ocr_text": [], "objects": [], "scene": "", "medium": "Video"}


# -- the review screen -------------------------------------------------------------------------------

def test_the_draft_lists_what_was_seen_and_describes_the_whole_clip():
    d = build_draft("video", perceptions=[frame("A desk with a laptop.", objects=["laptop", "mouse"]),
                                          frame("A notebook on the desk.", objects=["notebook", "mouse"])],
                    frame_offsets_ms=[0, 3000], file_modified_at="2026-10-29T12:00:00")
    fields = {f.key: f for f in d.fields}
    assert fields["seen"].value == "laptop, mouse, notebook" and fields["seen"].confidence == "sure"
    assert "laptop" in fields["doing"].value and "notebook" in fields["doing"].value


def test_every_object_is_sent_for_the_review_screen_and_commas_are_kept_out_of_labels():
    d = build_draft("frame", perceptions=[frame("x", objects=[f"item{i}" for i in range(20)] + ["cup, red"])],
                    frame_offsets_ms=[0])
    seen = next(f for f in d.fields if f.key == "seen").value
    assert seen.split(", ") == [f"item{i}" for i in range(20)] + ["cup  red"] and "more" not in seen


def test_no_objects_means_no_seen_row():
    d = build_draft("frame", perceptions=[frame("A sunset.")], frame_offsets_ms=[0])
    assert not any(f.key == "seen" for f in d.fields)


def test_text_printed_on_things_and_cropped_fragments_are_not_offered_as_a_place():
    book = build_draft("video", perceptions=[frame("A desk.", ocr=["pplications with AI Agents"], objects=["book", "laptop"])],
                       frame_offsets_ms=[0])
    assert book.place_name is None and any(q.id == "where" for q in book.questions)
    pad = build_draft("frame", perceptions=[frame("A desk.", ocr=["B"], objects=["mouse pad"])], frame_offsets_ms=[0])
    assert pad.place_name is None
    shop = build_draft("frame", perceptions=[frame("A cafe.", ocr=["Blue Door Café"], objects=["table", "cup"])], frame_offsets_ms=[0])
    assert shop.place_name == "Blue Door Café"
    later = build_draft("video", perceptions=[frame(ocr=["a fragment"]), frame(ocr=["Mikado Ramen"], objects=["bowl"])],
                        frame_offsets_ms=[0, 1000])
    assert later.place_name == "Mikado Ramen"                           # a later frame's sign still counts


# -- reading and saving ------------------------------------------------------------------------------

class Concurrent(FakeLLM):
    """Each reading waits until three are in flight at once, so a one-at-a-time reader cannot pass."""

    def __init__(self):
        super().__init__()
        self.gate = threading.Barrier(3, timeout=5)

    def describe_image(self, image, prompt):
        self.gate.wait()
        return super().describe_image(image, prompt)


def video_body(frames=6):
    return {"kind": "video", "frames_b64": [b64(png()) for _ in range(frames)],
            "frame_offsets_ms": [1000 * (i + 1) for i in range(frames)], "file_modified_at": "2026-10-29T12:35:00"}


def test_frames_are_read_at_the_same_time():
    fake = Concurrent()
    c, _ = make(fake)
    r = c.post("/capture/preview", json=video_body(6))
    assert r.status_code == 200, r.text
    assert len(fake.described) == 6 and len(r.json()["perceptions"]) == 6


def test_up_to_eight_frames_are_accepted_and_nine_are_not():
    c, fake = make()
    assert c.post("/capture/preview", json=video_body(8)).status_code == 200
    assert c.post("/capture/preview", json=video_body(9)).status_code == 422


def test_a_video_is_saved_as_one_memory_not_one_per_frame():
    c, fake = make()
    d = c.post("/capture/preview", json=video_body(6)).json()
    r = commit(c, d, people=[])
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["results"]] == ["ingested"]
    rows = c.app.state.conn.execute("SELECT captured_at, text FROM sources WHERE kind='frame_observation' "
                                    "AND session_id LIKE 'upload-%'").fetchall()
    assert len(rows) == 1 and rows[0][0] == "2026-10-29T12:35:00"
    assert rows[0][1].startswith("Video: ") and "wallet" in rows[0][1]
