import json

import pytest

from app.capture.models import Observation
from app.compiler.contradiction import contradiction_pass
from app.compiler.episodes import bind_episode, haversine_m
from app.compiler.extract import ExtractionRejected, extract_claims
from app.compiler.resolve import EntityResolver, norm
from app.compiler.store import ClaimWriter

from .fakes import FakeLLM, claim


def obs(source_id="s1", kind="frame_observation", at="2026-10-29T09:10:00", text="x", **kw):
    return Observation(source_id, kind, text, at, "sess", "g1", **kw)


# -- episode binding --------------------------------------------------------------------------

def test_demo_geometry_across_the_street_is_inside_the_geofence():
    assert 20 < haversine_m(37.79370, -122.39650, 37.79400, -122.39650) < 60


def test_episode_binding_follows_the_demo_day(conn):
    cafe = bind_episode(conn, obs("a", at="2026-10-29T09:10:00", lat=37.7893, lon=-122.4008))
    billboard = bind_episode(conn, obs("b", at="2026-10-29T09:40:00", lat=37.7766, lon=-122.3959))
    meeting = bind_episode(conn, obs("c", kind="calendar_event", at="2026-10-29T12:30:00",
                                     ends_at="2026-10-29T13:15:00", lat=37.7937, lon=-122.3965))
    talk = bind_episode(conn, obs("d", kind="transcript_segment", at="2026-10-29T12:35:00",
                                  lat=37.7937, lon=-122.3965))
    sign = bind_episode(conn, obs("e", at="2026-10-29T13:20:00", lat=37.7940, lon=-122.3965))
    car = bind_episode(conn, obs("f", at="2026-10-29T17:45:00"))   # no GPS fix
    assert len({cafe, billboard, meeting, car}) == 4
    assert talk == meeting == sign       # the sign photo joins the meeting 5 min after it ends
    assert conn.execute("SELECT COUNT(*) FROM entities WHERE type='episode'").fetchone()[0] == 4


def test_same_time_but_far_apart_is_a_different_episode(conn):
    a = bind_episode(conn, obs("a", at="2026-10-29T10:00:00", lat=37.7893, lon=-122.4008))
    b = bind_episode(conn, obs("b", at="2026-10-29T10:05:00", lat=37.7766, lon=-122.3959))
    assert a != b


def test_observation_without_location_joins_by_time(conn):
    a = bind_episode(conn, obs("a", at="2026-10-29T10:00:00", lat=37.7893, lon=-122.4008))
    assert bind_episode(conn, obs("b", at="2026-10-29T10:10:00")) == a


def test_episode_extent_grows_with_its_observations(conn):
    eid = bind_episode(conn, obs("a", at="2026-10-29T12:30:00", ends_at="2026-10-29T13:15:00"))
    bind_episode(conn, obs("b", at="2026-10-29T13:30:00"))
    row = conn.execute("SELECT name, attrs FROM entities WHERE entity_id=?", (eid,)).fetchone()
    assert row["name"] == "Episode 12:30-13:30"
    assert json.loads(row["attrs"])["end"] == "2026-10-29T13:30:00"


# -- extraction -------------------------------------------------------------------------------

def test_extraction_repairs_once_then_rejects():
    llm = FakeLLM()
    bad = {"claims": [{"subject": "Alex", "subject_type": "person", "predicate": "works_at",
                       "confidence": 0.9, "text": "Alex works at X"}]}
    good = {"claims": [claim("Alex", "said", value="hello")]}
    llm.extraction_replies = [bad, good]
    assert len(extract_claims(llm, obs(text="Alex: hello"), {}, [])) == 1
    assert "invalid" in llm.calls[1][1]            # the retry tells the model what was wrong
    llm.extraction_replies = [bad, bad]
    with pytest.raises(ExtractionRejected):
        extract_claims(llm, obs(text="Alex: hello"), {}, [])


def test_extraction_rejects_out_of_range_confidence():
    llm = FakeLLM()
    llm.extraction_replies = [{"claims": [claim("A", "said", value="x", confidence=85)]}] * 2
    with pytest.raises(ExtractionRejected):
        extract_claims(llm, obs(), {}, [])


# -- entity resolution ------------------------------------------------------------------------

def test_norm_folds_accents_articles_and_case():
    assert norm("The Blue Door Café") == norm("blue door cafe") == "blue door cafe"


def test_exact_and_cross_type_matching(conn):
    r = EntityResolver(conn)
    a, created = r.resolve("Blue Door Café", "place", "s1")
    assert created
    assert r.resolve("blue door cafe", "org", "s2") == (a, False)   # model said org this time
    assert r.resolve("Me", "person", "s1")[0] == "me"
    alex, _ = r.resolve("Alex", "person", "s1")
    assert r.resolve("Alexa", "person", "s1")[0] != alex   # no LLM: similar is never merged


def test_ambiguous_names_stay_separate_without_adjudication(conn):
    r = EntityResolver(conn)
    a, _ = r.resolve("Luna Taqueria", "place", "s1")
    b, created = r.resolve("Luna Taqueria Express", "place", "s1")
    assert created and a != b


def test_adjudicated_merge_becomes_a_justified_same_as_claim(conn):
    conn.execute("INSERT INTO sources(source_id, kind, captured_at, ingested_at, content_hash)"
                 " VALUES ('s1','frame_observation','t','t','h')")
    llm = FakeLLM(adjudicate="place:luna-taqueria")
    r = EntityResolver(conn, llm)
    a, _ = r.resolve("Luna Taqueria", "place", "s1")
    b, created = r.resolve("Luna Taqueria.", "place", "s1")   # exact after normalisation
    assert (b, created) == (a, False) and not r.adjudications
    c, created = r.resolve("Luna Taqueri", "place", "s1")      # fuzzy, adjudicated
    assert (c, created) == (a, False) and r.adjudications[-1]["match"] == a
    row = conn.execute("SELECT * FROM claims WHERE predicate='same_as'").fetchone()
    assert row["subject_id"] == a and row["object_value"] == "Luna Taqueri"
    assert conn.execute("SELECT source_id FROM justifications WHERE claim_id=?",
                        (row["claim_id"],)).fetchone()[0] == "s1"
    assert r.resolve("luna taqueri", "place", "s1") == (a, False)   # alias now exact


def test_adjudicator_cannot_pick_a_non_candidate(conn):
    r = EntityResolver(conn, FakeLLM(adjudicate="place:something-else"))
    r.resolve("Luna Taqueria", "place", "s1")
    _, created = r.resolve("Luna Taqueri", "place", "s1")
    assert created


# -- claim store and contradictions -----------------------------------------------------------

def seed_sources(conn, *ids):
    for i in ids:
        conn.execute("INSERT INTO sources(source_id, kind, captured_at, ingested_at, content_hash)"
                     " VALUES (?, 'frame_observation','2026-10-29T09:00:00','t',?)", (i, i))


def test_identical_claim_from_two_sources_is_one_claim_with_two_justifications(conn):
    seed_sources(conn, "cal", "talk")
    conn.execute("INSERT INTO entities VALUES ('me','person','Me',NULL),('person:alex','person','Alex',NULL)")
    w = ClaimWriter(conn)
    kw = dict(subject_id="me", predicate="met_with", object_id="person:alex", object_value=None,
              event_time="t", evidence_type="direct_observation", confidence=0.8,
              episode_id=None, text="Me met with Alex")
    c1, created1 = w.write(source_id="cal", **kw)
    c2, created2 = w.write(source_id="talk", **{**kw, "confidence": 0.9})
    assert c1 == c2 and created1 and not created2
    assert conn.execute("SELECT COUNT(*) FROM justifications WHERE claim_id=?", (c1,)).fetchone()[0] == 2
    assert conn.execute("SELECT confidence FROM claims").fetchone()[0] == 0.9
    w.write(source_id="talk", **kw)    # replay adds nothing
    assert conn.execute("SELECT COUNT(*) FROM justifications").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM claim_index").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM claim_vectors").fetchone()[0] == 1


def test_contradiction_pass_only_flags_near_simultaneous_conflicts(conn):
    seed_sources(conn, "s1")
    conn.execute("INSERT INTO entities VALUES ('o','object','wallet',NULL),('p1','place','Cafe',NULL),"
                 "('p2','place','Car',NULL),('p3','place','Desk',NULL)")
    w = ClaimWriter(conn)
    def put(place, t):
        return w.write(subject_id="o", predicate="located_at", object_id=place, object_value=None,
                       event_time=t, evidence_type="direct_observation", confidence=0.9,
                       episode_id=None, text=f"wallet at {place}", source_id="s1")[0]
    cafe = put("p1", "2026-10-29T09:10:00")
    car = put("p2", "2026-10-29T17:45:00")
    assert contradiction_pass(conn, {"o"}) == []          # sequential sightings: not a conflict
    desk = put("p3", "2026-10-29T09:12:00")
    assert len(contradiction_pass(conn, {"o"})) == 1
    status = dict(conn.execute("SELECT claim_id, status FROM claims").fetchall())
    assert status[cafe] == status[desk] == "disputed" and status[car] == "active"
