"""What the model has been asked to do for this profile: a summary of the `model_calls` log.

The log holds counts and sizes only (never prompts, replies, transcripts or media), so this
summary can say how much was read, heard and answered without ever touching what was in it.
"""
import sqlite3

_COLUMNS = ("calls", "live", "cache", "failed", "reading", "answering", "photos", "words_read",
            "audio_minutes", "avg_ms")

_SELECT = """
SELECT {extra}COUNT(*) AS calls,
       COALESCE(SUM(served_from = 'live'), 0) AS live,
       COALESCE(SUM(served_from = 'cache'), 0) AS cache,
       COALESCE(SUM(ok = 0), 0) AS failed,
       COALESCE(SUM(purpose = 'read_memory'), 0) AS reading,
       COALESCE(SUM(purpose = 'answer'), 0) AS answering,
       COALESCE(SUM(images), 0) AS photos,
       COALESCE(SUM(words_in), 0) AS words_read,
       COALESCE(SUM(audio_ms), 0) AS audio_ms,
       AVG(CASE WHEN served_from = 'live' THEN duration_ms END) AS avg_ms
FROM model_calls
"""


def _bucket(row: sqlite3.Row) -> dict:
    out = {k: int(row[k]) for k in ("calls", "live", "cache", "failed", "reading", "answering",
                                    "photos", "words_read")}
    out["audio_minutes"] = round(row["audio_ms"] / 60000, 1)
    out["avg_ms"] = round(row["avg_ms"]) if row["avg_ms"] is not None else 0   # live calls only
    return {k: out[k] for k in _COLUMNS}


def usage_summary(conn: sqlite3.Connection, memory_day: str | None = None) -> dict:
    """Totals, the share for one memory day (by the day the call was about, not when it ran) and a
    row per model."""
    select = _SELECT.format(extra="")
    total = _bucket(conn.execute(select).fetchone())
    since = conn.execute("SELECT MIN(at) FROM model_calls").fetchone()[0]
    day = None
    if memory_day is not None:
        row = conn.execute(select + " WHERE memory_day = ?", (memory_day,)).fetchone()
        day = _bucket(row) if row["calls"] else None
    models = []
    per_model = _SELECT.format(extra="model, MIN(kind = 'asr') AS only_asr, ")
    for row in conn.execute(per_model + " GROUP BY model ORDER BY calls DESC, model"):
        models.append({"model": row["model"],
                       "kind_label": "Transcribes" if row["only_asr"] else "Reads and answers",
                       **{k: v for k, v in _bucket(row).items()
                          if k in ("calls", "photos", "words_read", "audio_minutes", "avg_ms",
                                   "reading", "answering", "cache")}})
    return {"recorded": total["calls"] > 0, "since": since, "total": total, "day": day,
            "models": models}
