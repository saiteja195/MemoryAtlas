"""A draft of what Muse understood from an upload, and the questions still open.

Nothing here is stored in the database. Which questions get asked is decided by the rules in
`build_draft`, not by the model: Muse supplies perceptions and transcripts, code decides what
is certain, what needs confirming, and what only the person can answer (especially consent).
"""
import re
import time
import uuid
from typing import Callable, Literal

from pydantic import BaseModel, Field, PrivateAttr

from ..compiler.perceive import merge_perceptions
from .media_info import ExifInfo

Confidence = Literal["sure", "check", "ask"]
Source = Literal["exif", "file", "image", "voice", "note", "user"]

# Whole words that mean a person is in the picture. Over-asking costs one extra question; missing a
# person stores someone who never agreed, so the list is generous and matched as whole words.
_PERSON_WORDS = (
    "person", "persons", "people", "man", "men", "woman", "women", "child", "children", "kid", "kids",
    "boy", "boys", "girl", "girls", "baby", "babies", "toddler", "toddlers", "infant", "infants",
    "teen", "teens", "teenager", "teenagers", "adult", "adults", "human", "humans", "guy", "guys",
    "lady", "ladies", "crowd", "crowds", "family", "families", "couple", "couples", "friend", "friends",
    "face", "faces", "customer", "customers", "diner", "diners", "passenger", "passengers",
    "pedestrian", "pedestrians", "waiter", "waitress", "worker", "workers", "selfie", "portrait",
)
_PERSON_RE = re.compile(r"\b(?:" + "|".join(_PERSON_WORDS) + r")\b", re.IGNORECASE)
_MAX_VISIBLE = 3
# Text printed on these is a title, a brand or a label, not the name of the place the person is in.
_PRINTED_ON = re.compile(r"\b(?:book|books|magazine|notebook|mouse ?pad|bottle|can|box|package|packaging|sticker|poster|"
                         r"laptop|keyboard|monitor|screen|shirt)\b", re.IGNORECASE)


class DraftField(BaseModel):
    key: Literal["when", "where", "doing", "seen", "people"]
    value: str | None
    source: Source | None
    confidence: Confidence


class Question(BaseModel):
    id: str
    field: str
    prompt: str
    kind: Literal["datetime", "text", "choice", "consent"]
    options: list[str] = Field(default_factory=list)
    ref: str | None = None


class Draft(BaseModel):
    # Optional SAM frames live only in this temporary RAM draft, never API output or SQLite.
    _tracking: dict | None = PrivateAttr(default=None)
    draft_id: str = ""
    kind: Literal["frame", "audio", "note", "video", "photos"]
    fields: list[DraftField]
    questions: list[Question]
    captured_at: str | None = None
    lat: float | None = None
    lon: float | None = None
    place_name: str | None = None
    text: str | None = None
    perceptions: list[dict] = Field(default_factory=list)
    frame_offsets_ms: list[int] = Field(default_factory=list)
    turns: list[dict] | None = None
    speakers: list[str] = Field(default_factory=list)


def _visible_people(perception: dict) -> int:
    """How many people the perception shows. Labels count one each; a person mentioned only in the
    caption or scene still counts as one, because Muse does not always list people as objects."""
    count = 0
    for o in perception.get("objects") or []:
        label = (o.get("label") if isinstance(o, dict) else str(o)) or ""
        if _PERSON_RE.search(label):
            count += 1
    if count == 0 and any(_PERSON_RE.search(str(perception.get(k) or "")) for k in ("caption", "scene")):
        count = 1
    return count


def _first_ocr(perceptions: list[dict]) -> str | None:
    """The first visible text that could be the name of a place. Text on a book or a mouse pad is not one, and neither
    is a cropped fragment ("pplications") or a single letter; when nothing qualifies the person is asked instead."""
    for p in perceptions:
        labels = [(o.get("label") if isinstance(o, dict) else str(o)) or "" for o in p.get("objects") or []]
        if any(_PRINTED_ON.search(label) for label in labels):
            continue
        for t in p.get("ocr_text") or []:
            t = str(t).strip()
            if sum(c.isalpha() for c in t) >= 3 and not t[0].islower():
                return t
    return None


def _seen(perceptions: list[dict]) -> str | None:
    """Every object Muse noticed, once each, for the review screen (the page shortens a long list and lets the person
    open it). The same list is saved with the memory."""
    labels = [o["label"].replace(",", " ") for o in merge_perceptions(perceptions)["objects"]]
    return ", ".join(labels) or None


def _first_caption(perceptions: list[dict]) -> str | None:
    return next((str(p["caption"]).strip() for p in perceptions if str(p.get("caption") or "").strip()), None)


def build_draft(kind: str, *, perceptions: list[dict] | None = None,
                frame_offsets_ms: list[int] | None = None, turns: list[dict] | None = None,
                text: str | None = None, exif: ExifInfo | None = None,
                file_modified_at: str | None = None) -> Draft:
    perceptions = perceptions or []
    exif = exif or ExifInfo(None, None, None)
    fields: list[DraftField] = []
    questions: list[Question] = []

    # when
    if exif.taken_at:
        captured_at = exif.taken_at
        fields.append(DraftField(key="when", value=captured_at, source="exif", confidence="sure"))
    elif file_modified_at:
        captured_at = file_modified_at
        fields.append(DraftField(key="when", value=captured_at, source="file", confidence="check"))
    else:
        captured_at = None
        fields.append(DraftField(key="when", value=None, source=None, confidence="ask"))
        questions.append(Question(id="when", field="when", kind="datetime",
                                  prompt="When did this happen?"))

    # where (images only)
    place_name = None
    if kind in ("frame", "video", "photos"):
        place_name = _first_ocr(perceptions)
        if place_name:
            fields.append(DraftField(key="where", value=place_name, source="image", confidence="check"))
            questions.append(Question(
                id="where_confirm", field="where", kind="choice", options=["Yes", "Different place"],
                prompt=f'The text reads "{place_name}". Is this where you were?'))
        else:
            fields.append(DraftField(key="where", value=None, source=None, confidence="ask"))
            questions.append(Question(id="where", field="where", kind="text",
                                      prompt="What is this place called?"))

    # doing
    if kind in ("frame", "video", "photos"):
        caption = (merge_perceptions(perceptions)["caption"] if kind in ("video", "photos")
                   else _first_caption(perceptions))
        if caption:
            fields.append(DraftField(key="doing", value=caption, source="image", confidence="sure"))
        seen = _seen(perceptions)
        if seen:
            fields.append(DraftField(key="seen", value=seen, source="image", confidence="sure"))
    elif kind == "note" and text:
        fields.append(DraftField(key="doing", value=text.strip(), source="note", confidence="sure"))

    # people
    speakers = sorted({str(t["speaker"]) for t in (turns or []) if t.get("speaker")})
    # Frames of one clip show the same scene, so the most people in any one of them is the count. Separate photos can
    # show different people, so they add up: asking about one too many is cheap, storing someone who never agreed is not.
    counts_ = [_visible_people(p) for p in perceptions]
    visible = min(sum(counts_) if kind == "photos" else max(counts_, default=0), _MAX_VISIBLE)
    if len(speakers) >= 2:
        fields.append(DraftField(key="people", value="Speakers " + ", ".join(speakers),
                                 source="voice", confidence="ask"))
        questions.append(Question(id="owner_speaker", field="people", kind="choice", options=speakers,
                                  prompt="Which speaker are you?"))
        for label in speakers:
            questions.append(Question(
                id=f"person_{label}", field="people", kind="consent", ref=label,
                prompt=f"Who is speaker {label}, and did they agree to be recorded?"))
    if visible:
        fields.append(DraftField(key="people", value=f"{visible} person(s) visible",
                                 source="image", confidence="ask"))
        for n in range(1, visible + 1):
            questions.append(Question(
                id=f"person_visible{n}", field="people", kind="consent", ref=f"visible{n}",
                prompt=f"Who is person {n} in the picture, and did they agree to be in your Atlas?"))

    return Draft(kind=kind, fields=fields, questions=questions, captured_at=captured_at,
                 lat=exif.lat, lon=exif.lon, place_name=place_name, text=text,
                 perceptions=perceptions, frame_offsets_ms=frame_offsets_ms or [0] * len(perceptions),
                 turns=turns, speakers=speakers)


class DraftStore:
    """In-memory only. A draft holds text from the upload, never the upload itself."""

    def __init__(self, ttl_seconds: float = 900, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._clock = ttl_seconds, clock
        self._drafts: dict[str, tuple[float, Draft]] = {}

    def clear(self) -> None:
        self._drafts.clear()

    def put(self, draft: Draft) -> Draft:
        self._expire()
        stored = draft.model_copy(update={"draft_id": uuid.uuid4().hex})
        self._drafts[stored.draft_id] = (self._clock() + self._ttl, stored)
        return stored

    def peek(self, draft_id: str) -> Draft:
        """Look without removing, so a commit that fails validation leaves the draft usable."""
        self._expire()
        return self._drafts[draft_id][1]

    def take(self, draft_id: str) -> Draft:
        self._expire()
        _, draft = self._drafts.pop(draft_id)       # KeyError when unknown or expired
        return draft

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, (due, _) in self._drafts.items() if due <= now]:
            del self._drafts[key]
