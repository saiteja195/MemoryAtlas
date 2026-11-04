"""Read an upload with Muse and return a draft. Nothing is stored; the bytes are dropped."""
import base64
import binascii
import concurrent.futures
import contextvars
from datetime import datetime

from ..compiler.perceive import perceive_frame
from ..llm.base import LLMClient
from ..llm.metered import usage_purpose
from .draft import Draft, build_draft
from .media_info import MediaError, check_image, check_wav, read_exif

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_NOTE_CHARS = 5000
MAX_VIDEO_FRAMES = 8
READ_WORKERS = 4                 # frames read at the same time: a clip takes about as long as one photo


class TooLarge(ValueError):
    pass


class BadRequest(ValueError):
    pass


def _decode(data_b64: str | None, limit: int, what: str) -> bytes:
    if not data_b64:
        raise BadRequest(f"{what} is required")
    if len(data_b64) > limit * 4 // 3 + 8:          # checked before decoding anything
        raise TooLarge(f"{what} is larger than {limit // (1024 * 1024)} MB")
    try:
        return base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise BadRequest(f"{what} is not valid base64") from None


def local_iso(value: str | None) -> str | None:
    """A browser-supplied file time as naive ISO seconds, or None when it cannot be read."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return None


def _day(iso: str | None) -> str | None:
    """The memory day (YYYY-MM-DD) of a capture time, when it is known."""
    return iso[:10] if iso else None


def _read_frames(llm: LLMClient, images: list[bytes]) -> list[dict]:
    """Read every frame, a few at a time, keeping their order. Each reading runs in a copy of this request's context,
    so the usage purpose and the progress count follow it."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(images))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, perceive_frame, llm, image) for image in images]
        return [f.result().model_dump() for f in futures]


def build_preview(llm: LLMClient, kind: str, *, data_b64: str | None = None,
                  frames_b64: list[str] | None = None, frame_offsets_ms: list[int] | None = None,
                  audio_b64: str | None = None, text: str | None = None,
                  file_modified_at: str | None = None) -> Draft:
    when = local_iso(file_modified_at)
    if kind == "note":
        if not (text or "").strip():
            raise BadRequest("the note is empty")
        if len(text) > MAX_NOTE_CHARS:
            raise BadRequest(f"the note is longer than {MAX_NOTE_CHARS} characters")
        return build_draft("note", text=text.strip(), file_modified_at=when)

    if kind == "frame":
        image = _decode(data_b64, MAX_IMAGE_BYTES, "the image")
        check_image(image)
        exif = read_exif(image)
        with usage_purpose("read_memory", _day(exif.taken_at or when)):
            perception = perceive_frame(llm, image).model_dump()
        del image
        return build_draft("frame", perceptions=[perception], frame_offsets_ms=[0], exif=exif,
                           file_modified_at=when)

    if kind == "audio":
        audio = _decode(data_b64, MAX_AUDIO_BYTES, "the audio")
        check_wav(audio)
        with usage_purpose("read_memory", _day(when)):
            turns = llm.transcribe(audio, None)
        del audio
        return build_draft("audio", turns=turns, file_modified_at=when)

    if kind == "video":
        frames, offsets = frames_b64 or [], frame_offsets_ms or []
        if not 1 <= len(frames) <= MAX_VIDEO_FRAMES or len(frames) != len(offsets):
            raise BadRequest(f"send 1 to {MAX_VIDEO_FRAMES} frames with one offset each")
        images = [_decode(f, MAX_IMAGE_BYTES, "a video frame") for f in frames]
        for image in images:
            check_image(image)
        audio = _decode(audio_b64, MAX_AUDIO_BYTES, "the audio") if audio_b64 else None
        if audio is not None:
            check_wav(audio)
        with usage_purpose("read_memory", _day(when)):
            # Speech and vision are independent. Copy metering/progress context into both workers.
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                vision = pool.submit(contextvars.copy_context().run, _read_frames, llm, images)
                speech = (pool.submit(contextvars.copy_context().run, llm.transcribe, audio, None)
                          if audio is not None else None)
                perceptions = vision.result()
                turns = speech.result() if speech is not None else None
        del images, audio
        return build_draft("video", perceptions=perceptions, frame_offsets_ms=list(offsets),
                           turns=turns, file_modified_at=when)

    raise BadRequest("kind must be frame, audio, video or note")


__all__ = ["BadRequest", "MediaError", "TooLarge", "build_preview", "local_iso"]
