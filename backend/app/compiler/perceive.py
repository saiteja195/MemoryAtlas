"""Step 1 of the compiler: turn a raw frame into text with Muse Spark vision."""
from typing import Any

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


def perception_to_text(p: Perception, place_name: str | None = None) -> str:
    """The text that is stored as the source. Raw pixels are not kept anywhere."""
    parts = []
    if p.caption:
        parts.append(f"Photo: {p.caption.strip()}")
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
