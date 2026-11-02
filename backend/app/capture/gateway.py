"""Privacy & Capture Gateway.

Order of operations per capture: consent check, perceive/transcribe, local redaction, hash,
blocked-hash check, insert a text-only source row, drop the raw bytes. Nothing but text and a
content hash is stored, and `media_bytes_retained` is always 0.
"""
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta

from ..compiler.perceive import parse_perception, perceive_frame, perception_to_text
from ..llm.base import LLMClient
from ..privacy.consent import active_grant
from .models import IngestResult, Observation, RawCapture
from .redact import redact

_KIND = {"frame": "frame_observation", "audio": "transcript_segment",
         "calendar": "calendar_event", "note": "user_confirmation"}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def hhmm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M")


class Gateway:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient, owner: str = "me",
                 names: dict[str, str] | None = None):
        self.conn, self.llm, self.owner = conn, llm, owner
        self.names = names or {}

    def display(self, person_id: str) -> str:
        return self.names.get(person_id) or ("Me" if person_id == self.owner else person_id.title())

    # -- entry point --------------------------------------------------------------------------

    def ingest(self, cap: RawCapture) -> list[IngestResult]:
        try:
            if cap.kind == "audio":
                return self._audio(cap)
            if cap.kind in ("frame", "calendar", "note"):
                return [self._single(cap)]
            return [IngestResult("rejected", "bad_input", ref=cap.ref)]
        finally:
            cap.image = None  # the ephemeral buffer: raw bytes never outlive the call
            cap.audio = None

    # -- per kind -----------------------------------------------------------------------------

    def _single(self, cap: RawCapture) -> IngestResult:
        grant = active_grant(self.conn, self.owner, cap.session_id)
        if not grant:
            return IngestResult("rejected", "no_consent", ref=cap.ref)
        if cap.kind == "frame":
            if cap.image is not None:
                perception = perceive_frame(self.llm, cap.image)
            elif cap.perception is not None:
                perception = parse_perception(cap.perception)
            else:
                return IngestResult("rejected", "bad_input", ref=cap.ref)
            text = perception_to_text(perception, cap.place_name)
        elif cap.kind == "calendar":
            if not cap.text:
                return IngestResult("rejected", "bad_input", ref=cap.ref)
            when = hhmm(cap.captured_at) + (f"-{hhmm(cap.ends_at)}" if cap.ends_at else "")
            where = f" at {cap.place_name}" if cap.place_name else ""
            who = (" Attendees: " + ", ".join(self.display(a) for a in cap.attendees) + "."
                   if cap.attendees else "")
            text = f"Calendar event: {cap.text}{where}, {when}.{who}"
        else:
            text = cap.text or ""
        return self._store(cap, _KIND[cap.kind], text, cap.captured_at, grant)

    def _audio(self, cap: RawCapture) -> list[IngestResult]:
        people = list(dict.fromkeys([self.owner, *cap.participants]))
        grants = {p: active_grant(self.conn, p, cap.session_id) for p in people}
        if not all(grants.values()):
            # Checked before any audio is sent to a transcription service.
            return [IngestResult("rejected", "no_consent", ref=cap.ref)]
        if cap.audio is not None:
            keywords = cap.keywords + [self.display(p) for p in people if p != self.owner]
            turns = self.llm.transcribe(cap.audio, keywords or None)
        elif cap.turns is not None:
            turns = cap.turns
        else:
            return [IngestResult("rejected", "bad_input", ref=cap.ref)]
        start = datetime.fromisoformat(cap.captured_at)
        fallback = next((g for p, g in grants.items() if p != self.owner), grants[self.owner])
        results = []
        for t in turns:
            who = cap.speaker_map.get(str(t.get("speaker")))
            label = self.display(who) if who else f"Speaker {t.get('speaker') or '?'}"
            # A segment is stored under the speaker's own grant. If the speaker is unknown it
            # goes under another participant's grant, so withdrawing that consent removes it.
            grant = grants.get(who) or fallback
            at = (start + timedelta(milliseconds=int(t.get("start_ms", 0)))).isoformat()
            res = self._store(cap, "transcript_segment", f"{label}: {t.get('text', '').strip()}",
                              at, grant, speaker=who,
                              participants=[self.display(p) for p in people])
            results.append(res)
        return results

    # -- storage ------------------------------------------------------------------------------

    def _store(self, cap: RawCapture, kind: str, text: str, captured_at: str, grant_id: str,
               speaker: str | None = None, participants: list[str] | None = None) -> IngestResult:
        text, _counts = redact(text)
        text = text.strip()
        if not text:
            return IngestResult("rejected", "empty", ref=cap.ref)
        chash = content_hash(text)
        if self.conn.execute("SELECT 1 FROM blocked_hashes WHERE content_hash=?",
                             (chash,)).fetchone():
            return IngestResult("rejected", "blocked", ref=cap.ref)
        source_id = "src-" + hashlib.sha1(f"{kind}|{captured_at}|{chash}".encode()).hexdigest()[:12]
        if self.conn.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone():
            return IngestResult("rejected", "duplicate", ref=cap.ref)
        self.conn.execute(
            "INSERT INTO sources(source_id, kind, session_id, grant_id, captured_at, ingested_at,"
            " lat, lon, text, content_hash, media_bytes_retained, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,0,'active')",
            (source_id, kind, cap.session_id, grant_id, captured_at,
             datetime.now().isoformat(timespec="seconds"), cap.lat, cap.lon, text, chash))
        self.conn.commit()
        obs = Observation(source_id, kind, text, captured_at, cap.session_id, grant_id,
                          cap.lat, cap.lon, cap.ends_at if kind == "calendar_event" else None,
                          speaker, participants or [], cap.place_name)
        return IngestResult("ingested", observation=obs, ref=cap.ref)

