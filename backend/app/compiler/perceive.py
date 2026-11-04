"""Step 1 of the compiler: turn a raw frame into text with Muse Spark vision."""
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..llm.base import LLMClient, LLMUnavailable

PERCEIVE_PROMPT = (
    "Describe this photo for a personal memory system. Return JSON with keys "
    '"caption" (one sentence), "ocr_text" (list of strings of any text visible), '
    '"objects" (list of {"label": str, "attrs": {str: str}}, e.g. colors) and "scene" (a few '
    "words). Describe only what is visible. Do not guess who any person is.")


class PObject(BaseModel):
    label: str
    attrs: dict[str, str] = Field(default_factory=dict)

    @field_validator("attrs", mode="before")
    @classmethod
    def _stringify(cls, v: Any) -> Any:
        return {str(k): str(x) for k, x in v.items()} if isinstance(v, dict) else {}


class Perception(BaseModel):
    caption: str = ""
    ocr_text: list[str] = Field(default_factory=list)
    objects: list[PObject] = Field(default_factory=list)
    scene: str = ""
    medium: Literal["Photo", "Video"] = "Photo"      # only changes the word the stored text starts with

    @field_validator("ocr_text", mode="before")
    @classmethod
    def _ocr_list(cls, v: Any) -> Any:
        if v is None:
            return []
        return [v] if isinstance(v, str) else [str(x) for x in v]

    @field_validator("objects", mode="before")
    @classmethod
    def _objects(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return []
        return [{"label": o} if isinstance(o, str) else o for o in v]


def parse_perception(raw: dict[str, Any]) -> Perception:
    return Perception.model_validate(raw)


def perceive_frame(llm: LLMClient, image: bytes) -> Perception:
    try:
        return parse_perception(llm.describe_image(image, PERCEIVE_PROMPT))
    except ValueError as e:  # pydantic.ValidationError subclasses ValueError
        raise LLMUnavailable(f"unusable perception: {e}") from e


_MAX_CAPTIONS, _MAX_OBJECTS, _MAX_OCR = 3, 25, 10


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def merge_perceptions(perceptions: list[dict[str, Any]], medium: Literal["Photo", "Video"] = "Video") -> dict[str, Any]:
    """The findings of a video's frames (or of several photos) as one description: each object, visible text and scene once, and only the
    captions that say something new. One description means one extraction call when it is saved, not one per frame."""
    captions: list[str] = []
    ocr: dict[str, str] = {}
    objects: dict[str, dict[str, Any]] = {}
    scenes: list[str] = []
    for raw in perceptions:
        p = parse_perception(raw)
        cap = p.caption.strip()
        if cap and len(captions) < _MAX_CAPTIONS:
            words = _words(cap)
            if not any(len(words & w) / max(1, len(words | w)) >= 0.7 for w in map(_words, captions)):
                captions.append(cap)
        for t in p.ocr_text:
            t = t.strip()
            if t and len(ocr) < _MAX_OCR:
                ocr.setdefault(t.lower(), t)
        for o in p.objects:
            key = o.label.strip().lower()
            if not key or len(objects) >= _MAX_OBJECTS and key not in objects:
                continue
            kept = objects.setdefault(key, {"label": o.label.strip(), "attrs": {}})
            for k, v in o.attrs.items():
                kept["attrs"].setdefault(k, v)
        sc = p.scene.strip()
        if sc and sc.lower() not in (x.lower() for x in scenes) and len(scenes) < 2:
            scenes.append(sc)
    return {"caption": " ".join(captions), "ocr_text": list(ocr.values()), "objects": list(objects.values()),
            "scene": ", ".join(scenes), "medium": medium}


def split_for_extraction(merged: dict[str, Any], per_source: int = 6) -> list[dict[str, Any]]:
    """A merged video or photo-set description as one or more memories. One extraction reads at most eight facts, so a long list of
    objects is saved a few at a time: the first memory carries the caption, text and scene, and each later one says
    it is more of the same clip. Still far fewer extraction calls than one for every frame."""
    objects = merged["objects"]
    if len(objects) <= per_source:
        return [merged]
    medium = merged.get("medium", "Video")
    more = "More of the same video clip" if medium == "Video" else "More from the same photos"
    parts = [{**merged, "objects": objects[:per_source]}]
    for start in range(per_source, len(objects), per_source):
        parts.append({"caption": more, "ocr_text": [], "scene": "",
                      "objects": objects[start:start + per_source], "medium": medium})
    return parts


def perception_to_text(p: Perception, place_name: str | None = None) -> str:
    """The text that is stored as the source. Raw pixels are not kept anywhere."""
    parts = []
    if p.caption:
        parts.append(f"{p.medium}: {p.caption.strip()}")
    if p.ocr_text:
        parts.append("Visible text: " + "; ".join(t.strip() for t in p.ocr_text if t.strip()))
    if p.objects:
        objs = []
        for o in p.objects:
            attrs = ", ".join(f"{k}: {v}" for k, v in o.attrs.items())
            objs.append(f"{o.label} ({attrs})" if attrs else o.label)
        parts.append("Objects: " + "; ".join(objs))
    if p.scene:
        parts.append(f"Scene: {p.scene.strip()}")
    if place_name:
        parts.append(f"Location: {place_name}")
    return ". ".join(parts)
