import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Deleted rows are overwritten with zeros instead of lingering in free pages: forgetting
    # must also hold for the database file itself.
    conn.execute("PRAGMA secure_delete = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_PATH.read_text())
    from .migrate import upgrade
    upgrade(conn)
    return conn


_TABLES_IN_DELETE_ORDER = [
    "justification_premises", "justifications", "claim_index", "claim_vectors", "answer_cache",
    "chat_messages", "forgetting_receipts", "todo_state", "claims", "source_consents", "sources", "consent_grants",
    "entities",
    "blocked_hashes",
]


def reset(conn: sqlite3.Connection) -> None:
    """Empty every table (used by /demo/reset)."""
    for t in _TABLES_IN_DELETE_ORDER:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
