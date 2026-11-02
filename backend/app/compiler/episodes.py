"""Step 2 of the compiler (deterministic): bind observations into episodes.

An observation joins an episode when its time is within 20 minutes of the episode's extent
and, if both have a location, within 150 m of the episode's location. Calendar events extend
the extent by their duration. Otherwise it starts a new episode.
"""
import json
import math
import sqlite3
from datetime import datetime, timedelta

from ..capture.models import Observation

WINDOW = timedelta(minutes=20)
GEOFENCE_M = 150.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _gap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> timedelta:
    if a_end < b_start:
        return b_start - a_end
    if b_end < a_start:
        return a_start - b_end
    return timedelta(0)


def _label(start: datetime, end: datetime) -> str:
    return (f"Episode {start:%H:%M}" if start == end else f"Episode {start:%H:%M}-{end:%H:%M}")


def episode_extent(contrib: list[dict]) -> dict:
    """Time bounds and location of an episode, derived only from the observations in `contrib`.
    The location is the first contribution that has one."""
    start = min(datetime.fromisoformat(c["start"]) for c in contrib)
    end = max(datetime.fromisoformat(c["end"]) for c in contrib)
    located = next((c for c in contrib if c.get("lat") is not None and c.get("lon") is not None), None)
    return {"start": start.isoformat(), "end": end.isoformat(),
            "lat": located["lat"] if located else None, "lon": located["lon"] if located else None}


def episode_id_for(start: datetime) -> str:
    return f"episode:{start:%Y%m%d-%H%M}"


def bind_episode(conn: sqlite3.Connection, obs: Observation) -> str:
    start = datetime.fromisoformat(obs.captured_at)
    end = datetime.fromisoformat(obs.ends_at) if obs.ends_at else start
    entry = {"source_id": obs.source_id, "start": start.isoformat(), "end": end.isoformat(),
             "lat": obs.lat, "lon": obs.lon}
    best: tuple[timedelta, sqlite3.Row, dict] | None = None
    for row in conn.execute("SELECT * FROM entities WHERE type='episode'"):
        a = json.loads(row["attrs"])
        gap = _gap(start, end, datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["end"]))
        if gap > WINDOW:
            continue
        if None not in (obs.lat, obs.lon, a.get("lat"), a.get("lon")) and \
                haversine_m(obs.lat, obs.lon, a["lat"], a["lon"]) > GEOFENCE_M:
            continue
        if best is None or gap < best[0]:
            best = (gap, row, a)
    if best is None:
        eid, n = episode_id_for(start), 2
        base = eid
        while conn.execute("SELECT 1 FROM entities WHERE entity_id=?", (eid,)).fetchone():
            eid, n = f"{base}-{n}", n + 1
        attrs = {**episode_extent([entry]), "contrib": [entry]}
        conn.execute("INSERT INTO entities(entity_id, type, name, attrs) VALUES (?,?,?,?)",
                     (eid, "episode", _label(start, end), json.dumps(attrs)))
        return eid
    _, row, a = best
    # `contrib` records which observation supplied which time and place, so the episode can be
    # recomputed from what remains if one of them is forgotten. Older rows without it get one
    # entry standing for what they already held.
    contrib = a.get("contrib") or [{"source_id": None, "start": a["start"], "end": a["end"],
                                    "lat": a.get("lat"), "lon": a.get("lon")}]
    contrib = [*contrib, entry]
    a = {**episode_extent(contrib), "contrib": contrib}
    conn.execute("UPDATE entities SET name=?, attrs=? WHERE entity_id=?",
                 (_label(datetime.fromisoformat(a["start"]), datetime.fromisoformat(a["end"])),
                  json.dumps(a), row["entity_id"]))
    return row["entity_id"]
