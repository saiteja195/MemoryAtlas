import pytest

from app.capture.draft import Draft, DraftStore, build_draft
from app.capture.media_info import ExifInfo

EXIF = ExifInfo("2026-10-29T12:42:10", 37.77, -122.41)
NO_EXIF = ExifInfo(None, None, None)


def perception(caption="Two bowls of ramen", ocr=("Mikado Ramen",), people=0):
    objects = [{"label": "bowl", "attrs": {}}] + [{"label": "person", "attrs": {}}] * people
    return {"caption": caption, "ocr_text": list(ocr), "objects": objects, "scene": "restaurant"}


def photo(**kw):
    exif = kw.pop("exif", EXIF)
    return build_draft("frame", perceptions=[kw.pop("perception", perception())],
                       frame_offsets_ms=[0], exif=exif, **kw)


def ids(d: Draft) -> list[str]:
    return [q.id for q in d.questions]


def field(d: Draft, key: str):
    return next(f for f in d.fields if f.key == key)


def test_photo_with_exif_is_sure_and_asks_only_where():
    d = photo()
    assert d.captured_at == "2026-10-29T12:42:10"
    assert (field(d, "when").source, field(d, "when").confidence) == ("exif", "sure")
    assert (d.lat, d.lon) == (37.77, -122.41)
    assert ids(d) == ["where_confirm"]


def test_photo_without_exif_or_file_time_asks_when():
    d = photo(exif=NO_EXIF)
    assert d.captured_at is None
    assert field(d, "when").confidence == "ask"
    assert "when" in ids(d)
    assert next(q for q in d.questions if q.id == "when").kind == "datetime"


def test_file_time_is_marked_check():
    d = photo(exif=NO_EXIF, file_modified_at="2026-10-30T09:00:00")
    assert d.captured_at == "2026-10-30T09:00:00"
    assert (field(d, "when").source, field(d, "when").confidence) == ("file", "check")
    assert "when" not in ids(d)


def test_ocr_text_becomes_confirmable_place():
    d = photo()
    assert d.place_name == "Mikado Ramen"
    f = field(d, "where")
    assert (f.value, f.source, f.confidence) == ("Mikado Ramen", "image", "check")
    q = next(q for q in d.questions if q.id == "where_confirm")
    assert q.kind == "choice" and q.options == ["Yes", "Different place"]


def test_no_ocr_asks_where_even_with_gps():
    d = photo(perception=perception(ocr=()))
    assert d.place_name is None
    assert (d.lat, d.lon) == (37.77, -122.41)
    assert field(d, "where").confidence == "ask"
    assert next(q for q in d.questions if q.id == "where").kind == "text"


def test_doing_comes_from_the_caption():
    f = field(photo(), "doing")
    assert (f.value, f.source, f.confidence) == ("Two bowls of ramen", "image", "sure")


TURNS = [{"turn_id": 1, "start_ms": 0, "end_ms": 1000, "speaker": "A", "text": "Lunch?"},
         {"turn_id": 2, "start_ms": 1000, "end_ms": 2000, "speaker": "B", "text": "Sure."}]


def test_two_speakers_ask_owner_and_consent_for_each():
    d = build_draft("audio", turns=TURNS, file_modified_at="2026-10-29T12:00:00")
    assert d.speakers == ["A", "B"]
    owner = next(q for q in d.questions if q.id == "owner_speaker")
    assert owner.kind == "choice" and owner.options == ["A", "B"]
    consent = [q for q in d.questions if q.kind == "consent"]
    assert [(q.id, q.ref) for q in consent] == [("person_A", "A"), ("person_B", "B")]


def test_one_speaker_asks_nothing_about_people():
    d = build_draft("audio", turns=TURNS[:1], file_modified_at="2026-10-29T12:00:00")
    assert d.speakers == ["A"]
    assert ids(d) == []


def test_unlabelled_turns_have_no_speakers():
    turns = [{"turn_id": 1, "start_ms": 0, "end_ms": 1, "speaker": None, "text": "hi"}]
    assert build_draft("audio", turns=turns, file_modified_at="2026-10-29T12:00:00").speakers == []


def test_visible_person_asks_consent():
    d = photo(perception=perception(people=2))
    consent = [q for q in d.questions if q.kind == "consent"]
    assert [(q.id, q.ref) for q in consent] == [("person_visible1", "visible1"),
                                                ("person_visible2", "visible2")]


def test_visible_people_are_capped_at_three():
    d = photo(perception=perception(people=7))
    assert len([q for q in d.questions if q.kind == "consent"]) == 3


def test_note_has_doing_and_no_people():
    d = build_draft("note", text="Lunch with Alex", file_modified_at="2026-10-29T12:00:00")
    assert field(d, "doing").value == "Lunch with Alex" and field(d, "doing").source == "note"
    assert not any(f.key in ("where", "people") for f in d.fields)
    assert ids(d) == []


def test_video_uses_ocr_from_any_frame_and_max_people():
    frames = [perception(ocr=(), people=0), perception(ocr=("Mikado Ramen",), people=1),
              perception(ocr=(), people=2)]
    d = build_draft("video", perceptions=frames, frame_offsets_ms=[1000, 2000, 3000], exif=NO_EXIF,
                    file_modified_at="2026-10-29T12:00:00")
    assert d.place_name == "Mikado Ramen"
    assert len([q for q in d.questions if q.kind == "consent"]) == 2
    assert d.frame_offsets_ms == [1000, 2000, 3000]


def test_video_with_audio_asks_owner_speaker():
    d = build_draft("video", perceptions=[perception()], frame_offsets_ms=[500], turns=TURNS,
                    exif=NO_EXIF, file_modified_at="2026-10-29T12:00:00")
    assert "owner_speaker" in ids(d)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_store_take_removes_draft():
    store = DraftStore()
    d = store.put(photo())
    assert d.draft_id
    assert store.take(d.draft_id).draft_id == d.draft_id
    with pytest.raises(KeyError):
        store.take(d.draft_id)


def test_store_expires():
    clock = Clock()
    store = DraftStore(ttl_seconds=900, clock=clock)
    d = store.put(photo())
    clock.t = 901
    with pytest.raises(KeyError):
        store.take(d.draft_id)


def test_store_unknown_id_raises():
    with pytest.raises(KeyError):
        DraftStore().take("nope")


def test_store_peek_does_not_remove():
    store = DraftStore()
    d = store.put(photo())
    assert store.peek(d.draft_id).draft_id == d.draft_id
    assert store.take(d.draft_id).draft_id == d.draft_id
    with pytest.raises(KeyError):
        store.peek(d.draft_id)


def people_questions(d):
    return [q for q in d.questions if q.kind == "consent"]


@pytest.mark.parametrize("labels", [["two women", "crowd", "baby"], ["men"], ["kid"], ["toddler"], ["face"],
                                    ["family"], ["couple"], ["human"], ["Friends"], ["a customer"]])
def test_common_people_labels_ask_consent(labels):
    p = {"caption": "A table", "ocr_text": [], "objects": [{"label": l, "attrs": {}} for l in labels], "scene": "cafe"}
    assert len(people_questions(photo(perception=p))) >= 1


@pytest.mark.parametrize("caption,scene", [("A man smiling at the camera", ""), ("", "a crowd at a market"),
                                           ("Two women and a baby at a cafe", "cafe")])
def test_a_person_in_the_caption_or_scene_asks_consent_even_without_object_labels(caption, scene):
    p = {"caption": caption, "ocr_text": [], "objects": [], "scene": scene}
    assert len(people_questions(photo(perception=p))) == 1


@pytest.mark.parametrize("label", ["manhole cover", "woodland", "command line", "bowl", "wallet"])
def test_people_words_are_matched_as_whole_words(label):
    p = {"caption": "Things", "ocr_text": [], "objects": [{"label": label, "attrs": {}}], "scene": "street"}
    assert people_questions(photo(perception=p)) == []
