"""Phase 3 gate against recorded Muse Spark output (fixtures/llm_cache), fully offline.

Act 4 on the real model: the day is played, two questions are asked, Alex withdraws consent
(the receipt's own red-team probe runs the real investigator), then the post-revocation
questions are asked. The call sequence must match scripts/revoke_demo.py exactly because request
hashes depend on graph state. If you change a prompt, run that script again to re-record.
"""
import os

import pytest

from app import db
from app.capture.adapters import MockDayAdapter
from app.config import ROOT, Settings
from app.demo import DemoRunner
from app.demo_acts import load_acts, run_group
from app.engine import MemoryEngine
from app.llm.replay import RecordReplayClient
from app.privacy.filter import authorized_claim_ids
from app.privacy.revocation import RevocationEngine
from app.recall.service import RecallService

SEED = ROOT / "fixtures" / "llm_cache"
BEFORE = ["Which restaurant did Alex recommend when we met near the office?",
          "What did the billboard advertise?"]


@pytest.fixture(scope="module")
def act4(tmp_path_factory):
    s = Settings()
    adapter = MockDayAdapter(s.demo_script)
    tmp = tmp_path_factory.mktemp("act4")
    llm = RecordReplayClient(str(tmp / "runtime"), "replay", seed_dir=str(SEED))
    path = str(tmp / "revoke.db")
    conn = db.connect(path)
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter,
                      s.revocation_secret)
    recall, acts = RecallService(conn, llm), load_acts()
    demo.advance(50)
    demo.play("F4")
    for q in BEFORE:
        recall.ask(q)
    before = {"claims": conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
              "chat": conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]}
    alex = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'").fetchone()[0]
    engine = RevocationEngine(conn, s.revocation_secret, llm, adapter.owner, db_path=path,
                              cache_dir=str(tmp / "runtime"),
                              red_team_questions=[q["question"] for q in acts["red_team"]])
    receipt = engine.revoke(alex, demo.tokens["alex:sync-alex"])
    out = {"conn": conn, "receipt": receipt, "before": before, "path": path, "demo": demo,
           "engine": engine, "alex": alex}
    out["forget"] = run_group(recall, acts["act4_must_forget"], forgotten=True)
    out["keep"] = run_group(recall, acts["act4_must_keep"])
    return out


def explain(rows):
    return [(r["question"], r["problems"], r["out"]["answer"]) for r in rows if r["problems"]]


def test_all_seven_probes_pass_including_the_red_team(act4):
    s = act4["receipt"]["summary"]
    assert s == {"probes_passed": 7, "probes_failed": 0, "probes_skipped": 0, "probes_total": 7,
                 "all_passed": True}, act4["receipt"]["probes"]


def test_forgotten_questions_are_refused_without_leaking(act4):
    assert len(act4["forget"]) == 4 and not explain(act4["forget"])
    for r in act4["forget"]:
        assert r["out"]["cited_claim_ids"] == []


def test_surviving_facts_still_answer_with_citations(act4):
    assert len(act4["keep"]) == 4 and not explain(act4["keep"])
    for r in act4["keep"]:
        assert r["out"]["status"] == "answered" and r["out"]["cited_claim_ids"]


def test_the_meeting_survives_because_the_calendar_supports_it(act4):
    r = act4["receipt"]
    met = next(x for x in r["retained"] if x["text"] == "Me met with Alex")
    assert all(s.startswith("transcript_segment") for s in met["lost_support"])
    assert met["still_supported_by"] == ["calendar_event at 12:30"]


def test_the_receipt_counts_and_does_not_quote(act4):
    r = act4["receipt"]
    assert r["removed"]["sources_blanked"] == 3 and r["removed"]["claims_deleted"] >= 8
    assert r["removed"]["claims_deleted_by_kind"].get("recommended") == 1
    blob = str(r).lower()
    for gone in ("pastor", "proposal", "friday", "promise", "sounds great"):
        assert gone not in blob


def test_the_cached_answer_and_the_chat_about_the_recommendation_were_removed(act4):
    assert act4["receipt"]["removed"]["answer_cache_rows"] >= 1
    redacted = act4["conn"].execute("SELECT text FROM chat_messages WHERE redacted=1").fetchall()
    assert redacted and all("Luna" not in r[0] for r in redacted)
    kept = [r[0] for r in act4["conn"].execute("SELECT text FROM chat_messages WHERE redacted=0")]
    assert any("billboard" in t.lower() or "Orbit" in t for t in kept)


def test_everything_that_remains_has_valid_support(act4):
    conn = act4["conn"]
    ids = {r[0] for r in conn.execute("SELECT claim_id FROM claims")}
    assert ids <= authorized_claim_ids(conn)
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] < act4["before"]["claims"]


def test_the_database_file_holds_none_of_what_was_forgotten(act4):
    data = b"".join(open(act4["path"] + s, "rb").read() for s in ("", "-wal")
                    if os.path.exists(act4["path"] + s)).lower()
    for gone in (b"al pastor", b"proposal by friday", b"sounds great", b"green awning, best"):
        assert gone not in data


def test_asking_again_to_forget_changes_nothing(act4):
    again = act4["engine"].revoke(act4["alex"], act4["demo"].tokens["alex:sync-alex"])
    assert again["already_revoked"] and again["receipt_id"] == act4["receipt"]["receipt_id"]
