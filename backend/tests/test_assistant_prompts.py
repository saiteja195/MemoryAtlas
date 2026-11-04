"""One test per assistant prompt in the spec's Goals list (sixteen), on the staged sample day.

Each test signs up a fresh profile, loads the committed sample snapshot through `POST /demo/load-sample`
(no model call), then asks its prompt through `POST /recall/ask` on the real app. The model is a
scripted `FakeLLM` that plays the tool calls and the final reply a good model would give; everything
else is production code: the router, the investigator loop, the real tools, every post-check and the
answer service. A good reply must pass those checks untouched (no check note, no template fallback),
and the tests at the end prove that bad replies (present tense, invented number, uncited or unseen
claim) are still caught on these same prompts.

The sample day: wallet at Blue Door Café 09:10 and in the car at 17:45, a billboard on the street at
09:40, the meeting with Alex at the Office at 12:30 (he recommended the taco place, Luna Taqueria, and
said he would send the proposal by Friday), Luna Taqueria seen at 13:20. The owner made no promise and
was asked nothing, so the to-do prompts seed one through the to-do scan, or abstain.
"""
import re
from types import SimpleNamespace

import pytest

from app.capture.models import RawCapture
from app.config import ROOT
from app.privacy.consent import create_grant
from app.recall.investigator import EXTENDED_ADDENDUM, SYSTEM, numbers_in
from app.recall.router import needs_extended
from app.todos import list_todos

from .fakes import DEMO_RULES, FakeLLM, claim
from .test_profiles_api import make_app, new_client, signup
from .test_tools_extra import add_call

DAY = "2026-10-29"
WHOLE_DAY = {"time_from": f"{DAY}T00:00:00", "time_to": f"{DAY}T23:59:59"}

# Claim ids in the committed snapshot (fixtures/profiles/staged.db); the tests check each is what it says.
WALLET_CAR = "clm-a94d0f3c6a6b"         # wallet located_at car, 17:45 (latest sighting)
WALLET_CAFE = "clm-28867fe1e76e"        # wallet located_at Blue Door Café, 09:10 (superseded: history)
RECOMMENDED = "clm-f74560568239"        # Alex recommended Luna Taqueria
MET_ALEX = "clm-a11c064887b5"           # Me met_with Alex, 12:30
AT_OFFICE = "clm-78180ac45720"          # Me observed_at Office, 12:30
LUNA_1320 = "clm-52e5a0f168a3"          # Luna Taqueria is a taco restaurant, 13:20
ALEX_PROMISE = "clm-4ef2fcb6078a"       # Alex committed_to send the proposal (Alex's, not the owner's)
SUMMARY = {"0910": "clm-4371871deb85", "0940": "clm-96f531753f2f",   # active summary of each moment
           "1230": "clm-1e5ef5965d5b", "1745": "clm-e4e0c3623b20"}
LOW_CONFIDENCE = SUMMARY["0940"]        # the only claim under 0.6 confidence on the sample day

PROMISE = claim("Me", "committed_to", value="send Sam the budget", text="I will send Sam the budget")
ASK = claim("Alex", "requested", "Me", object_type="person", value="review the draft",
            text="Alex asked me to review the draft")

PROMPTS = {
    "facts": ["Where did I leave my wallet?", "Which restaurant did Alex recommend?", "Who did I meet today?",
              "What time was my meeting with Alex?"],
    "summary": ["Summarise my day.", "What happened this morning?", "What was the most important moment?",
                "Where did I spend the most time?"],
    "todo": ["What did I say I would do today?", "Did I promise anyone anything?",
             "Did anyone ask me to do something?", "What did I forget to follow up on?"],
    "memory": ["What did the models read today?", "How much of my day is covered?",
               "What happened between 13:20 and 17:45?", "What are you unsure about?"],
}
ALL_PROMPTS = [q for group in PROMPTS.values() for q in group]


# -- helpers ----------------------------------------------------------------------------------------

def tool(tool_name, /, **args):
    return {"action": "tool", "tool": tool_name, "args": args}


def final(answer, cited=(), tools=(), status="answered", note=""):
    return {"action": "final", "status": status, "answer": answer, "cited_claim_ids": list(cited),
            "cited_tools": list(tools), "uncertainty_note": note}


@pytest.fixture
def sample(tmp_path):
    """A fresh profile holding the staged sample day, loaded from the committed snapshot."""
    llm = FakeLLM(rules=DEMO_RULES + [("the budget", [PROMISE])])
    app = make_app(tmp_path, llm)
    client = new_client(app)
    assert signup(client).status_code == 201
    r = client.post("/demo/load-sample")
    assert r.status_code == 200 and r.json()["cursor"] == r.json()["total"] > 0
    assert llm.calls == []                       # the snapshot, not a replay through the model
    pid = client.get("/auth/me").json()["profile"]["profile_id"]
    rt = app.state.runtimes.get(pid, "x", False)
    return SimpleNamespace(client=client, llm=llm, rt=rt, conn=rt.conn)


def ask(s, question, replies, as_of=DAY):
    s.llm.recall_replies[:] = replies
    s.llm.recall_payloads.clear()
    before = len(s.llm.calls)
    body = {"question": question} if as_of is None else {"question": question, "as_of": as_of}
    r = s.client.post("/recall/ask", json=body)
    assert r.status_code == 200, r.text
    assert s.llm.recall_replies == [], "every scripted step was played"
    out = r.json()
    out["systems"] = {sys for sys, _ in s.llm.calls[before:] if sys.startswith("You answer")}
    return out


def passed_clean(out, status="answered"):
    """A good reply went through every check untouched: no check note and no template fallback."""
    assert out["status"] == status, out
    assert out["checks"] == [], out["checks"]
    assert not any(c.startswith("fallback:") for c in out["checks"])
    if status != "abstained":
        assert out["cited_claim_ids"] or out["cited_tools"]
        assert [c["claim_id"] for c in out["citations"]] == out["cited_claim_ids"]


def routed(s, out, question, route):
    assert needs_extended(question) == route
    if route is None:
        assert out["systems"] == {SYSTEM}
        assert all("as_of" not in p for p in s.llm.recall_payloads)
    else:
        assert out["systems"] == {SYSTEM + EXTENDED_ADDENDUM}
        assert all(p["as_of"] == DAY and p["today"] == DAY for p in s.llm.recall_payloads)


def claim_row(s, cid):
    return s.conn.execute("SELECT c.*, e.name AS subject FROM claims c JOIN entities e ON e.entity_id = c.subject_id"
                          " WHERE claim_id=?", (cid,)).fetchone()


def episodes_of(s, cids):
    return {claim_row(s, c)["episode_id"] for c in cids}


def tool_calls(out):
    return [(t["tool"], t["results"]) for t in out["trace"]]


def seed_todos(s):
    """One promise by the owner (a note) and one request made of the owner (found by the to-do scan in
    a conversation), ingested through the profile's own engine. Returns (promise_id, request_id)."""
    engine, conn, secret = s.rt.engine, s.conn, s.rt.settings.revocation_secret
    for person in ("me", "alex"):
        create_grant(conn, secret, person, "talk")
    s.llm.todo_replies.append({"claims": [ASK]})
    turns = [{"turn_id": 1, "start_ms": 0, "end_ms": 500, "speaker": "B", "text": "Can you review the draft?"}]
    engine.ingest(RawCapture(kind="audio", session_id="talk", captured_at=f"{DAY}T15:05:00", turns=turns,
                             participants=["alex"], speaker_map={"A": "me", "B": "alex"}))
    create_grant(conn, secret, "me", "jot")
    engine.ingest(RawCapture(kind="note", session_id="jot", captured_at=f"{DAY}T16:40:00",
                             text="Remember: I will send Sam the budget"))
    todos = {t["kind"]: t["claim_id"] for t in list_todos(conn, "me")}
    assert set(todos) == {"promise", "request"}
    return todos["promise"], todos["request"]


def seed_usage(s):
    """Three model calls about the sample day in the usage log, as the metering client writes them."""
    add_call(s.conn, "read-photo", model="muse-spark-1.3", kind="vision", purpose="read_memory",
             images=2, words_in=1200)
    add_call(s.conn, "read-audio", model="muse-voice-transcribe-1.0", kind="asr", purpose="read_memory",
             audio_ms=90000)
    add_call(s.conn, "read-text", model="muse-spark-1.3", purpose="read_memory", words_in=3000)


def logged_for_day(s):
    """The day's figures straight from the model_calls log, independent of usage_stats."""
    r = s.conn.execute("SELECT COUNT(*) n, SUM(images) photos, SUM(words_in) words, SUM(audio_ms) audio"
                       " FROM model_calls WHERE memory_day=?", (DAY,)).fetchone()
    return {"calls": str(r["n"]), "photos": str(r["photos"]), "words": str(r["words"]),
            "audio": f"{round(r['audio'] / 60000, 1):g}"}


# -- the sixteen prompts ----------------------------------------------------------------------------

CASES = {}


def case(question):
    def register(fn):
        CASES[question] = fn
        return fn
    return register


@case("Where did I leave my wallet?")
def _wallet(s, q):
    out = ask(s, q, [tool("find_entity", name="wallet"), tool("last_seen", object_id="object:wallet"),
                     final("Last confirmed sighting at 17:45 at the car. Earlier it was seen at 09:10 at "
                           "Blue Door Café.", cited=[WALLET_CAR, WALLET_CAFE])])
    passed_clean(out)
    routed(s, out, q, None)
    assert re.match(r"Last confirmed sighting at \d{2}:\d{2} at the car\b", out["answer"])
    assert out["cited_claim_ids"][0] == WALLET_CAR
    latest = claim_row(s, WALLET_CAR)
    assert latest["predicate"] == "located_at" and latest["event_time"] == f"{DAY}T17:45:00"


@case("Which restaurant did Alex recommend?")
def _restaurant(s, q):
    out = ask(s, q, [tool("search_claims", query="restaurant Alex recommended"),
                     final("Alex recommended Luna Taqueria, the taco place across from the office with the "
                           "green awning.", cited=[RECOMMENDED, SUMMARY["1230"]])])
    passed_clean(out)
    routed(s, out, q, None)
    assert "Luna Taqueria" in out["answer"]
    assert {claim_row(s, c)["predicate"] for c in out["cited_claim_ids"]} == {"recommended", "summary_of"}


@case("Who did I meet today?")
def _who(s, q):
    out = ask(s, q, [tool("search_claims", query="met with", predicate="met_with", **WHOLE_DAY),
                     tool("search_claims", query="office Alex", **WHOLE_DAY),
                     final("You met Alex, at the Office at 12:30.", cited=[MET_ALEX, AT_OFFICE])])
    passed_clean(out)
    routed(s, out, q, "time")
    assert "Alex" in out["answer"]
    assert claim_row(s, MET_ALEX)["predicate"] == "met_with" and MET_ALEX in out["cited_claim_ids"]


@case("What time was my meeting with Alex?")
def _meeting(s, q):
    out = ask(s, q, [tool("search_claims", query="meeting with Alex"),
                     final("Your meeting with Alex was at 12:30, at the Office.", cited=[MET_ALEX, AT_OFFICE])])
    passed_clean(out)
    routed(s, out, q, None)
    assert "12:30" in out["answer"] and MET_ALEX in out["cited_claim_ids"]
    assert claim_row(s, MET_ALEX)["event_time"] == f"{DAY}T12:30:00"


@case("Summarise my day.")
def _summary(s, q):
    out = ask(s, q, [tool("day_summary", **WHOLE_DAY),
                     final("Your day ran from 09:10 to 17:45. At 09:10 you were at Blue Door Café with your "
                           "wallet; at 09:40 you passed a billboard for Orbit Fitness on the street; at 12:30 "
                           "you met Alex at the Office, who recommended Luna Taqueria and said he would send "
                           "the proposal by Friday; at 17:45 your wallet was in the car.",
                           cited=list(SUMMARY.values()))])
    passed_clean(out)
    routed(s, out, q, "summary")
    assert len(episodes_of(s, out["cited_claim_ids"])) >= 3
    assert out["trace"][0]["args"]["time_from"].startswith(DAY)


@case("What happened this morning?")
def _morning(s, q):
    morning = {"time_from": f"{DAY}T05:00:00", "time_to": f"{DAY}T11:59:59"}
    out = ask(s, q, [tool("day_summary", **morning),
                     final("At 09:10 you were at Blue Door Café, with your brown wallet next to a coffee cup, "
                           "and at 09:40 you passed a billboard on the street advertising Orbit Fitness.",
                           cited=[SUMMARY["0910"], SUMMARY["0940"]])])
    passed_clean(out)
    routed(s, out, q, "time")
    # The morning holds two moments, and the answer covers both and nothing after noon.
    assert episodes_of(s, out["cited_claim_ids"]) == {"episode:20261029-0910", "episode:20261029-0940"}
    assert all(claim_row(s, c)["event_time"] < f"{DAY}T12:00:00" for c in out["cited_claim_ids"])
    assert out["trace"][0]["args"] == morning


@case("What was the most important moment?")
def _important(s, q):
    out = ask(s, q, [tool("day_summary", **WHOLE_DAY),
                     final("The most important moment was the 12:30 meeting with Alex at the Office: he "
                           "recommended Luna Taqueria and said he would send the proposal by Friday. The rest "
                           "was quieter: coffee at Blue Door Café at 09:10, a billboard at 09:40 and the "
                           "wallet in the car at 17:45.", cited=[SUMMARY["1230"], SUMMARY["0910"],
                                                                 SUMMARY["0940"], SUMMARY["1745"]])])
    passed_clean(out)
    routed(s, out, q, "summary")
    assert out["cited_claim_ids"][0] == SUMMARY["1230"]
    assert len(episodes_of(s, out["cited_claim_ids"])) >= 3


@case("Where did I spend the most time?")
def _most_time(s, q):
    # coverage ran, so the numbers in this claim-backed answer are checked against it and the claims
    out = ask(s, q, [tool("coverage"), tool("day_summary", **WHOLE_DAY),
                     final("At the Office with Alex: that meeting is the only stretch with any length, 45 min "
                           "from 12:30. Blue Door Café at 09:10, the street at 09:40 and the car at 17:45 are "
                           "single moments.", cited=[SUMMARY["1230"], SUMMARY["0910"], SUMMARY["0940"],
                                                     SUMMARY["1745"]], tools=["coverage"])])
    passed_clean(out)
    routed(s, out, q, "summary")
    assert "Office" in out["answer"] and out["cited_tools"] == ["coverage"]
    assert len(episodes_of(s, out["cited_claim_ids"])) >= 3


@case("What did I say I would do today?")
def _said_i_would(s, q):
    promise, _ = seed_todos(s)
    out = ask(s, q, [tool("open_todos"),
                     final("You said you would send Sam the budget (a note at 16:40).", cited=[promise])])
    passed_clean(out)
    routed(s, out, q, "todo")
    assert out["cited_claim_ids"] == [promise]
    assert claim_row(s, promise)["predicate"] == "committed_to" and claim_row(s, promise)["subject_id"] == "me"


@case("Did I promise anyone anything?")
def _promise(s, q):
    promise, _ = seed_todos(s)
    out = ask(s, q, [tool("open_todos"), final("Yes: you said you would send Sam the budget.", cited=[promise])])
    passed_clean(out)
    routed(s, out, q, "todo")
    assert out["cited_claim_ids"] == [promise] and "budget" in out["answer"]


@case("Did anyone ask me to do something?")
def _asked(s, q):
    _, request = seed_todos(s)
    out = ask(s, q, [tool("open_todos"), final("Alex asked you to review the draft, at 15:05.", cited=[request])])
    passed_clean(out)
    routed(s, out, q, "todo")
    row = claim_row(s, request)
    assert out["cited_claim_ids"] == [request] and row["predicate"] == "requested" and row["object_id"] == "me"


@case("What did I forget to follow up on?")
def _follow_up(s, q):
    promise, request = seed_todos(s)
    assert s.client.post(f"/todos/{promise}", json={"state": "done"}).status_code == 200
    out = ask(s, q, [tool("open_todos"),
                     final("Alex asked you to review the draft, and that is still open.", cited=[request])])
    passed_clean(out)
    routed(s, out, q, "todo")
    assert tool_calls(out) == [("open_todos", 1)]          # the done promise is no longer open
    assert out["cited_claim_ids"] == [request]


@case("What did the models read today?")
def _models(s, q):
    seed_usage(s)
    log = logged_for_day(s)
    assert log == {"calls": "3", "photos": "2", "words": "4200", "audio": "1.5"}
    out = ask(s, q, [tool("usage_stats", day=DAY),
                     final(f"For {DAY} the models made 3 calls: they read 4,200 words and 2 photos and heard "
                           "1.5 min of audio.", tools=["usage_stats"])])
    passed_clean(out)
    routed(s, out, q, "memory")
    assert out["cited_tools"] == ["usage_stats"] and out["cited_claim_ids"] == []
    assert numbers_in(out["answer"]) == {DAY, *log.values()}       # every figure is the log's own


@case("How much of my day is covered?")
def _covered(s, q):
    out = ask(s, q, [tool("coverage"),
                     final("25% of your waking hours hold a memory (4 of 16). The longest gap ran from 13:20 "
                           "to 17:45, 4 h 25 min.", tools=["coverage"])])
    passed_clean(out)
    routed(s, out, q, "memory")
    assert out["cited_tools"] == ["coverage"] and "4 h 25 min" in out["answer"] and "25%" in out["answer"]


@case("What happened between 13:20 and 17:45?")
def _between(s, q):
    window = {"time_from": f"{DAY}T13:20:00", "time_to": f"{DAY}T17:45:00"}
    out = ask(s, q, [tool("coverage", **window), tool("search_claims", query="Luna Taqueria wallet", **window),
                     final("Almost nothing: 0% of that window is covered. The memory holds only its edges, "
                           "Luna Taqueria at 13:20 and the wallet in the car at 17:45; the 4 h 25 min between "
                           "them is a gap.", cited=[LUNA_1320, WALLET_CAR], tools=["coverage"])])
    passed_clean(out)
    routed(s, out, q, "memory")
    assert out["cited_tools"] == ["coverage"] and "4 h 25 min" in out["answer"] and "0%" in out["answer"]
    assert out["trace"][0]["args"] == window


@case("What are you unsure about?")
def _unsure(s, q):
    out = ask(s, q, [tool("uncertain_claims"),
                     final("I am least sure about the 09:40 moment on the street: my summary of the billboard "
                           "for Orbit Fitness has low confidence.", cited=[LOW_CONFIDENCE])])
    passed_clean(out)
    routed(s, out, q, "memory")
    assert tool_calls(out) == [("uncertain_claims", 1)]
    assert out["cited_claim_ids"] == [LOW_CONFIDENCE] and claim_row(s, LOW_CONFIDENCE)["confidence"] < 0.6


def test_the_sixteen_prompts_each_have_a_case():
    assert len(set(ALL_PROMPTS)) == 16 and set(CASES) == set(ALL_PROMPTS)


@pytest.mark.parametrize("question", ALL_PROMPTS)
def test_prompt(sample, question):
    CASES[question](sample, question)


# -- abstentions ------------------------------------------------------------------------------------

def test_promise_question_abstains_when_the_owner_promised_nothing(sample):
    q = "Did I promise anyone anything?"
    out = ask(sample, q, [tool("open_todos"), tool("search_claims", query="promise will send"),
                          final("I have no record of you promising anyone anything.", status="abstained")])
    passed_clean(out, "abstained")
    assert "no record" in out["answer"] and out["cited_claim_ids"] == [] and out["citations"] == []
    assert tool_calls(out)[0] == ("open_todos", 0)        # Alex's own promise is not the owner's to-do


def test_request_question_abstains_when_nobody_asked(sample):
    q = "Did anyone ask me to do something?"
    out = ask(sample, q, [tool("open_todos"),
                          final("I have no record of anyone asking you to do something.", status="abstained")])
    passed_clean(out, "abstained")
    assert "no record" in out["answer"] and tool_calls(out) == [("open_todos", 0)]
    assert not sample.conn.execute("SELECT 1 FROM claims WHERE predicate='requested'").fetchone()


def test_unsure_question_abstains_when_nothing_is_uncertain(sample):
    sample.conn.execute("UPDATE claims SET confidence=0.7 WHERE claim_id=?", (LOW_CONFIDENCE,))
    sample.conn.commit()
    out = ask(sample, "What are you unsure about?", [tool("uncertain_claims"), final(
        "I have no record of anything I am unsure about: no claim is disputed or low in confidence.",
        status="abstained")])
    passed_clean(out, "abstained")
    assert tool_calls(out) == [("uncertain_claims", 0)] and "no record" in out["answer"]


# -- bad replies are still caught -------------------------------------------------------------------

def test_present_tense_wallet_reply_is_rejected_then_the_retry_passes(sample):
    good = "Last confirmed sighting at 17:45 at the car."
    out = ask(sample, "Where did I leave my wallet?", [
        tool("last_seen", object_id="object:wallet"),
        final("Your wallet is in the car.", cited=[WALLET_CAR]),
        final(good, cited=[WALLET_CAR])])
    assert out["status"] == "answered" and out["answer"] == good
    assert len(out["checks"]) == 1 and "Last confirmed sighting" in out["checks"][0]
    assert "Last confirmed sighting" in sample.llm.recall_payloads[-1]["steps_so_far"][-1]["checker"]


def test_invented_usage_number_is_rejected_and_replaced_by_the_template(sample):
    seed_usage(sample)
    bad = final("The models read 5,000 words today.", tools=["usage_stats"])
    out = ask(sample, "What did the models read today?", [tool("usage_stats", day=DAY), bad, bad])
    assert out["status"] == "answered" and out["cited_tools"] == ["usage_stats"]
    assert "5000" in out["checks"][0] and out["checks"][-1].startswith("fallback:")
    assert "5000" not in numbers_in(out["answer"])
    assert out["answer"].startswith("For that day: 3 calls, 4,200 words and 2 photos read, and 1.5 min of audio")


def test_invented_coverage_number_on_the_window_prompt_is_rejected(sample):
    window = {"time_from": f"{DAY}T13:20:00", "time_to": f"{DAY}T17:45:00"}
    bad = final("About 40% of that window is covered.", tools=["coverage"])
    out = ask(sample, "What happened between 13:20 and 17:45?", [tool("coverage", **window), bad, bad])
    assert "40" in out["checks"][0] and out["checks"][-1].startswith("fallback:")
    assert "4 h 25 min" in out["answer"] and "40" not in numbers_in(out["answer"])


def test_promise_citing_a_claim_never_shown_is_rejected(sample):
    """Alex's promise exists, but the model was never shown it (open_todos is empty) and it is not the
    owner's: citing it is refused, and the retry abstains."""
    out = ask(sample, "Did I promise anyone anything?", [
        tool("open_todos"),
        final("You promised to send the proposal by Friday.", cited=[ALEX_PROMISE]),
        final("I have no record of you promising anyone anything.", status="abstained")])
    assert out["status"] == "abstained" and out["cited_claim_ids"] == []
    assert "never returned by a tool" in out["checks"][0]


def test_an_answer_citing_nothing_is_rejected(sample):
    good = final("Alex recommended Luna Taqueria.", cited=[RECOMMENDED])
    out = ask(sample, "Which restaurant did Alex recommend?", [
        tool("search_claims", query="restaurant Alex recommended"), final("Luna Taqueria."), good])
    assert out["answer"] == "Alex recommended Luna Taqueria." and out["cited_claim_ids"] == [RECOMMENDED]
    assert out["checks"] == ["An answered or partial reply must cite at least one claim."]


# -- the extended prompt asks for the forms the number check reads ----------------------------------

def test_extended_addendum_asks_for_iso_dates_clock_times_and_unnumbered_lists():
    text = " ".join(EXTENDED_ADDENDUM.split())
    assert "Write dates as YYYY-MM-DD and times as HH:MM" in text
    assert "Do not number list items" in text


@pytest.mark.parametrize("answer", ["On October 29, 25% of waking hours is covered.",
                                    "Covered:\n1. 25% of waking hours\n2. the longest gap is 4 h 25 min"])
def test_prose_dates_and_numbered_lists_fail_the_number_check(sample, answer):
    """Why the addendum says so: a prose date or a list number is a figure no tool returned, so a good
    answer in that shape is degraded to the template after its retry."""
    reply = final(answer, tools=["coverage"])
    out = ask(sample, "How much of my day is covered?", [tool("coverage"), reply, reply])
    assert out["checks"][-1].startswith("fallback:")
