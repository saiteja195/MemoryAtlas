"""Turn a confirmed draft into stored memories.

Every privacy decision here is code: who must answer, who has consented, and which grants are
created. A person who says no (or is not answered for) means nothing is stored and no grant is
created. Muse is not called again; the draft already holds its output as text.
"""
import re
import sqlite3
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from ..compiler.perceive import merge_perceptions, split_for_extraction
from ..engine import MemoryEngine
from ..privacy.consent import active_grant, create_grant
from .draft import Draft
from .models import RawCapture
from .preview import local_iso


class CommitError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class PersonAnswer(BaseModel):
    ref: str
    name: str | None = None
    consented: bool


class Answers(BaseModel):
    when: str | None = None
    where: str | None = Field(default=None, max_length=200)
    owner_speaker: str | None = None
    people: list[PersonAnswer] = Field(default_factory=list)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


class _Plan(BaseModel):
    captured_at: str
    place_name: str | None
    owner_speaker: str | None
    others: list[tuple[str, str]]       # (speaker label, person id), only people with a voice
    names: dict[str, str]               # person id -> display name
    declined: bool


def plan(draft: Draft, answers: Answers, owner: str) -> _Plan:
    """Validate the answers against the draft. Raises CommitError(422); changes nothing."""
    # A time the person gave wins over the one Muse or the file supplied: file dates are often just the
    # download time.
    given = local_iso(answers.when) if answers.when else None
    if answers.when and given is None:
        raise CommitError(422, "the time you gave could not be read")
    captured_at = given or draft.captured_at
    if not captured_at:
        raise CommitError(422, "when this happened is required")

    by_ref = {p.ref: p for p in answers.people}
    owner_speaker = None
    labels: list[str] = []
    if draft.turns is not None and len(draft.speakers) >= 2:
        owner_speaker = answers.owner_speaker
        if owner_speaker not in draft.speakers:
            raise CommitError(422, "say which speaker is you")
        labels = [s for s in draft.speakers if s != owner_speaker]
    elif draft.speakers:
        owner_speaker = draft.speakers[0]

    visible = [q.ref for q in draft.questions if q.ref and q.ref.startswith("visible")]
    declined, others, names = False, [], {}
    for ref in [*labels, *visible]:
        answer = by_ref.get(ref)
        if answer is None:
            raise CommitError(422, f"answer whether {ref} agreed to be included")
        if not answer.consented:
            declined = True
            continue
        if ref in labels:
            name = (answer.name or "").strip()
            if not name:
                raise CommitError(422, f"give a name for speaker {ref}")
            person = slug(name)
            if not person or person == owner:
                raise CommitError(422, f"{name!r} cannot be used as a name for someone else")
            others.append((ref, person))
            names[person] = name
    return _Plan(captured_at=captured_at, place_name=answers.where or draft.place_name,
                 owner_speaker=owner_speaker, others=others, names=names, declined=declined)


def _shift(iso: str, ms: int) -> str:
    return (datetime.fromisoformat(iso) + timedelta(milliseconds=ms)).isoformat(timespec="seconds")


def _grant(conn: sqlite3.Connection, secret: str, person: str, session: str, out: list[dict]) -> None:
    if active_grant(conn, person, session):
        return
    gid, token = create_grant(conn, secret, person, session)
    out.append({"person": person, "grant_id": gid, "revocation_token": token})


def commit(conn: sqlite3.Connection, engine: MemoryEngine, secret: str, draft: Draft,
           p: _Plan) -> dict:
    owner = engine.gateway.owner
    session = f"upload-{p.captured_at[:10]}"
    if p.declined:
        return {"session_id": session, "grants": [],
                "results": [{"status": "rejected", "reason": "no_consent", "source_id": None,
                             "claims": 0, "compile_rejected": None}]}

    grants: list[dict] = []
    _grant(conn, secret, owner, session, grants)
    for _, person in p.others:
        _grant(conn, secret, person, session, grants)
    for person, name in p.names.items():
        engine.gateway.names[person] = name

    caps: list[RawCapture] = []
    if draft.kind == "note":
        caps.append(RawCapture(kind="note", session_id=session, captured_at=p.captured_at, text=draft.text))
    if draft.kind in ("video", "photos") and draft.perceptions:
        # The frames' (or photos') findings merged into one memory, so saving costs a few extraction calls for the whole
        # clip or set, not one each.
        merged = merge_perceptions(draft.perceptions, "Video" if draft.kind == "video" else "Photo")
        for part in split_for_extraction(merged):
            caps.append(RawCapture(kind="frame", session_id=session, captured_at=p.captured_at, lat=draft.lat,
                                   lon=draft.lon, perception=part, place_name=p.place_name))
    else:
        for perception, offset in zip(draft.perceptions, draft.frame_offsets_ms):
            caps.append(RawCapture(kind="frame", session_id=session, captured_at=_shift(p.captured_at, offset),
                                   lat=draft.lat, lon=draft.lon, perception=perception, place_name=p.place_name))
    if draft.turns is not None:
        speaker_map = {label: person for label, person in p.others}
        if p.owner_speaker is not None:
            speaker_map[p.owner_speaker] = owner
        caps.append(RawCapture(kind="audio", session_id=session, captured_at=p.captured_at,
                               turns=draft.turns, participants=[person for _, person in p.others],
                               speaker_map=speaker_map))

    results = []
    for cap in caps:
        for r in engine.ingest(cap):
            results.append({
                "status": r.ingest.status, "reason": r.ingest.reason,
                "source_id": r.ingest.observation.source_id if r.ingest.observation else None,
                "claims": len(r.compiled.claim_ids) if r.compiled else 0,
                "compile_rejected": r.compiled.rejected if r.compiled else None})
    return {"session_id": session, "grants": grants, "results": results}
