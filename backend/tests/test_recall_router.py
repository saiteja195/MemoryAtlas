"""The code router that sends a question to the extended investigator prompt, the `as_of` day
and the cache rules. Unrouted questions must keep the original prompt and payload byte for byte,
because recorded replies in fixtures/llm_cache are keyed by them."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.compiler.resolve import norm
from app.config import Settings
from app.demo_acts import load_acts
from app.insights.coverage import memory_days
from app.recall.investigator import EXTENDED_ADDENDUM, SYSTEM, Investigator
from app.recall.router import needs_extended
from app.recall.service import RecallService

from .fakes import FakeLLM


def abstained(answer="No record."):
    return {"action": "final", "status": "abstained", "answer": answer,
            "cited_claim_ids": [], "uncertainty_note": ""}


# -- the router ---------------------------------------------------------------------------------

GOALS = [
    # Facts
    ("Where did I leave my wallet?", {None}),
    ("Which restaurant did Alex recommend?", {None}),
    ("Who did I meet today?", {"time"}),
    ("What time was my meeting with Alex?", {None}),
    # Summary
    ("Summarise my day.", {"summary", "time"}),
    ("What happened this morning?", {"summary", "time"}),
    ("What was the most important moment?", {"summary", "time"}),
    ("Where did I spend the most time?", {"summary", "time"}),
    # To-dos
    ("What did I say I would do today?", {"todo"}),
    ("Did I promise anyone anything?", {"todo"}),
    ("Did anyone ask me to do something?", {"todo"}),
    ("What did I forget to follow up on?", {"todo"}),
    # About the memory
    ("What did the models read today?", {"memory"}),
    ("How much of my day is covered?", {"memory"}),
    ("What happened between 13:20 and 17:45?", {"memory"}),
    ("What are you unsure about?", {"memory"}),
]


@pytest.mark.parametrize("question,routes", GOALS)
def test_router_matrix(question, routes):
    assert needs_extended(question) in routes
    assert needs_extended(question.upper()) in routes        # case-insensitive


def recorded_questions():
    """Every question asked through the recall service with a recorded reply: the demo acts
    (fixtures/demo_day/acts.yaml, which frontend/src/utils/suggest.ts mirrors). The red-team
    probes call the investigator directly, without a day, so they never route."""
    acts = load_acts()
    return sorted({item["question"] for group, items in acts.items() if group != "red_team"
                   for item in items})


@pytest.mark.parametrize("question", recorded_questions())
def test_recorded_questions_keep_the_original_prompt(question):
    assert needs_extended(question) is None


@pytest.mark.parametrize("question", ["What did Alex promise me?", "Who did I have lunch with on Friday?",
                                      "Which gym did I go to?", "Did I have a meeting with Alex?"])
def test_words_close_to_a_route_do_not_route(question):
    assert needs_extended(question) is None


def test_addendum_states_the_windows_and_the_new_tools():
    for text in ("05:00 to 11:59", "12:00 to 17:59", "18:00 to 23:59", "as_of", "day_summary(",
                 "open_todos(", "coverage(", "usage_stats(", "uncertain_claims("):
        assert text in EXTENDED_ADDENDUM
    assert "unknown" in EXTENDED_ADDENDUM.lower() and "no record" in EXTENDED_ADDENDUM.lower()
    assert not EXTENDED_ADDENDUM.startswith(SYSTEM)       # appended, never a rewrite


# -- prompt and payload sent ----------------------------------------------------------------------

def recall_calls(llm):
    return [(s, json.loads(u.split("\n\nYour previous")[0])) for s, u in llm.calls
            if s.startswith("You answer questions")]


def test_unrouted_question_sends_the_original_system_prompt(played):
    llm = played.engine.llm
    llm.recall_replies[:] = [abstained()]
    RecallService(played.conn, llm).ask("Which restaurant did Alex recommend?", as_of="2026-10-29")
    ((system, payload),) = recall_calls(llm)
    assert system == SYSTEM
    assert list(payload) == ["question", "steps_so_far"]       # the recorded payload shape


def test_routed_question_sends_system_plus_addendum_and_the_date(played):
    llm = played.engine.llm
    llm.recall_replies[:] = [abstained()]
    RecallService(played.conn, llm).ask("Who did I meet today?", as_of="2026-10-29")
    ((system, payload),) = recall_calls(llm)
    assert system == SYSTEM + EXTENDED_ADDENDUM
    assert payload["as_of"] == payload["today"] == "2026-10-29"
    assert payload["question"] == "Who did I meet today?"


def test_investigator_without_a_day_keeps_the_original_prompt(played):
    """The red-team probes ask "Summarize my afternoon." straight to the investigator, with no day:
    their recorded replies must still match."""
    llm = played.engine.llm
    llm.recall_replies[:] = [abstained()]
    Investigator(played.conn, llm, purpose="other").ask("Summarize my afternoon.")
    ((system, payload),) = recall_calls(llm)
    assert system == SYSTEM and list(payload) == ["question", "steps_so_far"]


def test_ask_without_as_of_defaults_to_the_latest_memory_day(played):
    llm = played.engine.llm
    llm.recall_replies[:] = [abstained()]
    latest = memory_days(played.conn)[-1]
    RecallService(played.conn, llm).ask("What happened this morning?")
    ((system, payload),) = recall_calls(llm)
    assert system == SYSTEM + EXTENDED_ADDENDUM and payload["as_of"] == latest


def test_no_memories_means_no_day_and_the_original_prompt(conn):
    llm = FakeLLM()
    llm.recall_replies[:] = [abstained()]
    RecallService(conn, llm).ask("Who did I meet today?")
    ((system, payload),) = recall_calls(llm)
    assert system == SYSTEM and "as_of" not in payload


# -- cache rules ----------------------------------------------------------------------------------

def test_same_question_on_two_days_is_not_shared_by_the_cache(played):
    llm = played.engine.llm
    llm.recall_replies[:] = [abstained("a"), abstained("b")]
    svc = RecallService(played.conn, llm)
    first = svc.ask("Who did I meet today?", as_of="2026-10-29")
    other_day = svc.ask("Who did I meet today?", as_of="2026-10-30")
    again = svc.ask("who did I meet TODAY? ", as_of="2026-10-29")
    assert (first["cached"], other_day["cached"], again["cached"]) == (False, False, True)
    assert (first["answer"], other_day["answer"], again["answer"]) == ("a", "b", "a")
    key = hashlib.sha256(("time|2026-10-29|" + norm("Who did I meet today?")).encode()).hexdigest()
    assert played.conn.execute("SELECT 1 FROM answer_cache WHERE question_hash=?", (key,)).fetchone()


def test_unrouted_cache_key_is_unchanged(played):
    llm = played.engine.llm
    llm.recall_replies[:] = [abstained()]
    svc = RecallService(played.conn, llm)
    q = "Which restaurant did Alex recommend?"
    svc.ask(q, as_of="2026-10-29")
    key = hashlib.sha256(norm(q).encode()).hexdigest()
    assert played.conn.execute("SELECT 1 FROM answer_cache WHERE question_hash=?", (key,)).fetchone()
    assert svc.ask(q, as_of="2026-10-30")["cached"] is True      # the day does not matter to it


# -- API ------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    llm = FakeLLM()
    c = TestClient(create_app(Settings(auth=False, db_path=":memory:", llm_mode="live",
                                       cache_dir=str(tmp_path)), llm))
    c.llm = llm
    c.post("/demo/advance", params={"steps": 10})
    return c


@pytest.mark.parametrize("bad", ["29-10-2026", "2026-10-32", "2026-1-5", "today", "2026-10-29T00:00"])
def test_ask_endpoint_rejects_a_malformed_day(client, bad):
    r = client.post("/recall/ask", json={"question": "Who did I meet today?", "as_of": bad})
    assert r.status_code == 422


def test_ask_endpoint_passes_the_day_through(client):
    client.llm.recall_replies[:] = [abstained()]
    r = client.post("/recall/ask", json={"question": "Who did I meet today?", "as_of": "2026-10-30"})
    assert r.status_code == 200
    assert client.llm.recall_payloads[-1]["as_of"] == "2026-10-30"
