"""The five extra recall tools, offered only to questions the router sends to the extended prompt.

  day_summary(time_from, time_to)  moments, people, places and counts for a window
  open_todos()                     the owner's open promises and the requests made of the owner
  coverage(time_from?, time_to?)   the spans the memory covers and the gaps, for one day
  usage_stats(day?)                how much the models read and answered (counts only)
  uncertain_claims()               claims that are disputed or low in confidence

They are deterministic code, like the original seven. Anything that shows a claim reads it through
the privacy filter (`RecallTools._claims` / `list_todos`) and records its id in `tools.returned`, so
a forgotten, expired or withdrawn claim never appears and a citation can be checked. `coverage` and
`usage_stats` show numbers, not claims: each keeps its raw result in `tools.stats_returned[<tool>]`
so the figures in an answer can be checked against it. Their results carry raw values and the same
values already formatted ("13:20", "4 h 25 min", "4,200"), so an answer may use either form.

What "uncertain" means here. A claim has a status (active, superseded, disputed, revoked) and a
confidence. There is no stored "partial" status or partial-support flag, so `uncertain_claims` reads
the two things that do exist: `status = 'disputed'` (the evidence conflicts) and `confidence < 0.6`
(the evidence is weak, including a claim only an inference supports). That is what "partial" maps to.
"""
import math
from datetime import datetime
from functools import partial
from typing import Any, Callable

from ..insights.coverage import coverage as day_coverage
from ..insights.coverage import memory_days
from ..insights.usage import usage_summary
from ..todos import list_todos
from .tools import HIDDEN_PREDICATES, MAX_K, RecallTools

LOW_CONFIDENCE = 0.6
MIN_GAP_MINUTES = 30          # shorter silences are not worth listing as gaps


def fmt_minutes(minutes: int) -> str:
    """265 -> "4 h 25 min", 45 -> "45 min", 120 -> "2 h"."""
    h, m = divmod(int(minutes), 60)
    if h == 0:
        return f"{m} min"
    return f"{h} h" if m == 0 else f"{h} h {m} min"


def _minute_of_day(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _span(start: str, end: str) -> dict[str, Any]:
    minutes = _minute_of_day(end) - _minute_of_day(start)
    return {"start": start, "end": end, "minutes": minutes, "duration": fmt_minutes(minutes)}


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


# -- day_summary ----------------------------------------------------------------------------------

def day_summary(tools: RecallTools, time_from: str, time_to: str) -> dict[str, Any]:
    moments = tools.episodes(time_from=time_from, time_to=time_to)
    rows = tools._claims("event_time >= ? AND event_time <= ?", (time_from, time_to))
    owner_ids = {tools.owner}
    people: set[str] = set()
    places: set[str] = set()
    for r in rows:
        for eid in (r["subject_id"], r["object_id"]):
            if eid is None or eid in owner_ids:
                continue
            e = tools.conn.execute("SELECT type, name FROM entities WHERE entity_id=?", (eid,)).fetchone()
            if e and e["type"] == "person":
                people.add(e["name"])
            elif e and e["type"] == "place":
                places.add(e["name"])
    shown = [r for r in rows if r["predicate"] not in (*HIDDEN_PREDICATES, "summary_of")]
    out: dict[str, Any] = {
        "window": {"from": time_from, "to": time_to},
        "moments": moments, "people": sorted(people), "places": sorted(places),
        "counts": {"moments": len(moments), "claims": len(shown), "people": len(people), "places": len(places)}}
    if not moments and not shown:
        hint = tools._outside_memory({"time_from": time_from, "time_to": time_to})
        out["note"] = hint["note"] if hint else "Nothing readable in that window."
    return out


# -- open_todos -----------------------------------------------------------------------------------

def open_todos(tools: RecallTools) -> list[dict[str, Any]]:
    out = []
    for t in list_todos(tools.conn, tools.owner, "open"):       # reads through the privacy filter
        tools.returned.add(t["claim_id"])
        out.append({"claim_id": t["claim_id"], "kind": t["kind"], "text": t["text"], "who": t["who"],
                    "when": t["when"], "source": t["source_label"], "state": t["state"]})
    return out


# -- coverage -------------------------------------------------------------------------------------

def _window(time_from: str | None, time_to: str | None) -> tuple[int, int] | None:
    """Whole hours around a window that lies inside one day, else None (the default waking hours)."""
    if not (time_from and time_to) or time_from[:10] != time_to[:10]:
        return None
    a, b = datetime.fromisoformat(time_from), datetime.fromisoformat(time_to)
    first = a.hour
    last = b.hour + (1 if (b.minute or b.second) else 0)
    return (first, min(last, 24)) if last > first else None


def coverage(tools: RecallTools, time_from: str | None = None, time_to: str | None = None) -> dict[str, Any]:
    days = memory_days(tools.conn)
    day = (time_from or time_to or "")[:10] or (days[-1] if days else "")
    if not day:
        return {"error": "no memory to cover yet"}
    try:
        datetime.fromisoformat(day)
        window = _window(time_from, time_to)
    except ValueError as e:
        return {"error": f"bad arguments for coverage: {e}"}
    raw = day_coverage(tools.conn, day, window) if window else day_coverage(tools.conn, day)
    first, last = raw["window"]
    spans = [_span(s["start"], s["end"]) for s in raw["spans"]]
    gaps: list[dict[str, Any]] = []
    if spans:
        cursor, w1 = first * 60, last * 60
        for s in raw["spans"]:
            lo, hi = _minute_of_day(s["start"]), _minute_of_day(s["end"])
            if hi < first * 60 or lo > w1:
                continue
            if lo > cursor:
                gaps.append((cursor, lo))
            cursor = max(cursor, min(hi, w1))
        if w1 > cursor:
            gaps.append((cursor, w1))
        gaps = [_span(_hhmm(a), _hhmm(b)) for a, b in gaps if b - a >= MIN_GAP_MINUTES]
    longest = raw["longest_gap"]
    out: dict[str, Any] = {
        "day": day, "window": [_hhmm(first * 60), _hhmm(last * 60)],
        "spans": spans, "gaps": gaps,
        "longest_gap": {**longest, "duration": fmt_minutes(longest["minutes"])} if longest else None,
        "covered_hours": raw["covered_hours"], "waking_hours": raw["waking_hours"],
        "share": raw["share"], "share_text": f"{round(raw['share'] * 100)}%",
        "busiest_hour": raw["busiest_hour"],
        "busiest_hour_text": None if raw["busiest_hour"] is None else f"{raw['busiest_hour']:02d}:00"}
    if not spans:
        out["note"] = ("No readable memory on that day. The memory covers: " + ", ".join(days) + "."
                       if days else "No readable memory yet.")
    tools.stats_returned["coverage"] = out
    return out


# -- usage_stats ----------------------------------------------------------------------------------

def _audio(minutes: float) -> str:
    return f"{minutes:g} min" if minutes < 60 else fmt_minutes(round(minutes))


def _avg(ms: int) -> str:
    return "n/a" if not ms else (f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s")


def _formatted(bucket: dict[str, Any]) -> dict[str, str]:
    return {"calls": f"{bucket['calls']:,}", "photos": f"{bucket['photos']:,}",
            "words_read": f"{bucket['words_read']:,}", "audio": _audio(bucket["audio_minutes"]),
            "avg_time": _avg(bucket["avg_ms"])}


def usage_stats(tools: RecallTools, day: str | None = None) -> dict[str, Any]:
    out = usage_summary(tools.conn, day)
    out["total"]["formatted"] = _formatted(out["total"])
    if out["day"]:
        out["day"]["formatted"] = _formatted(out["day"])
    elif day is not None:
        out["note"] = "No model calls were recorded for that day."
    for m in out["models"]:
        m["formatted"] = _formatted(m)
    tools.stats_returned["usage_stats"] = out
    return out


# -- uncertain_claims -----------------------------------------------------------------------------

def uncertain_claims(tools: RecallTools) -> list[dict[str, Any]]:
    marks = ",".join("?" * len(HIDDEN_PREDICATES))
    rows = tools._claims(f"(status = 'disputed' OR confidence < ?) AND predicate NOT IN ({marks})",
                         (LOW_CONFIDENCE, *HIDDEN_PREDICATES))
    rows.sort(key=lambda r: (r["event_time"] or "", r["created_at"], r["claim_id"]), reverse=True)
    out = []
    for r in rows[:MAX_K]:
        why = (["disputed"] if r["status"] == "disputed" else []) + \
              (["low confidence"] if r["confidence"] < LOW_CONFIDENCE else [])
        out.append({**tools.view(r), "why": why})
    return out


def extra_tools(tools: RecallTools) -> dict[str, Callable[..., Any]]:
    return {name: partial(fn, tools) for name, fn in (
        ("day_summary", day_summary), ("open_todos", open_todos), ("coverage", coverage),
        ("usage_stats", usage_stats), ("uncertain_claims", uncertain_claims))}
