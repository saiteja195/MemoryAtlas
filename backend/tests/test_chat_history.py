"""The conversation is kept with its day and status and served back by `GET /chat`, so the assistant
shows the same thread after a reload and on every page. Forgetting still reaches it."""
import sqlite3

from app import db
from app.privacy.revocation import REDACTED_CHAT
from app.profiles.runtime import Runtimes

from .fakes import FakeLLM
from .test_assistant_prompts import DAY, RECOMMENDED, ask, final, sample, tool  # noqa: F401  (sample is a fixture)
from .test_profiles_api import make_app, new_client, signup

ASK_REPLY = [tool("search_claims", query="restaurant Alex recommended"),
             final("Alex recommended Luna Taqueria.", cited=[RECOMMENDED])]


def test_history_keeps_as_of_and_status(sample):
    ask(sample, "Which restaurant did Alex recommend?", ASK_REPLY)
    msgs = sample.client.get("/chat").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]            # oldest first
    user, bot = msgs
    assert user["text"] == "Which restaurant did Alex recommend?" and user["as_of"] == DAY
    assert user["status"] is None
    assert bot["text"] == "Alex recommended Luna Taqueria."
    assert bot["status"] == "answered" and bot["as_of"] == DAY
    assert bot["cited_claim_ids"] == [RECOMMENDED] and bot["cited_tools"] == []
    assert [c["claim_id"] for c in bot["citations"]] == [RECOMMENDED]
    assert bot["redacted"] is False and bot["id"] and user["id"] != bot["id"]


def test_the_day_is_the_one_the_question_was_asked_about(sample):
    ask(sample, "Which restaurant did Alex recommend?", ASK_REPLY, as_of="2026-10-29")
    ask(sample, "Summarise my day.", [final("Nothing on that day.", status="abstained")], as_of="2026-10-30")
    days = [m["as_of"] for m in sample.client.get("/chat").json() if m["role"] == "assistant"]
    assert days == ["2026-10-29", "2026-10-30"]


def test_a_stats_answer_keeps_its_cited_tools(sample):
    ask(sample, "How much of my day is covered?", [
        tool("coverage"),
        final("25% of waking hours are covered, and the longest gap is 4 h 25 min.", tools=["coverage"])])
    bot = [m for m in sample.client.get("/chat").json() if m["role"] == "assistant"][0]
    assert bot["cited_tools"] == ["coverage"] and bot["cited_claim_ids"] == [] and bot["citations"] == []


def test_history_survives_a_runtime_rebuild(sample):
    ask(sample, "Which restaurant did Alex recommend?", ASK_REPLY)
    before = sample.client.get("/chat").json()
    pid = sample.client.get("/auth/me").json()["profile"]["profile_id"]
    runtimes = sample.client.app.state.runtimes
    runtimes.evict(pid)                                                    # the next request builds a fresh runtime
    assert sample.client.get("/chat").json() == before


def test_a_cached_answer_is_logged_too(sample):
    ask(sample, "Which restaurant did Alex recommend?", ASK_REPLY)
    again = sample.client.post("/recall/ask", json={"question": "Which restaurant did Alex recommend?",
                                                    "as_of": DAY}).json()
    assert again["cached"] is True
    assert len(sample.client.get("/chat").json()) == 4


def test_forgotten_citations_are_dropped_and_text_redacted(sample):
    ask(sample, "Which restaurant did Alex recommend?", ASK_REPLY)
    rt = sample.rt
    grant = rt.conn.execute("SELECT grant_id, grantor, scope_ref FROM consent_grants WHERE grantor='alex'").fetchone()
    token = rt.demo.tokens[f"{grant['grantor']}:{grant['scope_ref']}"]     # Alex withdraws the recorded conversation
    rt.revoker.revoke(grant["grant_id"], token, run_red_team=False)
    bot = [m for m in sample.client.get("/chat").json() if m["role"] == "assistant"][0]
    assert bot["redacted"] is True and bot["text"] == REDACTED_CHAT
    assert bot["citations"] == [] and bot["cited_claim_ids"] == []


def test_chat_is_private_to_the_profile(tmp_path):
    llm = FakeLLM()
    llm.recall_replies[:] = [final("I have no record.", status="abstained")]
    app = make_app(tmp_path, llm)
    a, b = new_client(app), new_client(app)
    signup(a, "Alpha One", "passcode-one")
    signup(b, "Beta Two", "passcode-two")
    assert a.post("/demo/load-sample").status_code == 200
    assert a.post("/recall/ask", json={"question": "What do I owe Sam?"}).status_code == 200
    assert len(a.get("/chat").json()) == 2
    assert b.get("/chat").json() == []
    assert new_client(app).get("/chat").status_code == 401


def test_old_database_is_migrated(tmp_path):
    """A database written before the new columns existed opens, keeps its rows, and accepts new ones."""
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE chat_messages (msg_id TEXT PRIMARY KEY, role TEXT NOT NULL, text TEXT NOT NULL,
          claim_ids TEXT NOT NULL DEFAULT '[]', redacted INTEGER NOT NULL DEFAULT 0);
        INSERT INTO chat_messages(msg_id, role, text) VALUES ('m1', 'user', 'an old question');
    """)
    old.commit()
    old.close()
    conn = db.connect(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)")}
    assert {"as_of", "status", "cited_tools"} <= cols
    row = conn.execute("SELECT text, as_of, status, cited_tools FROM chat_messages WHERE msg_id='m1'").fetchone()
    assert (row["text"], row["as_of"], row["status"], row["cited_tools"]) == ("an old question", None, None, "[]")
