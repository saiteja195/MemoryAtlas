"""Opt-in object tracking in a video. The browser sends a few evenly spaced frames; SAM 3.1 looks for each named object
in each frame as an image (about $0.0025 a frame, so the cost is known up front, unlike a whole-clip video call that
bills every frame at the clip's native rate); frames with the object become time ranges. Only words are kept: when each
object was visible, never boxes or masks. People are never followed."""
import concurrent.futures
import contextvars
import re
from typing import Any

from .llm.base import LLMClient

MAX_FRAMES = 12
MAX_PHRASES = 3
MAX_FRAME_BYTES = 2_000_000
_BOX = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")
_PHRASE = re.compile(r"^[a-z0-9][a-z0-9 '\-]{1,29}$")
_PEOPLE = {"person", "people", "man", "men", "woman", "women", "child", "children", "kid", "kids", "boy", "girl", "baby",
           "babies", "face", "faces", "human", "humans", "guy", "lady", "ladies", "toddler", "adult", "adults"}


class PhraseError(ValueError):
    """The object words cannot be used; the message says why, in words a person can act on."""


def parse_boxes(text: str) -> list[dict[str, int]]:
    """The bounding boxes in a SAM reply. The pixel masks that come with them are ignored: they are not kept."""
    return [dict(zip(("x1", "y1", "x2", "y2", "w", "h"), map(int, m.groups()))) for m in _BOX.finditer(text or "")]


def clean_phrases(raw: list[str]) -> list[str]:
    """One to three short object words, lower-case and without repeats. Words for people are refused."""
    out: list[str] = []
    for p in raw:
        phrase = " ".join(str(p).lower().split())
        if not _PHRASE.match(phrase):
            raise PhraseError("Name objects in a few plain words, like \"wallet\" or \"car key\".")
        if _PEOPLE & set(re.split(r"[ \-']", phrase)):
            raise PhraseError("Object tracking does not follow people.")
        if phrase not in out:
            out.append(phrase)
    if not 1 <= len(out) <= MAX_PHRASES:
        raise PhraseError(f"Name between 1 and {MAX_PHRASES} objects.")
    return out


def presence_ranges(offsets_ms: list[int], hits: list[bool], max_gap: int = 1, min_hits: int = 2) -> list[dict[str, int]]:
    """Stretches of the clip where the object was seen. One missed frame inside a stretch does not split it; a stretch
    needs at least `min_hits` frames, so a single frame is treated as a blip and dropped."""
    ranges: list[dict[str, int]] = []
    first = last = -1
    count = misses = 0

    def close() -> None:
        if first >= 0 and count >= min_hits:
            ranges.append({"start_ms": offsets_ms[first], "end_ms": offsets_ms[last], "hits": count})

    for i, hit in enumerate(hits):
        if not hit:
            misses += 1
            continue
        if first >= 0 and misses <= max_gap:
            last, count = i, count + 1
        else:
            close()
            first = last = i
            count = 1
        misses = 0
    close()
    return ranges


def follow_objects(llm: LLMClient, frames: list[bytes], offsets_ms: list[int], phrases: list[str],
                   workers: int = 4) -> list[dict[str, Any]]:
    """Ask SAM about every (object, frame) pair, a few at a time, and turn the answers into time ranges per object."""
    def one(phrase: str, frame: bytes) -> bool:
        return bool(llm.detect_objects(frame, phrase))           # type: ignore[attr-defined]

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        # each task runs in its own copy of the context, so the usage purpose and the progress count follow it
        futures = {(p, i): pool.submit(contextvars.copy_context().run, one, p, f)
                   for p in phrases for i, f in enumerate(frames)}
        found = {key: fut.result() for key, fut in futures.items()}
    out = []
    for p in phrases:
        ranges = presence_ranges(offsets_ms, [found[(p, i)] for i in range(len(frames))])
        out.append({"phrase": p, "found": bool(ranges), "frames_checked": len(frames), "ranges": ranges})
    return out


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.1f} s"


def perception_for(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """What is stored for a clip: one sentence of words per object, in the shape of a photo's perception."""
    seen = [(o["phrase"], ", ".join(f"{_seconds(r['start_ms'])} to {_seconds(r['end_ms'])}" for r in o["ranges"]))
            for o in objects if o["found"]]
    return {"caption": "", "ocr_text": [], "scene": "A video clip, with the objects followed through it",
            "objects": [{"label": p, "attrs": {"visible": t}} for p, t in seen]}
