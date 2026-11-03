"""Alex's consent LAPSES instead of being withdrawn, against recorded Muse Spark output, fully offline.

Expiry runs the same purge as a withdrawal, so the recorded run from scripts/revoke_demo.py must serve it
unchanged (the receipt's own red-team probe included). The call sequence mirrors that script.
"""
from datetime import timedelta

import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.config import ROOT, Settings
from app.demo import DemoRunner
from app.demo_acts import load_acts, run_group
from app.engine import MemoryEngine
from app.llm.replay import RecordReplayClient
from app.privacy import clock
from app.privacy.revocation import RevocationEngine
from app.recall.service import RecallService

SEED = ROOT / "fixtures" / "llm_cache"
BEFORE = ["Which restaurant did Alex recommend when we met near the office?",
          "What did the billboard advertise?"]


@pytest.fixture(scope="module")
def lapsed(tmp_path_factory):
    s = Settings()
    adapter = MockDayAdapter(s.demo_script)
    tmp = tmp_path_factory.mktemp("expiry")
    llm = RecordReplayClient(str(tmp / "runtime"), "replay", seed_dir=str(SEED))
    path = str(tmp / "expiry.db")
    conn = db.connect(path)
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, s.revocation_secret)
    recall, acts = RecallService(conn, llm), load_acts()
    demo.advance(50)
    demo.play("F4")
    for q in BEFORE:
        recall.ask(q)
    alex = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'").fetchone()[0]
    conn.execute("UPDATE consent_grants SET expires_at=? WHERE grant_id=?",
                 (clock.iso(clock.now() - timedelta(seconds=1)), alex))
    conn.commit()
    engine = RevocationEngine(conn, s.revocation_secret, llm, adapter.owner, db_path=path,
                              cache_dir=str(tmp / "runtime"),
                              red_team_questions=[q["question"] for q in acts["red_team"]])
    (receipt,) = engine.sweep()
    return {"conn": conn, "receipt": receipt, "recall": recall, "acts": acts}


def test_the_receipt_says_expired_and_all_seven_checks_pass(lapsed):
    r = lapsed["receipt"]
    assert r["reason"] == "expired"
    assert r["summary"]["all_passed"] and r["summary"]["probes_total"] == 7, r["probes"]


def test_what_only_the_lapsed_conversation_supported_is_forgotten(lapsed):
    rows = run_group(lapsed["recall"], lapsed["acts"]["act4_must_forget"], forgotten=True)
    assert not [r for r in rows if r["problems"]], [(r["question"], r["problems"]) for r in rows]


def test_what_other_sources_support_is_still_answered(lapsed):
    rows = run_group(lapsed["recall"], lapsed["acts"]["act4_must_keep"])
    assert not [r for r in rows if r["problems"]], [(r["question"], r["problems"]) for r in rows]
