import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class _Fetched:
    """The rows of one statement, read inside the lock, so no other thread can interleave with a half-read result."""

    def __init__(self, cur: sqlite3.Cursor):
        self._rows = cur.fetchall()
        self._i = 0
        self.rowcount, self.lastrowid, self.description = cur.rowcount, cur.lastrowid, cur.description

    def fetchone(self) -> Any:
        if self._i >= len(self._rows):
            return None
        self._i += 1
        return self._rows[self._i - 1]

    def fetchall(self) -> list[Any]:
        rows, self._i = self._rows[self._i:], len(self._rows)
        return rows

    def fetchmany(self, size: int = 1) -> list[Any]:
        rows = self._rows[self._i:self._i + size]
        self._i += len(rows)
        return rows

    def __iter__(self) -> Iterator[Any]:
        return iter(self.fetchall())


class SharedConnection:
    """One sqlite3 connection shared by every request thread of a profile. SQLite's own cursors are not safe to
    interleave on one connection (a read can come back torn, or fail with "API misuse"), and the dashboard asks for
    the graph, the insights and the to-dos at the same moment. Every statement here runs under one lock and hands
    back its rows already fetched; everything else is the plain connection."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.RLock()

    def execute(self, sql: str, params: Any = ()) -> _Fetched:
        with self._lock:
            return _Fetched(self._conn.execute(sql, params))

    def executemany(self, sql: str, seq: Any) -> _Fetched:
        with self._lock:
            return _Fetched(self._conn.executemany(sql, seq))

    def executescript(self, script: str) -> None:
        with self._lock:
            self._conn.executescript(script)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def row_factory(self) -> Any:
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._conn.row_factory = value

    def __getattr__(self, name: str) -> Any:        # in_transaction, total_changes, ...: read straight from the connection
        return getattr(self._conn, name)


def connect(path: str = ":memory:") -> "SharedConnection":
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Deleted rows are overwritten with zeros instead of lingering in free pages: forgetting
    # must also hold for the database file itself.
    conn.execute("PRAGMA secure_delete = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_PATH.read_text())
    shared = SharedConnection(conn)
    from .migrate import upgrade
    upgrade(shared)
    return shared


_TABLES_IN_DELETE_ORDER = [
    "justification_premises", "justifications", "claim_index", "claim_vectors", "answer_cache",
    "chat_messages", "forgetting_receipts", "todo_state", "claims", "source_consents", "sources", "consent_grants",
    "entities",
    "blocked_hashes",
]


def reset(conn: "SharedConnection") -> None:
    """Empty every table (used by /demo/reset)."""
    for t in _TABLES_IN_DELETE_ORDER:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
