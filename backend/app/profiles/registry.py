"""Who the profiles are. Holds names, passcode hashes, goals, consent and sign-in sessions; never any memory."""
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from .passcodes import burn_hash, hash_passcode, name_key, normalize_name, validate_passcode, verify_passcode

GOALS = ("remember_day", "trips", "work_meetings", "family_friends", "just_trying")
DEMO_KINDS = ("staged", "real")
MAX_FAILURES = 5
LOCK_SECONDS = 900.0
SESSION_SECONDS = 30 * 86400.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
  profile_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  name_key TEXT NOT NULL UNIQUE,
  salt TEXT NOT NULL,
  passcode_hash TEXT NOT NULL,
  goals_json TEXT NOT NULL DEFAULT '[]',
  consent_at TEXT,
  created_at TEXT NOT NULL,
  demo_kind TEXT,
  failed_count INTEGER NOT NULL DEFAULT 0,
  locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_profile ON sessions(profile_id);
"""


class NameTaken(Exception):
    pass


class BadCredentials(Exception):
    def __init__(self) -> None:
        super().__init__("Wrong name or passcode")


class Locked(Exception):
    def __init__(self, retry_after: float):
        super().__init__("Too many wrong passcodes. Try again later.")
        self.retry_after = retry_after


class TooManyProfiles(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    profile_id: str
    name: str
    goals: list[str]
    consent_at: str | None
    demo_kind: str | None
    created_at: str

    @property
    def onboarded(self) -> bool:
        return self.consent_at is not None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _check_goals(goals: list[str] | None) -> list[str]:
    goals = list(dict.fromkeys(goals or []))
    if len(goals) > len(GOALS) or any(g not in GOALS for g in goals):
        raise ValueError("unknown goal")
    return goals


class Registry:
    PHANTOM_LIMIT = 10_000          # unknown names remembered, so they lock exactly like real ones

    def __init__(self, path: str, clock: Callable[[], float] = time.time, max_profiles: int = 500):
        self.clock, self.max_profiles = clock, max_profiles
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA secure_delete = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(_SCHEMA)
        self._lock = threading.RLock()
        self._phantom: dict[str, tuple[int, float]] = {}      # name_key -> (failures, locked_until)

    # -- helpers ----------------------------------------------------------------------------------
    def _profile(self, row: sqlite3.Row) -> Profile:
        return Profile(row["profile_id"], row["name"], json.loads(row["goals_json"]),
                       row["consent_at"], row["demo_kind"], row["created_at"])

    def _iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")

    # -- profiles ---------------------------------------------------------------------------------
    def create(self, name: str, passcode: str, goals: list[str] | None = None,
               demo_kind: str | None = None) -> Profile:
        display = normalize_name(name)
        validate_passcode(passcode)
        goals = _check_goals(goals)
        if demo_kind is not None and demo_kind not in DEMO_KINDS:
            raise ValueError("unknown demo kind")
        salt, digest = hash_passcode(passcode)             # slow work stays outside the lock
        with self._lock:
            if self.count() >= self.max_profiles:
                raise TooManyProfiles()
            pid = secrets.token_hex(6)
            try:
                self.conn.execute(
                    "INSERT INTO profiles(profile_id, name, name_key, salt, passcode_hash, goals_json,"
                    " created_at, demo_kind) VALUES (?,?,?,?,?,?,?,?)",
                    (pid, display, name_key(display), salt, digest, json.dumps(goals), self._iso(),
                     demo_kind))
                self.conn.commit()
            except sqlite3.IntegrityError:
                self.conn.rollback()
                raise NameTaken() from None
            return self.get(pid)  # type: ignore[return-value]

    def authenticate(self, name: str, passcode: str) -> Profile:
        try:
            key = name_key(name)
        except ValueError:
            self._fail_unknown(" ".join(name.split()).casefold()[:100], passcode)
            raise BadCredentials() from None
        with self._lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE name_key=?", (key,)).fetchone()
        if row is None:
            self._fail_unknown(key, passcode)
            raise BadCredentials()
        now = self.clock()
        if row["locked_until"] > now:
            raise Locked(row["locked_until"] - now)
        ok = verify_passcode(passcode, row["salt"], row["passcode_hash"])
        with self._lock:
            if not ok and row["demo_kind"]:
                raise BadCredentials()          # a demo passcode is public, so locking it would only let anyone lock everyone out
            if ok:
                self.conn.execute("UPDATE profiles SET failed_count=0, locked_until=0 WHERE profile_id=?",
                                  (row["profile_id"],))
                self.conn.commit()
                return self._profile(row)
            fails = self.conn.execute("SELECT failed_count FROM profiles WHERE profile_id=?",
                                      (row["profile_id"],)).fetchone()
            fails = (fails["failed_count"] if fails else 0) + 1
            if fails >= MAX_FAILURES:
                self.conn.execute("UPDATE profiles SET failed_count=0, locked_until=? WHERE profile_id=?",
                                  (self.clock() + LOCK_SECONDS, row["profile_id"]))
            else:
                self.conn.execute("UPDATE profiles SET failed_count=? WHERE profile_id=?",
                                  (fails, row["profile_id"]))
            self.conn.commit()
        raise BadCredentials()

    def _fail_unknown(self, key: str, passcode: str) -> None:
        """An unknown name costs one hash and locks after five tries, so it cannot be told from a real one."""
        burn_hash(passcode)
        with self._lock:
            now = self.clock()
            fails, locked_until = self._phantom.get(key, (0, 0.0))
            if locked_until > now:
                raise Locked(locked_until - now)
            fails += 1
            if fails >= MAX_FAILURES:
                fails, locked_until = 0, now + LOCK_SECONDS
            if key not in self._phantom and len(self._phantom) >= self.PHANTOM_LIMIT:
                self._phantom.pop(next(iter(self._phantom)))
            self._phantom[key] = (fails, locked_until)

    def get(self, profile_id: str) -> Profile | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE profile_id=?", (profile_id,)).fetchone()
        return self._profile(row) if row else None

    def count(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]

    def set_goals(self, profile_id: str, goals: list[str]) -> None:
        goals = _check_goals(goals)
        with self._lock:
            self.conn.execute("UPDATE profiles SET goals_json=? WHERE profile_id=?",
                              (json.dumps(goals), profile_id))
            self.conn.commit()

    def accept_consent(self, profile_id: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE profiles SET consent_at=? WHERE profile_id=?",
                              (self._iso(), profile_id))
            self.conn.commit()

    def delete(self, profile_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM sessions WHERE profile_id=?", (profile_id,))
            self.conn.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))
            self.conn.commit()

    # -- sessions ---------------------------------------------------------------------------------
    def start_session(self, profile_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            self.conn.execute("INSERT INTO sessions(token_hash, profile_id, created_at, expires_at)"
                              " VALUES (?,?,?,?)", (_digest(token), profile_id, now, now + SESSION_SECONDS))
            self.conn.commit()
        return token

    def profile_for_token(self, token: str) -> Profile | None:
        if not token:
            return None
        digest = _digest(token)
        with self._lock:
            row = self.conn.execute("SELECT profile_id, expires_at FROM sessions WHERE token_hash=?",
                                    (digest,)).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= self.clock():
                self.conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
                self.conn.commit()
                return None
        return self.get(row["profile_id"])

    def end_session(self, token: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM sessions WHERE token_hash=?", (_digest(token),))
            self.conn.commit()
