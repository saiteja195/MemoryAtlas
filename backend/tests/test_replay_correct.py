"""A user correction against recorded Muse Spark output (fixtures/llm_cache), fully offline.

The call sequence must match scripts/correct_demo.py. If you change a prompt, run that script again.
"""
import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.config import ROOT, Settings
from app.corrections import correct_claim
from app.demo import DemoRunner
from app.engine import MemoryEngine
from app.llm.replay import RecordReplayClient
from app.recall.service import RecallService

SEED = ROOT / "fixtures" / "llm_cache"
QUESTION = "What did Alex promise me?"
CORRECTION = "Actually, Alex said he would send the proposal by Monday, not Friday."
AT = "2026-10-29T18:30:00"      # fixed: the time is part of the request, so a replay needs it pinned


@pytest.fixture(scope="module")
def corrected(tmp_path_factory):
    s = Settings()
    adapter = MockDayAdapter(s.demo_script)
    tmp = tmp_path_factory.mktemp("correct")
    llm = RecordReplayClient(str(tmp / "runtime"), "replay", seed_dir=str(SEED))
    conn = db.connect(str(tmp / "c.db"))
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, s.revocation_secret)
    recall = RecallService(conn, llm)
    demo.advance(50)
    demo.play("F4")
    before = recall.ask(QUESTION)
    result = correct_claim(demo.engine, before["cited_claim_ids"][0], CORRECTION, at=AT)
    after = recall.ask(QUESTION)
    return {"conn": conn, "before": before, "result": result, "after": after}


def test_the_answer_says_friday_before_and_monday_after(corrected):
    assert "friday" in corrected["before"]["answer"].lower()
    after = corrected["after"]["answer"].lower()
    assert "monday" in after and "friday" not in after


def test_the_corrected_answer_cites_the_users_own_correction(corrected):
    conn, after = corrected["conn"], corrected["after"]
    assert corrected["result"]["replacement"] in after["cited_claim_ids"]
    kinds = {r[0] for r in conn.execute(
        "SELECT s.kind FROM justifications j JOIN sources s USING(source_id) WHERE j.claim_id=?",
        (corrected["result"]["replacement"],))}
    assert kinds == {"user_confirmation"}


def test_the_old_fact_is_kept_as_history(corrected):
    old = corrected["before"]["cited_claim_ids"][0]
    row = corrected["conn"].execute("SELECT status, superseded_by FROM claims WHERE claim_id=?", (old,)).fetchone()
    assert row["status"] == "superseded" and row["superseded_by"] == corrected["result"]["replacement"]
