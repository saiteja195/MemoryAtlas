"""Phase 2 gate against recorded Muse Spark output (fixtures/llm_cache), fully offline.

Acts 2 and 3 are asked with three phrasings each, plus questions that must be refused. The
sequence below must match scripts/ask_demo.py exactly, because request hashes depend on graph
state. If you change a prompt, run ask_demo.py again to re-record.
"""
import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.config import ROOT, Settings
from app.demo import DemoRunner
from app.demo_acts import load_acts, run_group
from app.engine import MemoryEngine
from app.llm.replay import RecordReplayClient
from app.recall.service import RecallService

CACHE = ROOT / "fixtures" / "llm_cache"


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    s = Settings()
    adapter = MockDayAdapter(s.demo_script)
    llm = RecordReplayClient(str(CACHE), "replay")
    conn = db.connect(str(tmp_path_factory.mktemp("db") / "recall.db"))
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, "s")
    recall = RecallService(conn, llm)
    acts = load_acts()
    played = demo.advance(50)
    out = {"played": played, "conn": conn, "demo": demo}
    out["act2"] = run_group(recall, acts["act2_connect"])
    out["act3_before"] = run_group(recall, acts["act3_before"])
    out["abstain"] = run_group(recall, acts["must_abstain"], abstain=True)
    demo.play("F4")
    out["act3_after"] = run_group(recall, acts["act3_after"])
    return out


def explain(rows):
    return [(r["question"], r["problems"], r["out"]["answer"]) for r in rows if r["problems"]]


@pytest.mark.parametrize("group", ["act2", "act3_before", "act3_after", "abstain"])
def test_every_phrasing_passes(session, group):
    assert len(session[group]) == 3
    assert not explain(session[group])


def test_act2_answers_cite_the_derived_recommendation(session):
    conn = session["conn"]
    (rec,) = conn.execute("SELECT claim_id FROM claims WHERE predicate='recommended'").fetchall()
    for r in session["act2"]:
        assert r["out"]["status"] == "answered"
        assert rec["claim_id"] in r["out"]["cited_claim_ids"] or any(
            "Luna" in c["text"] for c in r["out"]["citations"])
        assert r["out"]["citations"]


def test_act3_flips_to_the_car_and_keeps_the_cafe_as_history(session):
    before = " ".join(r["out"]["answer"] for r in session["act3_before"])
    after = " ".join(r["out"]["answer"] for r in session["act3_after"])
    assert "09:10" in before and "17:45" not in before
    assert "17:45" in after
    conn = session["conn"]
    cafe = conn.execute("SELECT status FROM claims WHERE predicate='located_at' AND"
                        " event_time LIKE '%09:10%'").fetchone()
    assert cafe["status"] == "superseded"           # greyed out, still history


def test_wallet_answers_are_never_present_tense(session):
    for r in session["act3_before"] + session["act3_after"]:
        assert "last confirmed sighting" in r["out"]["answer"].lower() or \
            "last seen" in r["out"]["answer"].lower() or "last see" in r["out"]["answer"].lower()


def test_abstentions_cite_nothing(session):
    for r in session["abstain"]:
        assert r["out"]["status"] == "abstained" and r["out"]["cited_claim_ids"] == []


def test_every_citation_was_shown_by_a_tool_and_is_still_valid(session):
    from app.privacy.filter import authorized_claim_ids
    ok = authorized_claim_ids(session["conn"])
    for group in ("act2", "act3_before", "act3_after"):
        for r in session[group]:
            assert set(r["out"]["cited_claim_ids"]) <= ok
            assert r["out"]["trace"], "an answer needs at least one tool call"


def test_nothing_was_rejected_while_building_the_day(session):
    assert not [p for p in session["played"] if p["rejected"]]
