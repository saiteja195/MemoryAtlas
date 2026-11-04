"""Deterministic answers built from a `coverage` or `usage_stats` result.

Used when the model's own answer about the memory failed the number check twice: the reply is then
this sentence, never "I can't verify that" and never an unchecked number. Every figure here is a raw
value or a preformatted string taken from the result as it is, so the sentence passes the same check.

An empty result is still an answer: coverage with nothing in its window says plainly that there is
no record (0% covered), and usage before any call says no model calls have been recorded. Those are
true statements about the memory, so the investigator returns them as `answered`. Only a missing or
error result has nothing usable, and then the investigator abstains instead of calling these.
"""
from typing import Any


def _basis(stats: dict[str, Any]) -> str:
    # "hours": waking hours that hold something, out of all waking hours (a whole day).
    # "minutes": covered minutes out of the window's minutes (a window).
    return "of the window" if stats.get("share_basis") == "minutes" else "of waking hours"


def render_coverage(stats: dict[str, Any]) -> str:
    day = stats.get("day", "")
    w0, w1 = (stats.get("window") or ["", ""])[:2]
    share, basis = stats.get("share_text", ""), _basis(stats)
    where = f"between {w0} and {w1} on {day}"
    if not stats.get("spans"):
        return f"There is no record of anything {where}, so {share} {basis} is covered."
    if stats.get("share_basis") == "minutes":
        held = f"{stats.get('covered_minutes')} of its {stats.get('window_minutes')} minutes"
        parts = [f"The memory covers {held} {where}, {share} {basis}."]
    else:
        held = f"{stats.get('covered_hours')} of {stats.get('window_hours')} waking hours"
        parts = [f"The memory covers {held} {where}, {share} {basis}."]
    gap = stats.get("longest_gap")
    if gap:
        parts.append(f"The longest gap ran from {gap['start']} to {gap['end']} ({gap['duration']}).")
    if stats.get("busiest_hour_text"):
        parts.append(f"The busiest hour began at {stats['busiest_hour_text']}.")
    return " ".join(parts)


def _plural(raw: int, shown: str, word: str) -> str:
    return f"{shown} {word}" if raw == 1 else f"{shown} {word}s"


def _bucket(b: dict[str, Any]) -> str:
    f = b["formatted"]
    return (f"{_plural(b['calls'], f['calls'], 'call')}, {_plural(b['words_read'], f['words_read'], 'word')}"
            f" and {_plural(b['photos'], f['photos'], 'photo')} read, and {f['audio']} of audio heard")


def render_usage(stats: dict[str, Any]) -> str:
    if not stats.get("recorded"):
        return "No model calls have been recorded for this profile yet, so there is no usage to report."
    total = f"In total: {_bucket(stats['total'])}."
    if stats.get("day"):
        return f"For that day: {_bucket(stats['day'])}. {total}"
    if stats.get("note"):
        return f"No model calls were recorded for that day. {total}"
    return total
