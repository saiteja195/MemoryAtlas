"""The five extra recall tools (day_summary, open_todos, coverage, usage_stats, uncertain_claims):
exact results on the staged day, the privacy filter on every claim they show, and the wiring that
registers them only for questions the router sends to the extended prompt."""
import json

from app.privacy import clock
from app.privacy.filter import authorized_claim_ids
from app.recall.investigator import CLAIM_ID_RE, Investigator
from app.recall.tools import MAX_K, RecallTools

from .fakes import FakeLLM

DAY = "2026-10-29"
ORIGINAL = {"search_claims", "find_entity", "timeline", "last_seen", "episodes", "neighbors", "provenance"}
EXTRA = {"day_summary", "open_todos", "coverage", "usage_stats", "uncertain_claims"}


def ext(conn):
    return RecallTools(conn, extended=True)


def ids_in(result) -> set[str]:
    return set(CLAIM_ID_RE.findall(json.dumps(result)))


def add_grant(conn, grant, grantor="me"):
    conn.execute("INSERT INTO consent_grants(grant_id, grantor, scope, scope_ref, purposes, token_hash,"
                 " granted_at) VALUES (?,?,?,?,?,?,?)",
                 (grant, grantor, "capture_session", grant, json.dumps(["personal_recall"]), "h", clock.now_iso()))


def add_claim(conn, cid, grant, *, predicate="committed_to", subject="me", obj=None, value=None, at=f"{DAY}T10:00:00",
              status="active", confidence=0.9, text=None):
    """A claim justified by its own source under its own grant, so revoking the grant forgets it."""
    if not conn.execute("SELECT 1 FROM consent_grants WHERE grant_id=?", (grant,)).fetchone():
        add_grant(conn, grant)
    src = f"src-{cid}"
    conn.execute("INSERT INTO sources(source_id, kind, grant_id, captured_at, ingested_at, content_hash)"
                 " VALUES (?,?,?,?,?,?)", (src, "user_confirmation", grant, at, at, src))
    conn.execute("INSERT INTO claims(claim_id, subject_id, predicate, object_id, object_value, event_time,"
                 " evidence_type, confidence, status, text, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (cid, subject, predicate, obj, value, at, "direct_observation", confidence, status,
                  text or f"{cid} text", at))
    conn.execute("INSERT INTO justifications(justification_id, claim_id, kind, source_id) VALUES (?,?,?,?)",
                 (f"j-{cid}", cid, "source", src))
    conn.commit()


def revoke(conn, grant):
    conn.execute("UPDATE consent_grants SET revoked_at=? WHERE grant_id=?", (clock.now_iso(), grant))
    conn.commit()


# -- registry ------------------------------------------------------------------------------------

def test_extended_tools_are_absent_by_default(conn):
    assert set(RecallTools(conn).registry) == ORIGINAL
    assert set(RecallTools(conn, extended=False).registry) == ORIGINAL
    assert set(RecallTools(conn, extended=True).registry) == ORIGINAL | EXTRA
    out = RecallTools(conn).run("coverage", {})
    assert "unknown tool" in out["error"]


# -- day_summary ----------------------------------------------------------------------------------

def test_day_summary_of_the_whole_staged_day(full_day):
    tools = ext(full_day.conn)
    out = tools.run("day_summary", {"time_from": f"{DAY}T00:00:00", "time_to": f"{DAY}T23:59:59"})
    assert [m["name"] for m in out["moments"]] == [
        "Episode 09:10", "Episode 09:40", "Episode 12:30-13:20", "Episode 17:45"]
    assert out["people"] == ["Alex"]
    assert out["places"] == ["Blue Door Café", "Car", "Luna Taqueria", "Office", "taco place"]
    assert out["counts"]["moments"] == 4 and out["counts"]["people"] == 1 and out["counts"]["places"] == 5
    assert out["counts"]["claims"] > 0
    lunch = out["moments"][2]
    assert lunch["start"] == f"{DAY} 12:30" and lunch["end"] == f"{DAY} 13:20"
    assert "Alex" in lunch["participants"] and lunch["summary"]["text"].startswith("Summary of")
    # every claim id the model was shown is recorded, so a citation of it can be checked
    assert ids_in(out) and ids_in(out) <= tools.returned


def test_day_summary_of_one_window(full_day):
    tools = ext(full_day.conn)
    out = tools.run("day_summary", {"time_from": f"{DAY}T12:00:00", "time_to": f"{DAY}T14:00:00"})
    assert [m["name"] for m in out["moments"]] == ["Episode 12:30-13:20"]
    assert out["people"] == ["Alex"]
    assert out["places"] == ["Luna Taqueria", "Office", "taco place"]
    assert out["counts"]["moments"] == 1
    assert "note" not in out


def test_unknown_window_returns_empty_not_error(full_day):
    tools = ext(full_day.conn)
    for name, args in (("day_summary", {"time_from": "2026-11-20T00:00:00", "time_to": "2026-11-20T23:59:59"}),
                       ("coverage", {"time_from": "2026-11-20T00:00:00", "time_to": "2026-11-20T23:59:59"}),
                       ("usage_stats", {"day": "2026-11-20"})):
        out = tools.run(name, args)
        assert isinstance(out, dict) and "error" not in out, name
    summary = tools.run("day_summary", {"time_from": "2026-11-20T00:00:00", "time_to": "2026-11-20T23:59:59"})
    assert summary["moments"] == [] and summary["people"] == [] and summary["places"] == []
    assert summary["counts"] == {"moments": 0, "claims": 0, "people": 0, "places": 0}
    assert "2026-10-29" in summary["note"]                    # says what the memory does cover
    cov = tools.run("coverage", {"time_from": "2026-11-20T00:00:00"})
    assert cov["day"] == "2026-11-20" and cov["spans"] == [] and cov["gaps"] == [] and cov["longest_gap"] is None
    assert tools.run("usage_stats", {"day": "2026-11-20"})["day"] is None
    assert tools.returned == set()


def test_day_summary_without_memory_is_empty(conn):
    out = ext(conn).run("day_summary", {"time_from": f"{DAY}T00:00:00", "time_to": f"{DAY}T23:59:59"})
    assert out["moments"] == [] and out["counts"]["moments"] == 0


def test_day_summary_needs_both_ends(conn):
    out = ext(conn).run("day_summary", {"time_from": f"{DAY}T00:00:00"})
    assert "bad arguments for day_summary" in out["error"]


# -- open_todos -----------------------------------------------------------------------------------

def test_open_todos_lists_the_owners_open_items(full_day):
    conn = full_day.conn
    add_claim(conn, "c-promise", "gp", value="send Sam the budget", at=f"{DAY}T16:40:00")
    add_claim(conn, "c-ask", "gq", predicate="requested", subject="person:alex", obj="me",
              value="review the draft", at=f"{DAY}T15:05:00")
    add_claim(conn, "c-done", "gd", value="water the plants", at=f"{DAY}T08:00:00")
    conn.execute("INSERT INTO todo_state(claim_id, state, updated_at) VALUES ('c-done','done','t')")
    conn.commit()
    tools = ext(conn)
    out = tools.run("open_todos", {})
    assert [(t["claim_id"], t["kind"], t["text"], t["who"], t["when"], t["state"]) for t in out] == [
        ("c-ask", "request", "review the draft", "Alex", "15:05", "open"),
        ("c-promise", "promise", "send Sam the budget", None, "16:40", "open")]
    assert tools.returned == {"c-ask", "c-promise"}
    assert tools.stats_returned == {}


def test_open_todos_empty_when_there_are_none(full_day):
    assert ext(full_day.conn).run("open_todos", {}) == []


def test_open_todos_uses_the_owner_it_is_given(full_day):
    conn = full_day.conn
    conn.execute("INSERT INTO entities(entity_id, type, name, attrs) VALUES ('ann','person','Ann','{}')")
    add_claim(conn, "c-ann", "ga", subject="ann", value="call the bank")
    assert ext(conn).run("open_todos", {}) == []
    assert [t["claim_id"] for t in RecallTools(conn, extended=True, owner="ann").run("open_todos", {})] == ["c-ann"]


# -- coverage -------------------------------------------------------------------------------------

def test_coverage_of_the_staged_day(full_day):
    tools = ext(full_day.conn)
    out = tools.run("coverage", {})                           # the latest memory day
    assert out["day"] == DAY and out["window"] == ["06:00", "22:00"]
    assert out["longest_gap"] == {"start": "13:20", "end": "17:45", "minutes": 265, "duration": "4 h 25 min"}
    assert out["gaps"] == [
        {"start": "06:00", "end": "09:10", "minutes": 190, "duration": "3 h 10 min"},
        {"start": "09:10", "end": "09:40", "minutes": 30, "duration": "30 min"},
        {"start": "09:40", "end": "12:30", "minutes": 170, "duration": "2 h 50 min"},
        {"start": "13:20", "end": "17:45", "minutes": 265, "duration": "4 h 25 min"},
        {"start": "17:45", "end": "22:00", "minutes": 255, "duration": "4 h 15 min"}]
    assert out["spans"][2] == {"start": "12:30", "end": "13:15", "minutes": 45, "duration": "45 min"}
    assert out["covered_hours"] == 4 and out["waking_hours"] == 16
    assert out["share"] == 0.25 and out["share_text"] == "25%"
    assert out["busiest_hour"] == 12 and out["busiest_hour_text"] == "12:00"
    assert tools.returned == set()                            # a stats tool shows no claim
    assert tools.stats_returned["coverage"] is out            # the raw result, kept for checking numbers


def test_coverage_of_a_window_on_the_day(full_day):
    out = ext(full_day.conn).run("coverage", {"time_from": f"{DAY}T12:00:00", "time_to": f"{DAY}T14:00:00"})
    assert out["day"] == DAY and out["window"] == ["12:00", "14:00"]
    assert out["longest_gap"] == {"start": "13:20", "end": "14:00", "minutes": 40, "duration": "40 min"}
    assert out["gaps"] == [{"start": "12:00", "end": "12:30", "minutes": 30, "duration": "30 min"},
                           {"start": "13:20", "end": "14:00", "minutes": 40, "duration": "40 min"}]
    assert out["covered_hours"] == 2 and out["waking_hours"] == 2


def test_coverage_forgets_a_withdrawn_source(full_day):
    conn = full_day.conn
    add_claim(conn, "c-late", "gl", at=f"{DAY}T20:00:00")
    spans = ext(conn).run("coverage", {})["spans"]
    assert {"start": "20:00", "end": "20:00", "minutes": 0, "duration": "0 min"} in spans
    revoke(conn, "gl")
    out = ext(conn).run("coverage", {})
    assert [s["start"] for s in out["spans"]] == ["09:10", "09:40", "12:30", "13:20", "17:45"]
    assert out["longest_gap"]["minutes"] == 265


# -- usage_stats ----------------------------------------------------------------------------------

def add_call(conn, cid, **kw):
    row = {"at": f"{DAY}T18:00:00", "model": "muse-spark", "kind": "text", "purpose": "answer", "memory_day": DAY,
           "served_from": "live", "duration_ms": 1500, "ok": 1, "images": 0, "words_in": 0, "words_out": 0,
           "audio_ms": 0, **kw}
    conn.execute(f"INSERT INTO model_calls(call_id, {', '.join(row)}) VALUES (?, {', '.join('?' * len(row))})",
                 (cid, *row.values()))
    conn.commit()


def test_usage_stats_has_raw_and_formatted_figures(full_day):
    conn = full_day.conn
    add_call(conn, "a", words_in=1200)
    add_call(conn, "b", purpose="read_memory", served_from="cache", images=2, words_in=3000, audio_ms=90000,
             duration_ms=0)
    add_call(conn, "c", memory_day="2026-10-30", ok=0, duration_ms=500)
    tools = ext(conn)
    out = tools.run("usage_stats", {"day": DAY})
    assert out["recorded"] is True
    assert out["total"]["calls"] == 3 and out["total"]["failed"] == 1 and out["total"]["words_read"] == 4200
    assert out["total"]["audio_minutes"] == 1.5 and out["total"]["photos"] == 2
    assert out["total"]["formatted"] == {"calls": "3", "photos": "2", "words_read": "4,200",
                                         "audio": "1.5 min", "avg_time": "1.0 s"}
    assert out["day"]["calls"] == 2 and out["day"]["formatted"]["words_read"] == "4,200"
    assert out["day"]["formatted"]["avg_time"] == "1.5 s"
    assert out["models"][0]["model"] == "muse-spark" and out["models"][0]["formatted"]["calls"] == "3"
    assert tools.returned == set() and tools.stats_returned["usage_stats"] is out
    assert tools.run("usage_stats", {})["day"] is None        # no day asked: totals only


def test_usage_stats_before_anything_was_recorded(full_day):
    out = ext(full_day.conn).run("usage_stats", {})
    assert out["recorded"] is False and out["total"]["calls"] == 0 and out["models"] == []


# -- uncertain_claims -----------------------------------------------------------------------------

def test_uncertain_claims_are_disputed_or_low_confidence_newest_first(full_day):
    conn = full_day.conn
    add_claim(conn, "u-old", "g1", predicate="said", value="x", at=f"{DAY}T09:00:00", confidence=0.5)
    add_claim(conn, "u-disputed", "g2", predicate="said", value="y", at=f"{DAY}T11:00:00", status="disputed")
    add_claim(conn, "u-new", "g3", predicate="said", value="z", at=f"{DAY}T14:00:00", confidence=0.59)
    add_claim(conn, "sure", "g4", predicate="said", value="w", at=f"{DAY}T15:00:00", confidence=0.6)
    add_claim(conn, "gone", "g5", predicate="said", value="v", at=f"{DAY}T16:00:00", confidence=0.1)
    add_claim(conn, "old-version", "g6", predicate="said", value="u", at=f"{DAY}T17:00:00", confidence=0.1,
              status="superseded")
    revoke(conn, "g5")
    tools = ext(conn)
    out = tools.run("uncertain_claims", {})
    assert [c["claim_id"] for c in out] == ["u-new", "u-disputed", "u-old"]
    assert [c["why"] for c in out] == [["low confidence"], ["disputed"], ["low confidence"]]
    assert tools.returned == {"u-new", "u-disputed", "u-old"}


def test_uncertain_claims_are_capped(full_day):
    conn = full_day.conn
    for i in range(MAX_K + 5):
        add_claim(conn, f"low-{i:02d}", f"gl{i}", predicate="said", value="x", at=f"{DAY}T10:{i:02d}:00",
                  confidence=0.3)
    out = ext(conn).run("uncertain_claims", {})
    assert len(out) == MAX_K and out[0]["claim_id"] == f"low-{MAX_K + 4:02d}"


# -- forgetting -----------------------------------------------------------------------------------

def test_forgotten_claims_never_appear(full_day):
    conn = full_day.conn
    add_claim(conn, "t-gone", "gt", value="send Sam the budget", at=f"{DAY}T12:45:00", text="Me will send Sam the budget")
    add_claim(conn, "u-gone", "gu", predicate="said", value="secret remark", at=f"{DAY}T12:50:00",
              confidence=0.2, text="Alex muttered a secret remark")
    add_claim(conn, "u-gone2", "gu", predicate="said", value="disputed remark", at=f"{DAY}T12:55:00",
              status="disputed", text="Alex made a disputed remark")
    window = {"time_from": f"{DAY}T12:00:00", "time_to": f"{DAY}T14:00:00"}

    def snapshot():
        tools = ext(conn)
        return {"day_summary": tools.run("day_summary", window), "open_todos": tools.run("open_todos", {}),
                "uncertain_claims": tools.run("uncertain_claims", {}), "tools": tools}

    before = snapshot()
    assert "t-gone" in json.dumps(before["open_todos"])
    assert {"u-gone", "u-gone2"} <= {c["claim_id"] for c in before["uncertain_claims"]}
    assert "Alex said to try the taco place" in json.dumps(before["day_summary"])
    revoke(conn, "gt")
    revoke(conn, "gu")
    conn.execute("UPDATE consent_grants SET revoked_at=? WHERE grantor='alex'", (clock.now_iso(),))
    conn.commit()
    after = snapshot()
    ok = authorized_claim_ids(conn)
    for name in ("day_summary", "open_todos", "uncertain_claims"):
        text = json.dumps(after[name])
        assert not ({"t-gone", "u-gone", "u-gone2"} & ids_in(after[name])), name
        assert ids_in(after[name]) <= ok, name
        for word in ("send Sam the budget", "secret remark", "disputed remark", "al pastor", "Alex said to try"):
            assert word not in text, (name, word)
    assert after["open_todos"] == []
    assert "taco place" not in after["day_summary"]["places"]      # only the withdrawn talk named it
    assert after["tools"].returned <= ok


# -- wiring ---------------------------------------------------------------------------------------

def tool_step(tool, args=None):
    return {"action": "tool", "tool": tool, "args": args or {}}


def abstain():
    return {"action": "final", "status": "abstained", "answer": "No record.", "cited_claim_ids": [],
            "uncertainty_note": ""}


def test_a_routed_question_gets_the_extra_tools(full_day):
    llm = FakeLLM()
    llm.recall_replies[:] = [tool_step("coverage", {}), abstain()]
    ans = Investigator(full_day.conn, llm).ask("How much of my day is covered?", as_of=DAY)
    assert ans.trace[0]["tool"] == "coverage" and ans.trace[0]["results"] == 1


def test_an_unrouted_question_does_not(full_day):
    llm = FakeLLM()
    llm.recall_replies[:] = [tool_step("coverage", {}), abstain()]
    ans = Investigator(full_day.conn, llm).ask("Which restaurant did Alex recommend?", as_of=DAY)
    assert ans.trace[0] == {"tool": "coverage", "args": {}, "results": 0}     # unknown tool: an error
    assert "unknown tool" in json.dumps(llm.recall_payloads[1]["steps_so_far"])


def test_a_citation_of_a_summary_moment_is_accepted(full_day):
    llm = FakeLLM()
    window = {"time_from": f"{DAY}T12:00:00", "time_to": f"{DAY}T14:00:00"}
    llm.recall_replies[:] = [tool_step("day_summary", window)]
    inv = Investigator(full_day.conn, llm)
    # learn the summary claim id the tool will show, then answer citing it
    cid = ext(full_day.conn).run("day_summary", window)["moments"][0]["summary"]["claim_id"]
    llm.recall_replies.append({"action": "final", "status": "answered", "answer": "You had lunch with Alex.",
                               "cited_claim_ids": [cid], "uncertainty_note": ""})
    ans = inv.ask("What happened this afternoon?", as_of=DAY)
    assert ans.status == "answered" and ans.cited_claim_ids == [cid]
