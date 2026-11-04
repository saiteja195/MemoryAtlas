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
from datetime import datetime
from functools import partial
from typing import Any, Callable

from ..insights.coverage import coverage as day_coverage
from ..insights.coverage import memory_days, window_gaps
from ..insights.usage import usage_summary
from ..todos import list_todos
from .tools import HIDDEN_PREDICATES, MAX_K, RecallTools

LOW_CONFIDENCE = 0.6
MIN_GAP_MINUTES = 30          # shorter silences are neither listed as gaps nor reported as the longest
MERGE_SPANS_UNDER = 5         # spans closer than this many minutes are shown as one
MAX_SPANS = 24                # a busy day has hundreds; more than this would crowd out the headline figures
MAX_MOMENTS = 12
MAX_NAMES = 30


def fmt_minutes(minutes: int) -> str:
    """265 -> "4 h 25 min", 45 -> "45 min", 120 -> "2 h"."""
    h, m = divmod(int(minutes), 60)
    if h == 0:
        return f"{m} min"
    return f"{h} h" if m == 0 else f"{h} h {m} min"


def _minute_of_day(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _span(start: int, end: int) -> dict[str, Any]:
    return {"start": _hhmm(start), "end": _hhmm(end), "minutes": end - start,
            "duration": fmt_minutes(end - start)}


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
    counts = {"moments": len(moments), "claims": len(shown), "people": len(people), "places": len(places)}
    # Headline first and the long lists last: a result past the clip limit is cut from the end.
    out: dict[str, Any] = {"window": {"from": time_from, "to": time_to}, "counts": counts}
    out["people"], out["places"] = sorted(people)[:MAX_NAMES], sorted(places)[:MAX_NAMES]
    if len(moments) > MAX_MOMENTS:
        out["moments_total"], out["moments_truncated"] = len(moments), True
    out["moments"] = moments[:MAX_MOMENTS]
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
    """The (first, last) minute of a window on one day; None when no window was given. Raises ValueError
    for one that crosses midnight, ends before it starts or is empty."""
    if not (time_from and time_to):
        return None
    a, b = datetime.fromisoformat(time_from), datetime.fromisoformat(time_to)
    if a.date() != b.date():
        raise ValueError("the window runs past one day")
    if b <= a:
        raise ValueError("the window is empty or ends before it starts")
    return a.hour * 60 + a.minute, b.hour * 60 + b.minute + (1 if b.second or b.microsecond else 0)


def _merge_near(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s - out[-1][1] < MERGE_SPANS_UNDER:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def coverage(tools: RecallTools, time_from: str | None = None, time_to: str | None = None) -> dict[str, Any]:
    days = memory_days(tools.conn)
    day = (time_from or time_to or "")[:10] or (days[-1] if days else "")
    if not day:
        return {"error": "no memory to cover yet"}
    try:
        datetime.fromisoformat(day)
        window = _window(time_from, time_to)
    except ValueError as e:
        return {"error": f"bad arguments for coverage: {e}. Coverage is for one day at a time: give time_from "
                         f"and time_to on the same day, time_to after time_from, or omit them."}
    raw = day_coverage(tools.conn, day)                  # the day's spans do not depend on the window
    spans = [(_minute_of_day(s["start"]), _minute_of_day(s["end"])) for s in raw["spans"]]
    day_has_spans = bool(spans)
    if window:
        lo, hi = window
        # a span that only touches the window's edge is not in it; an instant on or inside it is
        spans = [(max(s, lo), min(e, hi)) for s, e in spans
                 if (s < hi and e > lo) or (s == e and lo <= s <= hi)]
        covered = sum(e - s for s, e in spans)
        window_minutes = hi - lo
        share = round(covered / window_minutes, 4)
        hours = [h for h in raw["hours"] if lo // 60 <= h["hour"] < -(-hi // 60)]
        top = max((h["count"] for h in hours), default=0)
        busiest = next((h["hour"] for h in hours if h["count"] == top), None) if top else None
        figures: dict[str, Any] = {"share_basis": "minutes", "share": share,
                                   "share_text": f"{round(share * 100)}%", "covered_minutes": covered,
                                   "window_minutes": window_minutes, "window_hours": round(window_minutes / 60, 2)}
    else:
        lo, hi = raw["window"][0] * 60, raw["window"][1] * 60
        busiest = raw["busiest_hour"]
        # the dashboard's own numbers: waking hours that hold something, out of all waking hours
        figures = {"share_basis": "hours", "share": raw["share"], "share_text": f"{round(raw['share'] * 100)}%",
                   "covered_hours": raw["covered_hours"], "window_hours": raw["waking_hours"],
                   "window_minutes": hi - lo}
    gaps = [_span(a, b) for a, b in window_gaps(spans, lo, hi) if b - a >= MIN_GAP_MINUTES] \
        if day_has_spans else []
    shown = _merge_near(spans)
    out: dict[str, Any] = {"day": day, "window": [_hhmm(lo), _hhmm(hi)], **figures,
                           "busiest_hour": busiest,
                           "busiest_hour_text": None if busiest is None else f"{busiest:02d}:00",
                           "longest_gap": max(gaps, key=lambda g: g["minutes"]) if gaps else None, "gaps": gaps}
    if not spans:
        out["note"] = ("No readable memory in that window. The memory covers: " + ", ".join(days) + "."
                       if days else "No readable memory yet.")
    if len(shown) > MAX_SPANS:      # the long list goes last: a result past the clip limit is cut from the end
        out["spans_total"], out["spans_truncated"] = len(shown), True
    out["spans"] = [_span(s, e) for s, e in shown[:MAX_SPANS]]
    tools.stats_returned["coverage"] = out
    return out


# -- usage_stats ----------------------------------------------------------------------------------

def _audio(minutes: float) -> str:
    return f"{round(minutes, 1):g} min" if minutes < 60 else fmt_minutes(round(minutes))


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
