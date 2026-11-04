"""Everything one person's memory needs, built once and cached: connection, engine, demo runner, recall,
revocation and drafts. Two profiles never share any of it, so isolation is a file boundary."""
import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, replace

from .. import db
from ..capture.adapters import MockDayAdapter
from ..capture.draft import DraftStore
from ..config import Settings, runtime_cache_path
from ..demo import DemoRunner
from ..demo_acts import load_acts
from ..engine import MemoryEngine
from ..llm.base import LLMClient
from ..llm.factory import build_client
from ..llm.metered import MeteredLLM
from ..privacy.revocation import RevocationEngine
from ..recall.service import RecallService

log = logging.getLogger("memoryatlas")


@dataclass
class ProfileRuntime:
    profile_id: str
    owner_name: str
    conn: sqlite3.Connection
    engine: MemoryEngine
    demo: DemoRunner
    recall: RecallService
    revoker: RevocationEngine
    drafts: DraftStore
    llm: LLMClient
    sweep_lock: threading.Lock
    db_path: str | None
    cache_dir: str
    settings: Settings
    demo_ready: bool = False        # a demo profile's runtime has been prepared (tokens, played state)

    def sweep(self) -> list[dict]:
        """Purge grants that have expired. Safe to call at any time; one at a time. A failed purge must
        not take the API down: the privacy filter still refuses the data."""
        with self.sweep_lock:
            try:
                return self.revoker.sweep()
            except Exception:
                log.exception("expiry sweep failed")
                return []

    def close(self) -> None:
        flush = getattr(self.llm, "flush", None)
        if flush:
            flush()                      # usage rows still held back go out before the connection closes
        try:
            self.conn.close()
        except sqlite3.Error:
            log.exception("closing a profile database failed")


class ProfileGone(Exception):
    """The profile was deleted; nothing may be built or opened for it again."""


class Runtimes:
    """One runtime per profile. Each profile has its own lock, so building or swapping one never stalls another;
    `exclusive` lets a caller hold a profile still while its files are replaced."""

    def __init__(self, settings: Settings, llm: LLMClient | None, root: str | None):
        self.settings, self.llm, self.root = settings, llm, root
        self._by_id: dict[str, ProfileRuntime] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._gone: set[str] = set()                # ids are random and never reused, so this stays small
        self._lock = threading.Lock()               # guards the three dicts above, never held while building

    def exclusive(self, profile_id: str) -> threading.RLock:
        """Hold this (`with runtimes.exclusive(pid):`) while evicting and replacing a profile's files."""
        with self._lock:
            return self._locks.setdefault(profile_id, threading.RLock())

    def get(self, profile_id: str, owner_name: str, seed_demo: bool) -> ProfileRuntime:
        with self.exclusive(profile_id):
            if profile_id in self._gone:
                raise ProfileGone(profile_id)
            with self._lock:
                rt = self._by_id.get(profile_id)
            if rt is None:
                rt = self._build(profile_id, owner_name, seed_demo)
                with self._lock:
                    self._by_id[profile_id] = rt
            return rt

    def evict(self, profile_id: str) -> None:
        with self.exclusive(profile_id):
            with self._lock:
                rt = self._by_id.pop(profile_id, None)
            if rt is not None:
                rt.close()

    def forget(self, profile_id: str) -> None:
        """The profile is being deleted: close it, and refuse every later `get`, so a request that was already
        in flight cannot recreate its files."""
        with self.exclusive(profile_id):
            self._gone.add(profile_id)
            self.evict(profile_id)

    def close_all(self) -> None:
        with self._lock:
            runtimes, self._by_id = list(self._by_id.values()), {}
        for rt in runtimes:
            rt.close()

    def close_all(self) -> None:
        with self._lock:
            runtimes, self._by_id = list(self._by_id.values()), {}
        for rt in runtimes:
            rt.close()

    def profile_dir(self, profile_id: str) -> str:
        assert self.root is not None
        return os.path.join(self.root, "profiles", profile_id)

    def _build(self, profile_id: str, owner_name: str, seed_demo: bool) -> ProfileRuntime:
        if self.root is None:
            s = replace(self.settings, runtime_cache_dir=runtime_cache_path(self.settings))
        else:
            d = self.profile_dir(profile_id)
            os.makedirs(d, exist_ok=True)
            s = replace(self.settings, db_path=os.path.join(d, "memoryatlas.db"),
                        runtime_cache_dir=os.path.join(d, "llmcache"))
        conn = db.connect(s.db_path)
        llm = MeteredLLM(self.llm or build_client(s), conn, {"text": s.llm_model, "asr": s.asr_model})
        adapter = MockDayAdapter(s.demo_script)
        engine = MemoryEngine(conn, llm, adapter.owner, adapter.names)
        demo = DemoRunner(engine, adapter, s.revocation_secret, seed=seed_demo)
        # A profile that did not start from the staged day still needs its own owner entity.
        engine.compiler.resolver.ensure_owner(adapter.names.get(adapter.owner, "Me"))
        conn.commit()
        try:
            red_team = [q["question"] for q in load_acts().get("red_team", [])]
        except OSError:
            red_team = []
        revoker = RevocationEngine(
            conn, s.revocation_secret, llm, adapter.owner,
            db_path=None if s.db_path == ":memory:" else os.path.abspath(s.db_path),
            cache_dir=s.runtime_cache_dir, red_team_questions=red_team)
        rt = ProfileRuntime(
            profile_id=profile_id, owner_name=owner_name, conn=conn, engine=engine, demo=demo,
            recall=RecallService(conn, llm), revoker=revoker, drafts=DraftStore(), llm=llm,
            sweep_lock=threading.Lock(),
            db_path=None if s.db_path == ":memory:" else os.path.abspath(s.db_path),
            cache_dir=s.runtime_cache_dir, settings=s)
        rt.sweep()                       # anything that lapsed while the app was off
        return rt
