"""Phase 1 gate against recorded Muse Spark output (fixtures/llm_cache).

The cache was produced by `scripts/record_demo.py` with the live model. If you change a prompt
the request hashes change and these tests fail with 'no recorded response'. Re-record then.
"""
import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.capture.audit import media_bytes_on_disk
from app.config import ROOT, Settings
from app.demo import DemoRunner
from app.engine import MemoryEngine
from app.graph import build_graph
from app.llm.replay import RecordReplayClient

CACHE = ROOT / "fixtures" / "llm_cache"


@pytest.fixture(scope="module")
def day(tmp_path_factory):
    adapter = MockDayAdapter(Settings().demo_script)
    llm = RecordReplayClient(str(CACHE), "replay")
    conn = db.connect(str(tmp_path_factory.mktemp("db") / "replay.db"))
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, "s")
    played = demo.advance(50)
    demo.play("F4")
    return demo, played


def edges(day, predicate):
    g = build_graph(day[0].conn, include_history=True)
    names = {n["id"]: n["name"] for n in g["nodes"]}
    return [(names[e["source"]], names.get(e["target"]) or e["value"], e)
            for e in g["edges"] if e["predicate"] == predicate]


def test_replay_builds_the_demo_graph_with_nothing_rejected(day):
    demo, played = day
    assert not [p for p in played if p["rejected"]]
    g = build_graph(demo.conn)
    names = {n["name"] for n in g["nodes"]}
    assert {"Me", "Alex", "wallet", "Luna Taqueria"} <= names
    assert len([n for n in g["nodes"] if n["type"] == "episode"]) == 4


def test_met_alex_is_supported_by_calendar_and_conversation(day):
    ((_, obj, edge),) = [x for x in edges(day, "met_with") if x[1] == "Alex"]
    assert {s["kind"] for s in edge["support"]} == {"calendar_event", "transcript_segment"}


def test_conversation_never_names_the_restaurant(day):
    conn = day[0].conn
    talk = " ".join(r[0] for r in conn.execute(
        "SELECT text FROM sources WHERE kind='transcript_segment'"))
    assert "Luna" not in talk
    for _, _, e in edges(day, "said"):
        assert "Luna" not in e["text"]


def test_the_sign_gives_luna_its_green_awning(day):
    assert any(s == "Luna Taqueria" and "green" in (o or "") for s, o, _ in
               edges(day, "has_attribute"))


def test_both_wallet_sightings_are_recorded_in_time_order(day):
    sightings = [(e["event_time"], o) for s, o, e in edges(day, "located_at") if s == "wallet"]
    assert len(sightings) == 2
    assert sightings == sorted(sightings)
    assert sightings[0][1] == "Blue Door Café" and sightings[0][0].startswith("2026-10-29T09:10")


def test_zero_media_bytes(day, tmp_path):
    assert day[0].conn.execute("SELECT COALESCE(SUM(media_bytes_retained),0) FROM sources"
                               ).fetchone()[0] == 0
    assert media_bytes_on_disk(CACHE, tmp_path) == 0
