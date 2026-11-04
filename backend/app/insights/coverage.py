"""How much of a day the memory covers: which waking hours hold readable material, where the
longest silence sits, and which hour was busiest. A pure read over the profile's database.

Only sources the privacy filter still allows count, and an episode contributes only through the
observations behind it that are still readable, so a withdrawn or expired source leaves no trace
here even before the purge has run. Stored times are naive local wall-clock ISO strings, so no
timezone conversion happens anywhere in this module.
"""
import json
import sqlite3
from datetime import datetime, timedelta

from ..compiler.episodes import reconstruct_contrib
from ..privacy.filter import valid_source_ids

DAY_MINUTES = 24 * 60


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _readable_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    live = valid_source_ids(conn)
    return [r for r in conn.execute("SELECT source_id, captured_at FROM sources ORDER BY captured_at")
            if r["source_id"] in live]


def memory_days(conn: sqlite3.Connection) -> list[str]:
    """Days (YYYY-MM-DD) with at least one readable source, oldest first."""
    return sorted({r["captured_at"][:10] for r in _readable_sources(conn)})


def _episode_spans(conn: sqlite3.Connection, live: set[str], day: datetime) -> list[tuple[int, int]]:
    """Minutes-of-day spans of the readable observations behind episodes, cut at this day's edges."""
    lo, hi = day, day + timedelta(days=1)
    spans = []
    for row in conn.execute("SELECT entity_id, attrs FROM entities WHERE type='episode'"):
        attrs = json.loads(row["attrs"] or "{}")
        contrib = attrs.get("contrib")
        if contrib is None:      # written before provenance was recorded: rebuild it from live claims
            contrib = reconstruct_contrib(conn, row["entity_id"], attrs, fallback=False)
        for c in contrib:
            if c.get("source_id") not in live:
                continue
            start, end = datetime.fromisoformat(c["start"]), datetime.fromisoformat(c["end"])
            if end < lo or start >= hi or (end == lo and start < lo):   # an episode only touching the edge
                continue
            start, end = max(start, lo), min(end, hi)
            spans.append((int((start - lo).total_seconds() // 60), int((end - lo).total_seconds() // 60)))
    return spans


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def coverage(conn: sqlite3.Connection, day: str, window: tuple[int, int] = (6, 22)) -> dict:
    first, last = window
    midnight = datetime.fromisoformat(day)
    live = valid_source_ids(conn)
    points = []                                  # minute-of-day of each readable source on this day
    for r in conn.execute("SELECT source_id, captured_at FROM sources WHERE substr(captured_at,1,10)=?"
                          " ORDER BY captured_at", (day,)):
        if r["source_id"] in live:
            t = datetime.fromisoformat(r["captured_at"])
            points.append(t.hour * 60 + t.minute)
    spans = _merge([(m, m) for m in points] + _episode_spans(conn, live, midnight))

    hours = []
    for h in range(first, last):
        lo, hi = h * 60, (h + 1) * 60
        # A span touches the hour when it starts inside it, or runs into it (an instant at its
        # start counts, a span that ends exactly on the hour boundary does not).
        covered = any(s < hi and (e > lo or s == e >= lo) for s, e in spans)
        hours.append({"hour": h, "covered": covered, "count": sum(lo <= m < hi for m in points)})
    covered_hours = sum(h["covered"] for h in hours)
    waking = last - first
    top = max((h["count"] for h in hours), default=0)
    busiest = next((h["hour"] for h in hours if h["count"] == top), None) if top else None

    gap = None
    if spans:
        w0, w1 = first * 60, last * 60
        inside = [(max(s, w0), min(e, w1)) for s, e in spans if e >= w0 and s <= w1]
        edges = [w0] + [x for s, e in inside for x in (s, e)] + [w1]
        # consecutive (end of one span, start of the next), plus the leading and trailing edges
        for a, b in zip(edges[0::2], edges[1::2]):
            if b - a > (gap["minutes"] if gap else 0):
                gap = {"start": _hhmm(a), "end": _hhmm(b), "minutes": b - a}
    return {"day": day, "window": [first, last],
            "hours": hours,
            "spans": [{"start": _hhmm(s), "end": _hhmm(e)} for s, e in spans],
            "covered_hours": covered_hours, "waking_hours": waking,
            "share": round(covered_hours / waking, 4) if waking else 0,
            "busiest_hour": busiest, "longest_gap": gap}
