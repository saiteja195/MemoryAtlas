"""Build the two published demo profiles: register them, run their content through the real pipeline, and
save a text-only snapshot. Raw photos, audio and GPS never reach the snapshot: the media is read once,
turned into text by Muse, and dropped, exactly as an upload is."""
import base64
import os
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

import yaml

from ..capture.commit import Answers, CommitError, PersonAnswer, commit, plan
from ..capture.draft import Draft
from ..capture.media_info import MediaError
from ..capture.preview import BadRequest, build_preview
from ..config import Settings
from ..llm.base import LLMClient
from . import snapshots
from .registry import Profile, Registry
from .runtime import ProfileRuntime, Runtimes

KINDS = ("staged", "real")
_FILE_KEYS = {"captured_at", "where", "owner_speaker", "people", "skip"}
_PERSON_KEYS = {"ref", "name", "consented"}
_KIND_BY_EXT = {".jpg": "frame", ".jpeg": "frame", ".png": "frame", ".wav": "audio", ".txt": "note"}
MANIFEST = "manifest.yaml"


def strip_gps(draft: Draft) -> Draft:
    """The demo shows what Atlas understood, never where a real person was."""
    return draft.model_copy(update={"lat": None, "lon": None})


def load_manifest(path: str, filenames: list[str] | None = None) -> dict[str, dict]:
    """The owner's decision for every media file: answers to what Muse could not know, or `skip: true`."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    files = raw.get("files")
    if not isinstance(files, dict) or set(raw) - {"files"}:
        raise ValueError("manifest.yaml must contain a single `files:` mapping")
    for name, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{name}: expected a mapping of answers")
        unknown = set(entry) - _FILE_KEYS
        if unknown:
            raise ValueError(f"{name}: unknown key(s) {', '.join(sorted(unknown))}")
        for person in entry.get("people") or []:
            bad = set(person) - _PERSON_KEYS if isinstance(person, dict) else {"?"}
            if bad:
                raise ValueError(f"{name}: unknown person key(s) {', '.join(sorted(map(str, bad)))}")
    missing = [f for f in (filenames or []) if f not in files]
    if missing:
        raise ValueError("no decision in the manifest for: " + ", ".join(sorted(missing)))
    return files


def _credentials(kind: str, env: Mapping[str, str]) -> tuple[str, str]:
    name_var, code_var = f"DEMO_{kind.upper()}_NAME", f"DEMO_{kind.upper()}_PASSCODE"
    missing = [v for v in (name_var, code_var) if not env.get(v)]
    if missing:
        raise SystemExit("set " + " and ".join(missing) + " in the environment")
    return env[name_var], env[code_var]


def _profile(registry: Registry, kind: str, env: Mapping[str, str]) -> Profile:
    from .registry import NameTaken
    name, passcode = _credentials(kind, env)
    try:
        return registry.create(name, passcode, demo_kind=kind)
    except NameTaken:
        profile = registry.authenticate(name, passcode)          # same credentials: reuse the profile
        if profile.demo_kind != kind:
            raise SystemExit(f"{name!r} exists but is not the {kind} demo profile") from None
        return profile


def register(kind: str, *, data_dir: str, env: Mapping[str, str], say: Callable[..., None] = print) -> Profile:
    """Create the demo profile's row (no content). On first sign-in its snapshot is loaded."""
    os.makedirs(data_dir, exist_ok=True)
    profile = _profile(Registry(os.path.join(data_dir, "profiles.db")), kind, env)
    say(f"{kind} demo profile ready: {profile.name!r}")
    return profile


def _seed_staged(rt: ProfileRuntime) -> None:
    rt.demo.reset()
    rt.demo.advance(50)
    for event_id in rt.demo.status()["live_uploads"]:
        rt.demo.play(event_id)


def _plan_media(llm: LLMClient, rt: ProfileRuntime, media_dir: str, say: Callable[..., None]) -> list:
    manifest_path = os.path.join(media_dir, MANIFEST)
    if not os.path.isfile(manifest_path):
        raise SystemExit(f"{media_dir} needs a {MANIFEST} (copy fixtures/profiles/real/manifest.example.yaml)")
    names = sorted(f for f in os.listdir(media_dir) if f != MANIFEST and not f.startswith("."))
    try:
        manifest = load_manifest(manifest_path, names)
    except ValueError as e:
        raise SystemExit(str(e)) from None
    planned = []
    for name in names:
        entry = manifest[name]
        if entry.get("skip"):
            say(f"  skipped {name}")
            continue
        path = os.path.join(media_dir, name)
        kind = _KIND_BY_EXT.get(os.path.splitext(name)[1].lower())
        if kind is None:
            raise SystemExit(f"{name}: unsupported file type (use jpg, png, wav or txt)")
        try:
            if kind == "note":
                draft = build_preview(llm, "note", text=Path(path).read_text())
            else:
                data = base64.b64encode(Path(path).read_bytes()).decode()
                draft = build_preview(llm, kind, data_b64=data)
            draft = strip_gps(draft)
            answers = Answers(
                when=entry.get("captured_at"), where=entry.get("where"), owner_speaker=entry.get("owner_speaker"),
                people=[PersonAnswer(ref=str(p["ref"]), name=p.get("name"), consented=bool(p.get("consented")))
                        for p in entry.get("people") or []])
            decided = plan(draft, answers, rt.engine.gateway.owner)
        except CommitError as e:
            hint = " (set captured_at in the manifest; a file's own date is not trusted)" if "when" in e.message else ""
            raise SystemExit(f"{name}: {e.message}{hint}") from None
        except (BadRequest, MediaError) as e:
            raise SystemExit(f"{name}: {e}") from None
        if decided.declined:
            say(f"  {name}: someone in it did not agree, so it is not included")
            continue
        planned.append((name, draft, decided))
    return planned


def _seed_real(llm: LLMClient, rt: ProfileRuntime, media_dir: str, say: Callable[..., None]) -> None:
    if not media_dir:
        raise SystemExit("the real demo profile needs --media DIR (photos, wav, txt and a manifest.yaml)")
    planned = _plan_media(llm, rt, media_dir, say)           # nothing is stored until every file is accepted
    for name, draft, decided in planned:
        out = commit(rt.conn, rt.engine, rt.settings.revocation_secret, draft, decided)
        say(f"  stored {name}: {sum(r['claims'] for r in out['results'])} claims")


def _snapshot(conn: sqlite3.Connection, out: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)
    conn.commit()
    conn.execute("VACUUM INTO ?", (out,))


def seed(kind: str, *, data_dir: str, out: str | None = None, media_dir: str | None = None,
         env: Mapping[str, str] = os.environ, llm: LLMClient | None = None,
         say: Callable[..., None] = print) -> str:
    """Build `kind`'s content in a scratch data directory and write its snapshot. Returns the snapshot path."""
    if kind not in KINDS:
        raise SystemExit(f"kind must be one of {', '.join(KINDS)}")
    _credentials(kind, env)
    settings = Settings(llm_mode="live", auth=True, db_path=os.path.join(data_dir, "unused.db"),
                        data_dir=data_dir)
    profile = register(kind, data_dir=data_dir, env=env, say=say)
    runtimes = Runtimes(settings, llm, data_dir)
    try:
        rt = runtimes.get(profile.profile_id, profile.name, False)
        if rt.conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
            raise SystemExit(f"{data_dir} already holds memories for this profile; use an empty --data-dir")
        if kind == "staged":
            _seed_staged(rt)
        else:
            _seed_real(rt.llm, rt, media_dir or "", say)
        say("Stored claims (review every line before committing the snapshot):")
        for row in rt.conn.execute("SELECT text FROM claims WHERE status='active' ORDER BY created_at, claim_id"):
            say("  - " + row["text"])
        target = out or snapshots.snapshot_path(kind)
        _snapshot(rt.conn, target)
        say(f"Snapshot written to {target}")
        return target
    finally:
        runtimes.close_all()
