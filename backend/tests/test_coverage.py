import json

from app.insights.coverage import coverage, memory_days
from app.privacy import clock

DAY = "2026-10-29"


def add_source(conn, source_id, at, grant="g1", kind="frame_observation"):
    if not conn.execute("SELECT 1 FROM consent_grants WHERE grant_id=?", (grant,)).fetchone():
        conn.execute("INSERT INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes, token_hash,"
                     " granted_at) VALUES (?,?,?,?,?,?,?)",
                     (grant, "me", "capture_session", "s", json.dumps(["personal_recall"]), "h",
                      clock.now_iso()))
    conn.execute("INSERT INTO sources(source_id, kind, grant_id, captured_at, ingested_at, content_hash)"
                 " VALUES (?,?,?,?,?,?)", (source_id, kind, grant, at, at, source_id))


def add_episode(conn, eid, start, end, source_id):
    entry = {"source_id": source_id, "start": start, "end": end, "lat": None, "lon": None}
    attrs = {"start": start, "end": end, "lat": None, "lon": None, "contrib": [entry]}
    conn.execute("INSERT INTO entities(entity_id, type, name, attrs) VALUES (?,?,?,?)",
                 (eid, "episode", eid, json.dumps(attrs)))


def test_sample_day_numbers(full_day):
    c = coverage(full_day.conn, DAY)
    assert c["window"] == [6, 22]
    assert c["covered_hours"] == 4
    assert c["waking_hours"] == 16
    assert c["share"] == 0.25
    assert c["busiest_hour"] == 12
    assert c["longest_gap"] == {"start": "13:20", "end": "17:45", "minutes": 265}
    assert [h["hour"] for h in c["hours"]] == list(range(6, 22))
    assert {h["hour"] for h in c["hours"] if h["covered"]} == {9, 12, 13, 17}
    assert c["spans"][0] == {"start": "09:10", "end": "09:10"}


def test_empty_day(conn):
    c = coverage(conn, DAY)
    assert (c["covered_hours"], c["share"], c["busiest_hour"], c["longest_gap"], c["spans"]) == \
        (0, 0, None, None, [])
    assert c["waking_hours"] == 16 and len(c["hours"]) == 16


def test_single_source_gap_is_the_longer_side(conn):
    add_source(conn, "a", f"{DAY}T09:00:00")
    c = coverage(conn, DAY)
    assert c["covered_hours"] == 1
    assert c["longest_gap"] == {"start": "09:00", "end": "22:00", "minutes": 780}


def test_sources_outside_the_window_are_listed_but_not_counted(conn):
    add_source(conn, "early", f"{DAY}T05:30:00")
    add_source(conn, "a", f"{DAY}T09:00:00")
    c = coverage(conn, DAY)
    assert c["spans"][0] == {"start": "05:30", "end": "05:30"}
    assert c["covered_hours"] == 1 and c["busiest_hour"] == 9
    assert c["longest_gap"] == {"start": "09:00", "end": "22:00", "minutes": 780}
    assert all(h["count"] <= 1 for h in c["hours"])


def test_only_outside_window_means_the_whole_window_is_a_gap(conn):
    add_source(conn, "late", f"{DAY}T23:00:00")
    c = coverage(conn, DAY)
    assert c["covered_hours"] == 0 and c["busiest_hour"] is None
    assert c["longest_gap"] == {"start": "06:00", "end": "22:00", "minutes": 960}


def test_episode_crossing_midnight_is_cut_at_the_day(conn):
    add_source(conn, "n", f"{DAY}T23:30:00")
    add_episode(conn, "episode:n", f"{DAY}T23:30:00", "2026-10-30T00:30:00", "n")
    today, tomorrow = coverage(conn, DAY), coverage(conn, "2026-10-30")
    assert today["spans"] == [{"start": "23:30", "end": "24:00"}]
    assert today["covered_hours"] == 0
    assert tomorrow["spans"] == [{"start": "00:00", "end": "00:30"}]
    assert tomorrow["covered_hours"] == 0
    assert memory_days(conn) == [DAY]


def test_episode_covers_the_hours_it_overlaps(conn):
    add_source(conn, "m", f"{DAY}T10:30:00")
    add_episode(conn, "episode:m", f"{DAY}T10:30:00", f"{DAY}T12:10:00", "m")
    c = coverage(conn, DAY)
    assert {h["hour"] for h in c["hours"] if h["covered"]} == {10, 11, 12}
    assert c["spans"] == [{"start": "10:30", "end": "12:10"}]


def test_withdrawn_source_does_not_count(conn):
    add_source(conn, "a", f"{DAY}T09:00:00", grant="g1")
    add_source(conn, "b", f"{DAY}T14:00:00", grant="g2")
    add_episode(conn, "episode:b", f"{DAY}T14:00:00", f"{DAY}T15:30:00", "b")
    assert coverage(conn, DAY)["covered_hours"] == 3
    conn.execute("UPDATE consent_grants SET revoked_at=? WHERE grant_id='g2'", (clock.now_iso(),))
    c = coverage(conn, DAY)
    assert c["covered_hours"] == 1
    assert c["spans"] == [{"start": "09:00", "end": "09:00"}]


def test_withdrawn_conversation_in_the_demo_day(full_day):
    conn = full_day.conn
    before = coverage(conn, DAY)["hours"][12 - 6]["count"]
    conn.execute("UPDATE consent_grants SET revoked_at=? WHERE grantor='alex'", (clock.now_iso(),))
    after = coverage(conn, DAY)
    assert before == 4 and after["hours"][12 - 6]["count"] == 1


def test_memory_days_lists_each_day_once(conn):
    assert memory_days(conn) == []
    add_source(conn, "b", "2026-10-30T08:00:00")
    add_source(conn, "a", f"{DAY}T09:00:00")
    add_source(conn, "c", f"{DAY}T10:00:00")
    add_source(conn, "x", "2026-10-31T10:00:00", grant="g2")
    conn.execute("UPDATE consent_grants SET revoked_at=? WHERE grant_id='g2'", (clock.now_iso(),))
    assert memory_days(conn) == [DAY, "2026-10-30"]


def test_window_gaps_agree_with_the_longest_gap(full_day):
    from app.insights.coverage import window_gaps
    c = coverage(full_day.conn, DAY)
    spans = [tuple(int(x) for x in p.split(":")) for s in c["spans"] for p in (s["start"], s["end"])]
    minutes = [(spans[i][0] * 60 + spans[i][1], spans[i + 1][0] * 60 + spans[i + 1][1])
               for i in range(0, len(spans), 2)]
    gaps = window_gaps(minutes, 6 * 60, 22 * 60)
    a, b = max(gaps, key=lambda g: g[1] - g[0])
    assert (a, b, b - a) == (13 * 60 + 20, 17 * 60 + 45, c["longest_gap"]["minutes"])
    assert window_gaps([], 360, 1320) == [(360, 1320)]
