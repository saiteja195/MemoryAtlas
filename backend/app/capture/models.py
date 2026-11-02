from dataclasses import dataclass, field
from typing import Any

KINDS = ("frame", "audio", "calendar", "note")


@dataclass
class RawCapture:
    """What an adapter hands to the gateway. Raw bytes exist only on this object and are
    cleared by the gateway before it returns."""

    kind: str                              # frame | audio | calendar | note
    session_id: str
    captured_at: str                       # ISO event time (naive, local)
    lat: float | None = None
    lon: float | None = None
    image: bytes | None = None             # frame: raw image
    perception: dict[str, Any] | None = None   # frame: pre-supplied (fixtures, tests)
    audio: bytes | None = None             # audio: mono 16-bit PCM WAV
    turns: list[dict[str, Any]] | None = None  # audio: pre-supplied diarized turns
    text: str | None = None                # calendar title / note text
    ends_at: str | None = None             # calendar end
    place_name: str | None = None
    attendees: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)   # biases speech recognition
    participants: list[str] = field(default_factory=list)       # person ids in the session
    speaker_map: dict[str, str] = field(default_factory=dict)   # diarization label -> person id
    ref: str | None = None                 # adapter-side id (e.g. "F1"), for logs only


@dataclass
class Observation:
    """A text-only observation that passed the gateway and is stored as a `sources` row."""

    source_id: str
    kind: str                              # sources.kind
    text: str
    captured_at: str
    session_id: str
    grant_id: str
    lat: float | None = None
    lon: float | None = None
    ends_at: str | None = None             # calendar only; used for episode extent
    speaker: str | None = None             # person id for transcript segments
    participants: list[str] = field(default_factory=list)   # names in the conversation
    place_name: str | None = None


@dataclass
class IngestResult:
    status: str                            # ingested | rejected
    reason: str | None = None              # no_consent | blocked | duplicate | empty | bad_input
    observation: Observation | None = None
    ref: str | None = None
