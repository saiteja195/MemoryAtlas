import json

from fastapi.testclient import TestClient

from app.api import create_app
from app.capture.audit import media_bytes_on_disk
from app.config import Settings
from app.graph import build_graph

from .fakes import FakeLLM


def names(graph):
    return {n["name"] for n in graph["nodes"]}


def claim_rows(conn, predicate):
    return conn.execute("SELECT * FROM claims WHERE predicate=? ORDER BY event_time", (predicate,)
                        ).fetchall()


def test_demo_day_builds_the_graph(played):
    g = build_graph(played.conn)
    assert {"Me", "Alex", "wallet", "Luna Taqueria", "Blue Door Café"} <= names(g)
    episodes = [n for n in g["nodes"] if n["type"] == "episode"]
    assert len(episodes) == 3          # café, billboard, meeting (+ sign); F4 comes later
    assert all(n["name"].startswith("Episode") for n in episodes)


def test_live_upload_starts_its_own_episode(full_day):
    g = build_graph(full_day.conn)
    assert len([n for n in g["nodes"] if n["type"] == "episode"]) == 4


def test_every_claim_has_a_source_and_the_two_independent_supports(played):
    conn = played.conn
    assert conn.execute("SELECT COUNT(*) FROM claims c WHERE NOT EXISTS (SELECT 1 FROM"
                        " justifications j WHERE j.claim_id=c.claim_id)").fetchone()[0] == 0
    (met,) = [r for r in claim_rows(conn, "met_with")]
    kinds = {r["kind"] for r in conn.execute(
        "SELECT s.kind FROM justifications j JOIN sources s USING(source_id) WHERE j.claim_id=?",
        (met["claim_id"],))}
    assert kinds == {"calendar_event", "transcript_segment"}   # "met Alex" has two supports


def test_the_taco_place_is_not_named_by_the_conversation(played):
    conn = played.conn
    texts = [r["text"] for r in conn.execute(
        "SELECT s.text FROM sources s WHERE s.kind='transcript_segment'")]
    assert texts and not any("Luna" in t for t in texts)
    said = claim_rows(conn, "said")[0]
    assert "Luna" not in said["text"]


def test_wallet_sightings_are_both_kept_in_order(full_day):
    rows = claim_rows(full_day.conn, "located_at")
    assert [r["object_id"] for r in rows] == ["place:blue-door-cafe", "place:car"]
    cafe, car = rows
    assert cafe["status"] == "superseded" and cafe["superseded_by"] == car["claim_id"]
    assert car["status"] == "active"                        # the latest sighting by event time


def test_zero_media_bytes_retained(played):
    assert played.conn.execute("SELECT COALESCE(SUM(media_bytes_retained),0) FROM sources"
                               ).fetchone()[0] == 0


def test_graph_respects_timeline_and_history(played):
    early = build_graph(played.conn, at="2026-10-29T09:30:00")
    assert "Luna Taqueria" not in names(early) and "wallet" in names(early)
    full = build_graph(played.conn)
    assert len(full["edges"]) > len(early["edges"])
    assert all(e["support"] for e in full["edges"])


def test_derived_claims_appear_in_the_graph_with_their_derivation(played):
    g = build_graph(played.conn)
    (rec,) = [e for e in g["edges"] if e["predicate"] == "recommended"]
    (sup,) = rec["support"]
    assert sup["kind"] == "derivation" and sup["rule"] == "spatial_referent_resolution"
    assert len(sup["premises"]) >= 4
    early = build_graph(played.conn, at="2026-10-29T12:50:00")      # before the sign photo
    assert not [e for e in early["edges"] if e["predicate"] == "recommended"]


def test_graph_hides_claims_whose_consent_was_withdrawn(played):
    played.conn.execute("UPDATE consent_grants SET revoked_at='x' WHERE grantor='alex'")
    g = build_graph(played.conn)
    assert not [e for e in g["edges"] if e["predicate"] in ("recommended", "said")]
    assert [e for e in g["edges"] if e["predicate"] == "met_with"]    # the calendar still supports it


def test_replaying_the_day_changes_nothing(played):
    before = played.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
    for ev in played._scheduled():
        played.play(ev["id"])
    assert played.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == before


def test_api_flow_with_no_media_on_disk(tmp_path):
    s = Settings(db_path=str(tmp_path / "m.db"), llm_mode="live", cache_dir=str(tmp_path / "c"))
    client = TestClient(create_app(s, FakeLLM()))
    assert client.get("/demo/status").json()["next"] == "F1"
    r = client.post("/demo/advance", params={"steps": 10}).json()
    assert [p["id"] for p in r["played"]] == ["F1", "F2", "C1", "A1", "F3"]
    assert r["next"] is None
    g = client.get("/graph").json()
    assert "Luna Taqueria" in names(g)
    assert client.get("/demo/status").json()["live_uploads"] == ["F4"]
    assert client.post("/demo/live/F4").json() == {"ingested": 1}
    hist = client.get("/graph", params={"include": "history"}).json()
    assert len(hist["edges"]) >= len(g["edges"])
    assert client.get("/privacy/media").json() == {"raw_media_bytes_retained": 0,
                                                   "media_bytes_on_disk": 0}
    assert media_bytes_on_disk(tmp_path) == 0
    assert client.post("/demo/reset").json()["cursor"] == 0
    assert client.get("/graph").json()["nodes"] == []


def test_capture_endpoint_enforces_consent(tmp_path):
    s = Settings(db_path=":memory:", llm_mode="live", cache_dir=str(tmp_path))
    client = TestClient(create_app(s, FakeLLM()))
    body = {"session_id": "nobody-consented", "captured_at": "2026-10-29T10:00:00",
            "text": "remember the milk"}
    assert client.post("/capture/note", json=body).json()["results"][0]["reason"] == "no_consent"
    client.post("/consent/grants", json={"grantor": "me", "session_id": "nobody-consented"})
    out = client.post("/capture/note", json=body).json()["results"][0]
    assert out["status"] == "ingested"
    assert client.post("/capture/video", json=body).status_code == 404
