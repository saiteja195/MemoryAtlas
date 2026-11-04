"""Opt-in object tracking in a video: the browser sends a few frames, SAM 3.1 looks for each named object in each frame,
and only text is kept (when and for how long each object was visible), never boxes or masks."""
import base64
import time

import httpx
import pytest

from app.llm.meta import MetaClient
from app.tracking import PhraseError, clean_phrases, parse_boxes, presence_ranges

from .fakes import FakeLLM
from .test_meta_client import responses_body
from .test_profiles_api import make_app, new_client, signup
from .test_upload_api import make

SAMPLE = ("<0f>0<|box;x1=903;y1=580;x2=1039;y2=647;w=1600;h=1200|>"
          "<|mask;x=0;y=0;data=68,137,~!!!8i#K{$dy#kE8W8h5w[fm|>\n")


# -- the parts that need no network ----------------------------------------------------------------

def test_boxes_are_read_and_masks_are_ignored():
    assert parse_boxes(SAMPLE) == [{"x1": 903, "y1": 580, "x2": 1039, "y2": 647, "w": 1600, "h": 1200}]
    assert parse_boxes("") == []
    assert len(parse_boxes(SAMPLE * 3)) == 3


def test_frames_with_the_object_become_time_ranges():
    offsets = [0, 500, 1000, 1500, 2000, 2500, 3000]
    assert presence_ranges(offsets, [False, False, True, True, True, False, True]) == [
        {"start_ms": 1000, "end_ms": 3000, "hits": 4}]                    # one missed frame does not split a stretch
    assert presence_ranges(offsets[:6], [True, True, False, False, True, True]) == [
        {"start_ms": 0, "end_ms": 500, "hits": 2}, {"start_ms": 2000, "end_ms": 2500, "hits": 2}]
    assert presence_ranges(offsets, [False] * 7) == []
    assert presence_ranges(offsets, [False, True, False, False, False, False, False]) == []   # one frame alone is a blip
    assert presence_ranges([], []) == []


def test_object_words_are_cleaned_and_people_are_refused():
    assert clean_phrases(["Glasses", "  car   key "]) == ["glasses", "car key"]
    assert clean_phrases(["wallet", "Wallet"]) == ["wallet"]
    for bad in (["person"], ["a woman"], ["Faces"], [], [""], ["a", "b", "c", "d"], ["x" * 40], ["<script>"], ["wallet; DROP"]):
        with pytest.raises(PhraseError):
            clean_phrases(bad)
    with pytest.raises(PhraseError, match="people"):
        clean_phrases(["child"])


def test_the_sam_client_sends_one_image_and_one_phrase_and_reads_the_boxes():
    seen = {}

    def handler(req):
        import json
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=responses_body(SAMPLE))

    c = MetaClient("https://api.meta.ai", "sk-secret", "muse-spark-1.3",
                   http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert c.detect_objects(b"\xff\xd8jpeg", "glasses") == [{"x1": 903, "y1": 580, "x2": 1039, "y2": 647, "w": 1600, "h": 1200}]
    body = seen["body"]
    assert body["model"] == "sam-3.1"
    parts = body["input"][0]["content"]
    assert {"type": "input_text", "text": "glasses"} in parts and any(p["type"] == "input_image" for p in parts)


def test_an_empty_reply_means_the_object_is_not_there():
    c = MetaClient("https://api.meta.ai", "k", "muse-spark-1.3", sleep=lambda s: None, http=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"output": [{"type": "message", "content": [
            {"type": "output_text", "text": ""}]}]}))))
    assert c.detect_objects(b"img", "wallet") == []


# -- the route -------------------------------------------------------------------------------------

class SamFake(FakeLLM):
    """SAM that finds a phrase in the frames the test names."""

    def __init__(self):
        super().__init__()
        self.hits: set[tuple[str, bytes]] = set()
        self.calls_made: list[tuple[str, bytes]] = []

    def detect_objects(self, image, phrase):
        self.calls_made.append((phrase, image))
        return [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "w": 10, "h": 10}] if (phrase, image) in self.hits else []


def frames(n=6):
    return [b"frame-%d" % i for i in range(n)]


def body(n=6, phrases=("glasses",), **over):
    b = {"frames_b64": [base64.b64encode(f).decode() for f in frames(n)], "offsets_ms": [i * 500 for i in range(n)],
         "phrases": list(phrases), "clip_start": "2026-10-29T12:42:10", "duration_ms": n * 500}
    b.update(over)
    return b


def wait(c, job_id, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f"/capture/commit/jobs/{job_id}").json()
        if s["state"] != "running":
            return s
        time.sleep(0.02)
    raise AssertionError("track job never finished")


def sources(c):
    return [r[0] for r in c.app.state.conn.execute("SELECT text FROM sources WHERE session_id LIKE 'upload-%'")]


def test_a_found_object_becomes_one_text_source_with_its_time_range():
    fake = SamFake()
    fake.hits = {("glasses", f) for f in frames()[2:5]}
    c, _ = make(fake)
    r = c.post("/capture/track", json=body(phrases=("glasses", "wallet")))
    assert r.status_code == 202
    done = wait(c, r.json()["job_id"])
    assert done["state"] == "done", done
    objs = {o["phrase"]: o for o in done["result"]["objects"]}
    assert objs["glasses"] == {"phrase": "glasses", "found": True, "frames_checked": 6,
                               "ranges": [{"start_ms": 1000, "end_ms": 2000, "hits": 3}]}
    assert objs["wallet"]["found"] is False and objs["wallet"]["ranges"] == []
    assert done["result"]["stored"] is True
    texts = sources(c)
    assert len(texts) == 1 and "glasses (visible: 1.0 s to 2.0 s)" in texts[0] and "video clip" in texts[0]
    assert "wallet" not in texts[0] and not texts[0].startswith("Photo")
    assert "mask" not in texts[0].lower() and "x1" not in texts[0]          # only words, never boxes or masks
    assert len(fake.calls_made) == 12                                       # 6 frames x 2 phrases


def test_nothing_found_stores_nothing():
    c, _ = make(SamFake())
    done = wait(c, c.post("/capture/track", json=body()).json()["job_id"])
    assert done["result"]["stored"] is False and done["result"]["objects"][0]["found"] is False
    assert sources(c) == []


def test_every_call_is_metered_as_sam_and_counted_as_an_image():
    fake = SamFake()
    c, _ = make(fake)
    wait(c, c.post("/capture/track", json=body(phrases=("glasses", "mouse"))).json()["job_id"])
    rows = c.app.state.conn.execute("SELECT model, kind, images FROM model_calls WHERE model LIKE 'sam%'").fetchall()
    assert len(rows) == 12 and {tuple(r) for r in rows} == {("sam-3.1", "vision", 1)}


@pytest.mark.parametrize("change", [
    {"phrases": ["person"]}, {"phrases": ["a", "b", "c", "d"]}, {"phrases": []},
    {"frames_b64": [], "offsets_ms": []}, {"offsets_ms": [0, 1]},
    {"frames_b64": ["AAAA"] * 13, "offsets_ms": list(range(13))}, {"clip_start": "not a time"},
])
def test_bad_requests_are_refused_before_anything_runs(change):
    fake = SamFake()
    c, _ = make(fake)
    assert c.post("/capture/track", json=body(**change)).status_code == 422
    assert fake.calls_made == []


def test_tracking_needs_live_mode():
    c = make_app_replay()
    assert c.post("/capture/track", json=body()).status_code == 409


def make_app_replay():
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.config import Settings
    return TestClient(create_app(Settings(auth=False, db_path=":memory:", llm_mode="replay")))


def test_a_profile_may_track_five_videos_an_hour_then_waits():
    fake = SamFake()
    c, _ = make(fake)
    for _ in range(5):
        r = c.post("/capture/track", json=body(n=2))
        assert r.status_code == 202
        wait(c, r.json()["job_id"])
    blocked = c.post("/capture/track", json=body(n=2))
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_a_second_track_while_one_runs_is_refused():
    import threading

    class Slow(SamFake):
        def __init__(self):
            super().__init__()
            self.release = threading.Event()

        def detect_objects(self, image, phrase):
            assert self.release.wait(10)
            return super().detect_objects(image, phrase)

    slow = Slow()
    c, _ = make(slow)
    first = c.post("/capture/track", json=body(n=2)).json()["job_id"]
    assert c.post("/capture/track", json=body(n=2)).status_code == 409
    slow.release.set()
    wait(c, first)


def test_the_usage_card_names_sam_by_what_it_does():
    fake = SamFake()
    c, _ = make(fake)
    wait(c, c.post("/capture/track", json=body(n=2)).json()["job_id"])
    from app.insights.usage import usage_summary
    rows = {m["model"]: m for m in usage_summary(c.app.state.conn)["models"]}
    assert rows["sam-3.1"]["kind_label"] == "Finds objects in images"
