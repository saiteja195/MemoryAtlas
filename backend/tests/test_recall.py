import json

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.recall.investigator import MAX_STEPS, Investigator
from app.recall.tools import RecallTools

from .fakes import FakeLLM


def tool(name, **args):
    return {"action": "tool", "tool": name, "args": args}


def final(status="answered", answer="x", cited=(), note=""):
    return {"action": "final", "status": status, "answer": answer,
            "cited_claim_ids": list(cited), "uncertainty_note": note}


def ids(result):
    return [r["claim_id"] for r in result]


# -- tools ------------------------------------------------------------------------------------

def test_search_finds_the_derived_recommendation(played):
    t = RecallTools(played.conn)
    hits = t.run("search_claims", {"query": "restaurant Alex recommended"})
    top = hits[0]
    assert top["predicate"] == "recommended" and top["object"] == "Luna Taqueria"
    assert top["supported_by"] == ["derived:spatial_referent_resolution"]
    assert top["claim_id"] in t.returned


def test_search_filters_and_hides_bookkeeping_claims(played):
    t = RecallTools(played.conn)
    assert all(h["predicate"] != "part_of_episode"
               for h in t.run("search_claims", {"query": "episode", "k": 12}))
    only = t.run("search_claims", {"query": "wallet", "predicate": "located_at"})
    assert only and {h["predicate"] for h in only} == {"located_at"}
    assert t.run("search_claims", {"query": "wallet", "time_from": "2026-10-29T20:00:00"}) == []


def test_find_entity_resolves_the_alias(played):
    t = RecallTools(played.conn)
    (hit,) = [h for h in t.run("find_entity", {"name": "taco place"})
              if h["entity_id"] == "place:luna-taqueria"]
    assert "taco place" in hit["aliases"]
    assert t.run("find_entity", {"name": "nobody here"}) == []


def test_timeline_hides_superseded_unless_asked(full_day):
    t = RecallTools(full_day.conn)
    plain = t.run("timeline", {"entity_id": "object:wallet"})
    assert all(c["status"] != "superseded" for c in plain)
    hist = t.run("timeline", {"entity_id": "object:wallet", "include_history": True})
    assert any(c["status"] == "superseded" for c in hist)
    assert [c["when"] for c in hist] == sorted(c["when"] for c in hist if c["when"])


def test_last_seen_returns_latest_context_and_history(full_day):
    out = RecallTools(full_day.conn).run("last_seen", {"object_id": "object:wallet"})
    assert out["latest"]["when"].endswith("17:45") and out["latest"]["object"] == "Car"
    assert [c["when"][-5:] for c in out["earlier_sightings"]] == ["09:10"]
    assert RecallTools(full_day.conn).run("last_seen", {"object_id": "object:billboard"})["latest"] is None


def test_last_seen_reports_conflicts(demo):
    demo.advance(1)
    demo.engine.llm.rules.append(("Desk", [__import__("tests.fakes", fromlist=["claim"]).claim(
        "wallet", "located_at", "Desk", subject_type="object", object_type="place")]))
    demo.engine.ingest(__import__("app.capture.models", fromlist=["RawCapture"]).RawCapture(
        kind="frame", session_id="day-1", captured_at="2026-10-29T09:12:00",
        perception={"caption": "Wallet on a desk", "ocr_text": ["Desk"]}))
    out = RecallTools(demo.conn).run("last_seen", {"object_id": "object:wallet"})
    assert "conflict" in out["note"]


def test_episodes_and_neighbors(played):
    t = RecallTools(played.conn)
    eps = t.run("episodes", {"time_from": "2026-10-29T12:00:00", "time_to": "2026-10-29T14:00:00"})
    assert len(eps) == 1 and {"Alex", "Me"} <= set(eps[0]["participants"]) and "summary" in eps[0]
    near = t.run("episodes", {"near_lat": 37.7893, "near_lon": -122.4008})
    assert len(near) == 1 and near[0]["start"].endswith("09:10")
    nb = t.run("neighbors", {"entity_id": "place:luna-taqueria"})
    assert nb and all(c["predicate"] != "part_of_episode" for c in nb)


def test_provenance_walks_down_to_sources(played):
    t = RecallTools(played.conn)
    rec = t.run("search_claims", {"query": "Alex recommended Luna", "predicate": "recommended"})[0]
    tree = t.run("provenance", {"claim_id": rec["claim_id"]})
    (j,) = tree["justifications"]
    assert j["kind"] == "derivation" and j["rule"] == "spatial_referent_resolution"
    kinds = {s["source"]["kind"] for p in j["premises"] for s in p["justifications"]
             if s["kind"] == "source"}
    # the sign (frame), the utterance (transcript) and where the conversation was (calendar)
    assert kinds == {"transcript_segment", "frame_observation", "calendar_event"}
    assert all(p["claim_id"] in t.returned for p in j["premises"])


def test_tools_reject_bad_input_without_raising(played):
    t = RecallTools(played.conn)
    assert "unknown tool" in t.run("drop_tables", {})["error"]
    assert "bad arguments" in t.run("search_claims", {"nonsense": 1})["error"]
    assert t.run("provenance", {"claim_id": "clm-doesnotexist"}) == {"error": "claim not available"}


def test_tools_never_return_what_consent_no_longer_covers(played):
    conn = played.conn
    conn.execute("UPDATE consent_grants SET revoked_at='2026-10-29T14:00:00' WHERE grantor='alex'")
    t = RecallTools(conn)
    texts = " ".join(h["text"] for q in ("restaurant Alex recommended", "proposal Friday",
                                         "al pastor taco") for h in t.run("search_claims", {"query": q}))
    assert "recommended Luna" not in texts and "proposal" not in texts
    assert "Luna Taqueria has a green awning" in " ".join(
        h["text"] for h in t.run("search_claims", {"query": "Luna awning"}))     # the sign survives
    assert any(c["predicate"] == "met_with" for c in t.run("neighbors", {"entity_id": "person:alex"}))
    src_texts = json.dumps(t.run("provenance", {"claim_id": next(
        h["claim_id"] for h in t.run("search_claims", {"query": "met with Alex"})
        if h["predicate"] == "met_with")}))
    assert "taco place" not in src_texts            # the transcript source is not shown


# -- investigator loop and post-checks --------------------------------------------------------

def ask(demo, replies, q="Which restaurant did Alex recommend?"):
    llm = demo.engine.llm
    llm.recall_replies[:] = replies
    inv = Investigator(demo.conn, llm)
    return inv, inv.ask(q)


def rec_id(demo):
    return RecallTools(demo.conn).run("search_claims", {"query": "Alex recommended Luna",
                                                        "predicate": "recommended"})[0]["claim_id"]


def test_answer_with_valid_citation(played):
    cid = rec_id(played)
    _, a = ask(played, [tool("search_claims", query="restaurant Alex recommended"),
                        final(answer="Alex recommended Luna Taqueria.", cited=[cid])])
    assert (a.status, a.cited_claim_ids, a.steps) == ("answered", [cid], 2)
    assert a.trace[0]["tool"] == "search_claims" and a.checks == []


def test_invented_citation_is_retried_then_accepted(played):
    cid = rec_id(played)
    _, a = ask(played, [tool("search_claims", query="Alex recommended"),
                        final(answer="Luna.", cited=["clm-000000000000"]),
                        final(answer="Luna Taqueria.", cited=[cid])])
    assert a.status == "answered" and len(a.checks) == 1 and "never returned" in a.checks[0]


def test_invented_citation_twice_abstains(played):
    _, a = ask(played, [tool("search_claims", query="Alex recommended"),
                        final(answer="Luna.", cited=["clm-000000000000"]),
                        final(answer="Luna.", cited=["clm-000000000001"])])
    assert a.status == "abstained" and a.cited_claim_ids == [] and "twice" in a.uncertainty_note


def test_answer_without_any_tool_call_cannot_cite(played):
    _, a = ask(played, [final(answer="Luna.", cited=[rec_id(played)]),
                        final(status="abstained", answer="No record.")])
    assert a.status == "abstained"       # the id was never shown to the model in this run


def test_answered_needs_a_citation(played):
    _, a = ask(played, [tool("search_claims", query="Alex"), final(answer="Luna."),
                        final(answer="Luna.")])
    assert a.status == "abstained" and "at least one claim" in " ".join(a.checks)


def test_object_location_must_be_phrased_as_last_sighting(full_day):
    t = RecallTools(full_day.conn)
    car = t.run("last_seen", {"object_id": "object:wallet"})["latest"]["claim_id"]
    _, a = ask(full_day, [tool("last_seen", object_id="object:wallet"),
                          final(answer="Your wallet is in the car.", cited=[car]),
                          final(answer="Last confirmed sighting at 17:45 in the car.", cited=[car])],
               q="Where is my wallet?")
    assert a.status == "answered" and "Last confirmed sighting" in a.answer
    assert "present tense" in a.checks[0]


def test_location_phrasing_is_only_enforced_for_the_object_asked_about(full_day):
    car = RecallTools(full_day.conn).run("last_seen", {"object_id": "object:wallet"}
                                         )["latest"]["claim_id"]
    _, a = ask(full_day, [tool("last_seen", object_id="object:wallet"),
                          final(answer="Nothing to report.", cited=[car])],
               q="What colour was the awning?")
    assert a.status == "answered" and a.checks == []


def test_present_tense_location_twice_abstains(full_day):
    car = RecallTools(full_day.conn).run("last_seen", {"object_id": "object:wallet"}
                                         )["latest"]["claim_id"]
    _, a = ask(full_day, [tool("last_seen", object_id="object:wallet"),
                          final(answer="It is in the car.", cited=[car]),
                          final(answer="It is in the car now.", cited=[car])],
               q="Where is my wallet?")
    assert a.status == "abstained"


def test_citing_a_claim_whose_consent_was_withdrawn_is_refused(played):
    cid = rec_id(played)
    llm = played.engine.llm
    llm.recall_replies[:] = [tool("search_claims", query="Alex recommended"),
                             final(answer="Luna.", cited=[cid]),
                             final(status="abstained", answer="No record.")]
    inv = Investigator(played.conn, llm)
    orig = inv._check

    def revoke_then_check(step, tools, question):   # consent is withdrawn mid-question
        played.conn.execute("UPDATE consent_grants SET revoked_at='x' WHERE grantor='alex'")
        return orig(step, tools, question)

    inv._check = revoke_then_check
    a = inv.ask("Which restaurant did Alex recommend?")
    assert a.status == "abstained" and "no longer valid" in " ".join(a.checks)


def test_disputed_evidence_adds_a_conflict_note(played):
    cid = rec_id(played)
    played.conn.execute("UPDATE claims SET status='disputed' WHERE claim_id=?", (cid,))
    _, a = ask(played, [tool("search_claims", query="Alex recommended"),
                        final(answer="Luna.", cited=[cid])])
    assert a.status == "answered" and "conflicts" in a.uncertainty_note


def test_step_limit_abstains(played):
    _, a = ask(played, [tool("search_claims", query="x")] * (MAX_STEPS + 2))
    assert a.status == "abstained" and "step limit" in a.uncertainty_note


def test_invalid_step_is_repaired_once(played):
    _, a = ask(played, [{"action": "dance"}, final(status="abstained", answer="No record.")])
    assert a.status == "abstained" and a.answer == "No record."
    assert "invalid" in played.engine.llm.calls[-1][1]


def test_questions_are_stateless(played):
    llm = played.engine.llm
    llm.recall_replies[:] = [final(status="abstained", answer="a"),
                             final(status="abstained", answer="b")]
    inv = Investigator(played.conn, llm)
    inv.ask("What is the secret word zebra?")
    inv.ask("Anything else?")
    second = llm.recall_payloads[-1]
    assert second["question"] == "Anything else?" and second["steps_so_far"] == []
    assert "zebra" not in json.dumps(second)


# -- API --------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    llm = FakeLLM()
    c = TestClient(create_app(Settings(db_path=":memory:", llm_mode="live", cache_dir=str(tmp_path)), llm))
    c.llm = llm
    c.post("/demo/advance", params={"steps": 10})
    return c


def test_ask_endpoint_caches_until_the_graph_changes(client):
    cid = client.get("/graph").json()
    rec = next(e["id"] for e in cid["edges"] if e["predicate"] == "recommended")
    client.llm.recall_replies[:] = [tool("search_claims", query="Alex recommended"),
                                    final(answer="Luna Taqueria.", cited=[rec]),
                                    final(status="abstained", answer="No record.")]
    first = client.post("/recall/ask", json={"question": "Which restaurant did Alex recommend?"}).json()
    assert first["status"] == "answered" and first["cached"] is False
    assert first["citations"][0]["object"] == "Luna Taqueria"
    again = client.post("/recall/ask", json={"question": " which restaurant did ALEX recommend? "}).json()
    assert again["cached"] is True and len(client.llm.recall_payloads) == 2
    client.post("/demo/live/F4")                   # the graph changed: cache must not be reused
    third = client.post("/recall/ask", json={"question": "Which restaurant did Alex recommend?"}).json()
    assert third["cached"] is False and third["status"] == "abstained"
    rows = client.app.state.conn.execute("SELECT role, claim_ids FROM chat_messages").fetchall()
    assert [r["role"] for r in rows] == ["user", "assistant"] * 3
    assert rec in rows[1]["claim_ids"]


def test_provenance_endpoint(client):
    g = client.get("/graph").json()
    rec = next(e["id"] for e in g["edges"] if e["predicate"] == "recommended")
    tree = client.get(f"/claims/{rec}/provenance").json()
    assert tree["justifications"][0]["rule"] == "spatial_referent_resolution"
    assert client.get("/claims/clm-nope/provenance").status_code == 404
    assert client.post("/recall/ask", json={"question": "hi"}).status_code == 422
