"""Findings of the whole-branch review: each has a test that failed before its fix."""
from app import db
from app.llm.metered import MeteredLLM
from app.llm.base import LLMUnavailable
from app.llm.replay import RecordReplayClient

from .test_assistant_prompts import WALLET_CAR, ask, final, sample, seed_todos, tool  # noqa: F401  (sample is a fixture)


def test_a_dismissed_to_do_is_not_announced_by_a_cached_answer(sample):
    promise, _ = seed_todos(sample)
    q = "What did I say I would do today?"
    first = ask(sample, q, [tool("open_todos"), final("You said you would send Sam the budget.", cited=[promise])])
    assert first["status"] == "answered" and first["cached"] is False
    assert sample.client.post(f"/todos/{promise}", json={"state": "dismissed"}).status_code == 200
    second = ask(sample, q, [tool("open_todos"), final("No record: nothing is left to do.", status="abstained")])
    assert second["cached"] is False
    assert second["status"] == "abstained"


def test_a_made_up_number_is_not_accepted_on_a_memory_question_when_no_stats_tool_ran(sample):
    q = "What did the models read today?"
    claim_search = tool("search_claims", query="wallet in the car")
    lie = final("The models read 40 photos today.", cited=[WALLET_CAR])
    out = ask(sample, q, [claim_search, lie, lie])
    assert out["status"] == "abstained"
    assert any("40" in c for c in out["checks"])


def test_a_made_up_number_in_an_abstention_on_a_memory_question_is_not_shown(sample):
    q = "How much of my day is covered?"
    lie = final("No record, though about 73% is covered.", status="abstained")
    out = ask(sample, q, [lie, lie])
    assert "73" not in out["answer"] and out["status"] == "abstained"
    assert any("73" in c for c in out["checks"])


def test_a_plain_abstention_on_a_memory_question_still_passes_clean(sample):
    out = ask(sample, "What did the models read today?", [final("I have no record of that.", status="abstained")])
    assert out["status"] == "abstained" and out["checks"] == []


def test_a_replay_miss_is_not_logged_as_a_failed_model_call(tmp_path):
    """Replay mode has no recording for some calls (the to-do scan): nothing ran, so nothing failed."""
    conn = db.connect()
    metered = MeteredLLM(RecordReplayClient(str(tmp_path), "replay"), conn, {"text": "m", "asr": "a"})
    try:
        metered.complete_json("system", "never recorded", {})
        raise AssertionError("expected a miss")
    except LLMUnavailable:
        pass
    assert conn.execute("SELECT COUNT(*) FROM model_calls WHERE ok = 0").fetchone()[0] == 0
