"""One clock for consent expiry, so tests can move time and every comparison uses the same format."""
from datetime import datetime, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """UTC, fixed width, so stored times compare correctly as text (also in SQL)."""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def now_iso() -> str:
    return iso(now())
