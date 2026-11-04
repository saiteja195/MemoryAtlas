"""Answers about the memory itself (coverage, model usage) cite the tool result instead of a claim.
Code checks every number in such an answer against that result; a failure gets the usual one retry,
and a second failure is replaced by a deterministic sentence built from the result (templates.py),
never by an unchecked number. Such answers are never cached: usage changes without the graph."""
import pytest

from app.recall.investigator import Investigator, numbers_in, stats_numbers
from app.recall.service import RecallService
from app.recall.templates import render_coverage, render_usage
from app.recall.tools import RecallTools

from .fakes import FakeLLM
from .test_tools_extra import add_call

DAY = "2026-10-29"
COVERAGE_Q = "How much of my day is covered?"          # routed: memory
USAGE_Q = "How many words did the models read?"          # routed: memory


def tool(name, **args):
    return {"action": "tool", "tool": name, "args": args}


def final(answer, tools=(), cited=(), status="answered", note=""):
    return {"action": "final", "status": status, "answer": answer, "cited_claim_ids": list(cited),
            "cited_tools": list(tools), "uncertainty_note": note}


def run(conn, replies, question=COVERAGE_Q, as_of=DAY):
    llm = FakeLLM()
    llm.recall_replies[:] = replies
    return Investigator(conn, llm).ask(question, as_of=as_of), llm


def stats(conn, name, **args):
    return RecallTools(conn, extended=True).run(name, args)


# -- numbers ---------------------------------------------------------------------------------------

def test_numbers_in_normalises_separators_trailing_zero_and_clock_times():
    assert numbers_in("4,200 words, 3.0 s, at 9:05 and 13:20, 25%") == {"4200", "3", "09:05", "13:20", "25"}
    assert numbers_in("no digits here") == set()
    assert stats_numbers({"a": 265, "b": "4 h 25 min", "c": [0.25, {"d": "13:20"}], "e": True}) == \
        {"265", "4", "25", "0.25", "13:20"}


def test_a_date_is_one_token_so_its_parts_do_not_feed_the_allowed_set():
    assert numbers_in("on 2026-10-29") == {"2026-10-29"}
    assert numbers_in("at 2026-10-29T12:30:00 and 2026-10-29 09:05") == {"2026-10-29", "12:30", "09:05"}
    assert stats_numbers({"day": "2026-10-29", "note": "The memory covers: 2026-10-28, 2026-10-29."}) == \
        {"2026-10-28", "2026-10-29"}


AFTERNOON = {"time_from": f"{DAY}T12:00:00", "time_to": f"{DAY}T14:00:00"}


@pytest.mark.parametrize("pct", ["29", "10"])
def test_a_percentage_from_the_date_is_retried_then_replaced(full_day, pct):
    text = f"You covered {pct}% of the window."
    ans, _ = run(full_day.conn, [tool("coverage", **AFTERNOON), final(text, ["coverage"]), final(text, ["coverage"])],
                 question="How much of my afternoon is covered?")
    assert pct in ans.checks[0] and any("fallback" in c for c in ans.checks)
    assert ans.answer == render_coverage(stats(full_day.conn, "coverage", **AFTERNOON))


def test_29_percent_of_the_whole_day_is_retried_too(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final("You covered 29% of your day", ["coverage"]),
                                 final("You covered 29% of your day", ["coverage"])])
    assert any("fallback" in c for c in ans.checks)


def test_a_reply_that_states_the_date_still_passes(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final("On 2026-10-29, 25% of waking hours is covered.", ["coverage"])])
    assert ans.status == "answered" and ans.checks == []


# -- claim-only replies after a stats tool ran ---------------------------------------------------

def _summary_claim(conn):
    return stats(conn, "day_summary", **AFTERNOON)["moments"][0]["summary"]["claim_id"]


def test_a_claim_only_reply_with_an_invented_percentage_after_coverage_is_replaced(full_day):
    conn = full_day.conn
    cid = _summary_claim(conn)
    text = "You covered 90% of your day."
    ans, llm = run(conn, [tool("coverage"), tool("day_summary", **AFTERNOON), final(text, cited=[cid]),
                          final(text, cited=[cid])])
    assert "90" in llm.recall_payloads[3]["steps_so_far"][-1]["checker"]
    assert ans.answer == render_coverage(stats(conn, "coverage")) and ans.status == "answered"
    assert ans.cited_tools == ["coverage"] and ans.cited_claim_ids == []
    assert any("fallback" in c for c in ans.checks)


def test_a_claim_only_reply_quoting_its_claim_passes(full_day):
    conn = full_day.conn
    cid = _summary_claim(conn)
    at = conn.execute("SELECT event_time FROM claims WHERE claim_id=?", (cid,)).fetchone()[0]
    text = f"Lunch with Alex began at {at[11:16]}; 25% of waking hours is covered."
    ans, _ = run(conn, [tool("coverage"), tool("day_summary", **AFTERNOON), final(text, cited=[cid])])
    assert ans.status == "answered" and ans.cited_claim_ids == [cid] and ans.checks == []


def test_a_claim_only_reply_without_a_stats_tool_is_unchanged(full_day):
    conn = full_day.conn
    cid = _summary_claim(conn)
    ans, _ = run(conn, [tool("day_summary", **AFTERNOON), final("You had 90 tacos.", cited=[cid])],
                 question="What happened this afternoon?")
    assert ans.status == "answered" and ans.checks == [] and ans.cited_tools == []


# -- the check -------------------------------------------------------------------------------------

def test_coverage_answer_with_correct_numbers_passes(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final(
        "The memory covers 4 of 16 waking hours, 25%. The longest gap ran from 13:20 to 17:45.", ["coverage"])])
    assert ans.status == "answered" and ans.cited_tools == ["coverage"] and ans.cited_claim_ids == []
    assert ans.checks == []
    assert ans.as_dict()["cited_tools"] == ["coverage"]


def test_invented_number_is_retried_then_replaced_by_the_template(full_day):
    ans, llm = run(full_day.conn, [tool("coverage"), final("You covered 90% of your day", ["coverage"]),
                                   final("You covered 90% of your day", ["coverage"])])
    assert "90" in str(llm.recall_payloads[2]["steps_so_far"][-1]["checker"])      # the retry named the number
    assert ans.answer == render_coverage(stats(full_day.conn, "coverage"))
    assert ans.status == "answered" and ans.cited_tools == ["coverage"] and ans.cited_claim_ids == []
    assert any("fallback" in c for c in ans.checks)
    assert "90" not in numbers_in(ans.answer)


def test_a_retry_with_correct_numbers_is_accepted(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final("You covered 90% of your day", ["coverage"]),
                                 final("You covered 25% of your waking hours.", ["coverage"])])
    assert ans.answer == "You covered 25% of your waking hours." and len(ans.checks) == 1


@pytest.mark.parametrize("text", ["The longest gap was 4 h 25 min, from 13:20 to 17:45.",
                                  "The longest gap was 265 minutes, from 13:20 to 17:45.",
                                  "The longest gap lasted 4 hours 25 minutes."])
def test_equivalent_formats_are_accepted(full_day, text):
    ans, _ = run(full_day.conn, [tool("coverage"), final(text, ["coverage"])])
    assert ans.status == "answered" and ans.answer == text and ans.checks == []


def test_an_invented_number_in_the_note_is_also_caught(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final("25% is covered.", ["coverage"], note="about 77 gaps"),
                                 final("25% is covered.", ["coverage"])])
    assert ans.answer == "25% is covered." and "77" in ans.checks[0]


def test_a_failure_on_the_last_step_also_gets_the_template(full_day):
    from app.recall.investigator import MAX_STEPS
    ans, _ = run(full_day.conn, [tool("coverage")] * (MAX_STEPS - 1) + [final("90% is covered.", ["coverage"])])
    assert ans.status == "answered" and ans.answer == render_coverage(stats(full_day.conn, "coverage"))


def test_usage_answer_cites_the_tool_not_a_claim(full_day):
    conn = full_day.conn
    add_call(conn, "a", words_in=1200)
    add_call(conn, "b", purpose="read_memory", words_in=3000)
    for text in ("The models read 4,200 words in 2 calls.", "The models read 4200 words."):
        ans, _ = run(conn, [tool("usage_stats", day=DAY), final(text, ["usage_stats"])], question=USAGE_Q)
        assert ans.status == "answered" and ans.answer == text
        assert ans.cited_tools == ["usage_stats"] and ans.cited_claim_ids == []


def test_claim_answers_still_need_claims(full_day):
    ans, llm = run(full_day.conn, [tool("coverage"), final("25% is covered."), final("25% is covered.")])
    assert ans.status == "abstained" and ans.cited_tools == []
    assert "cite at least one claim" in ans.checks[0]
    assert "cite at least one claim" in llm.recall_payloads[2]["steps_so_far"][-1]["checker"]


def test_a_tool_cited_but_not_called_is_refused(full_day):
    ans, llm = run(full_day.conn, [final("The models read 4,200 words.", ["usage_stats"]),
                                   final("The models read 4,200 words.", ["usage_stats"])], question=USAGE_Q)
    assert ans.status == "abstained" and ans.cited_tools == []     # no result, so no template either
    assert "usage_stats" in ans.checks[0] and "not called" in ans.checks[0]


def test_a_claim_tool_cannot_be_cited_as_a_stats_tool(full_day):
    ans, _ = run(full_day.conn, [tool("search_claims", query="Alex"), final("You met 1 person.", ["search_claims"]),
                                 final("You met 1 person.", ["search_claims"])])
    assert ans.status == "abstained"


def test_an_error_result_is_not_a_valid_citation(full_day):
    bad = {"time_from": f"{DAY}T14:00:00", "time_to": f"{DAY}T12:00:00"}
    ans, _ = run(full_day.conn, [tool("coverage", **bad), final("0% is covered.", ["coverage"]),
                                 final("0% is covered.", ["coverage"])])
    assert ans.status == "abstained" and ans.cited_tools == [] and "0%" not in ans.answer


def test_a_valid_result_after_an_error_is_used(full_day):
    bad = {"time_from": f"{DAY}T14:00:00", "time_to": f"{DAY}T12:00:00"}
    ans, _ = run(full_day.conn, [tool("coverage", **bad), tool("coverage"), final("25% is covered.", ["coverage"])])
    assert ans.status == "answered" and ans.cited_tools == ["coverage"]


def test_mixed_claims_and_tools_are_both_checked(full_day):
    conn = full_day.conn
    window = {"time_from": f"{DAY}T12:00:00", "time_to": f"{DAY}T14:00:00"}
    cid = stats(conn, "day_summary", **window)["moments"][0]["summary"]["claim_id"]
    text = "You had lunch with Alex; 45 of the window's 120 minutes are covered (38%), from 12:30."
    ans, _ = run(conn, [tool("day_summary", **window), tool("coverage", **window),
                        final(text, ["coverage"], cited=[cid])], question="What happened this afternoon?")
    assert ans.status == "answered" and ans.cited_claim_ids == [cid] and ans.cited_tools == ["coverage"]
    # an invented claim id fails even when the numbers are right: retried, then the template
    ans, _ = run(conn, [tool("coverage", **window), final(text, ["coverage"], cited=["clm-000000000000"]),
                        final(text, ["coverage"], cited=["clm-000000000000"])], question="What happened this afternoon?")
    assert ans.answer == render_coverage(stats(conn, "coverage", **window)) and ans.cited_claim_ids == []
    # and a number neither the claim nor the tool holds fails too
    ans, _ = run(conn, [tool("day_summary", **window), tool("coverage", **window),
                        final("You had lunch with 77 people.", ["coverage"], cited=[cid]),
                        final("You had lunch with 77 people.", ["coverage"], cited=[cid])],
                 question="What happened this afternoon?")
    assert "77" in ans.checks[0] and any("fallback" in c for c in ans.checks)


def test_an_unrouted_question_never_answers_from_a_tool(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final("25% is covered.", ["coverage"]),
                                 final("25% is covered.", ["coverage"])], question="Which restaurant did Alex recommend?")
    assert ans.status == "abstained" and ans.cited_tools == []
    ans, _ = run(full_day.conn, [final("25% is covered.", ["coverage"]), final("25% is covered.", ["coverage"])],
                 question=COVERAGE_Q, as_of=None)                     # no day: never routed
    assert ans.status == "abstained" and ans.cited_tools == []


def test_an_abstained_reply_drops_its_cited_tools(full_day):
    ans, _ = run(full_day.conn, [tool("coverage"), final("No record.", ["coverage"], status="abstained")])
    assert ans.status == "abstained" and ans.cited_tools == []


# -- templates -------------------------------------------------------------------------------------

def test_coverage_template_follows_the_share_basis(full_day):
    day = stats(full_day.conn, "coverage")
    text = render_coverage(day)
    assert "of waking hours" in text and "of the window" not in text
    assert "25%" in text and "13:20" in text and "4 h 25 min" in text
    window = stats(full_day.conn, "coverage", time_from=f"{DAY}T12:00:00", time_to=f"{DAY}T14:00:00")
    text = render_coverage(window)
    assert "of the window" in text and "of waking hours" not in text and "38%" in text and "45" in text
    for s in (day, window):
        assert numbers_in(render_coverage(s)) <= stats_numbers(s)


def test_coverage_template_says_plainly_when_there_is_no_record(full_day):
    empty = stats(full_day.conn, "coverage", time_from=f"{DAY}T03:00:00", time_to=f"{DAY}T04:00:00")
    text = render_coverage(empty)
    assert "no record" in text.lower() and "0%" in text and "longest gap" not in text.lower()
    assert numbers_in(text) <= stats_numbers(empty)


def test_usage_template(full_day):
    conn = full_day.conn
    nothing = stats(conn, "usage_stats")
    assert "no model calls" in render_usage(nothing).lower() and numbers_in(render_usage(nothing)) == set()
    add_call(conn, "a", words_in=1200)
    add_call(conn, "b", purpose="read_memory", images=1, words_in=3000, audio_ms=90000)
    day = stats(conn, "usage_stats", day=DAY)
    text = render_usage(day)
    assert "4,200" in text and "1.5 min" in text and "1 photo" in text and "2 calls" in text
    assert numbers_in(text) <= stats_numbers(day)
    other = stats(conn, "usage_stats", day="2026-10-30")
    text = render_usage(other)
    assert "no model calls were recorded for that day" in text.lower() and "2 calls" in text
    assert numbers_in(text) <= stats_numbers(other)


def test_usage_fallback_when_nothing_was_recorded_is_answered(full_day):
    ans, _ = run(full_day.conn, [tool("usage_stats"), final("The models read 900 words.", ["usage_stats"]),
                                 final("The models read 900 words.", ["usage_stats"])], question=USAGE_Q)
    assert ans.status == "answered" and ans.answer == render_usage(stats(full_day.conn, "usage_stats"))
    assert "no model calls" in ans.answer.lower()


# -- the service -----------------------------------------------------------------------------------

def test_stats_answer_is_not_cached(full_day):
    conn = full_day.conn
    llm = FakeLLM()
    reply = [tool("coverage"), final("25% of waking hours is covered.", ["coverage"])]
    llm.recall_replies[:] = reply * 2
    svc = RecallService(conn, llm)
    first = svc.ask(COVERAGE_Q, as_of=DAY)
    second = svc.ask(COVERAGE_Q, as_of=DAY)
    assert first["cited_tools"] == ["coverage"] and first["cached"] is False and second["cached"] is False
    assert len(llm.recall_payloads) == 4                          # the second ask called the model again
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 0
    rows = conn.execute("SELECT role, text, claim_ids FROM chat_messages").fetchall()
    assert [r["role"] for r in rows] == ["user", "assistant"] * 2 and rows[1]["claim_ids"] == "[]"


def test_a_cached_row_with_cited_tools_is_never_read(full_day):
    conn = full_day.conn
    llm = FakeLLM()
    q = "What happened this afternoon?"                           # routed, but not a memory question
    llm.recall_replies[:] = [tool("coverage"), final("No record.", status="abstained")]
    svc = RecallService(conn, llm)
    svc.ask(q, as_of=DAY)                                         # an abstention is cached as before
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 1
    conn.execute("UPDATE answer_cache SET answer_json = json_set(answer_json, '$.cited_tools', json('[\"coverage\"]'))")
    llm.recall_replies[:] = [tool("coverage"), final("25% is covered.", ["coverage"])]
    out = svc.ask(q, as_of=DAY)
    assert out["cached"] is False and out["answer"] == "25% is covered."


def test_memory_questions_are_never_cached(full_day):
    """Ruling R-G(c): even an abstention or a claim-only answer to a memory question could outlive new usage."""
    conn = full_day.conn
    llm = FakeLLM()
    llm.recall_replies[:] = [final("No record.", status="abstained")] * 2
    svc = RecallService(conn, llm)
    first, second = svc.ask(USAGE_Q, as_of=DAY), svc.ask(USAGE_Q, as_of=DAY)
    assert first["cached"] is False and second["cached"] is False and len(llm.recall_payloads) == 2
    assert conn.execute("SELECT COUNT(*) FROM answer_cache").fetchone()[0] == 0
    # a cached row for the same key is not read either
    import hashlib
    from app.compiler.resolve import norm
    key = hashlib.sha256(f"memory|{DAY}|{norm(USAGE_Q)}".encode()).hexdigest()
    conn.execute("INSERT INTO answer_cache(question_hash, answer_json, claim_ids) VALUES (?,?,?)",
                 (key, '{"graph_version": "x", "answer": "stale"}', "[]"))
    conn.execute("UPDATE answer_cache SET answer_json = json_set(answer_json, '$.graph_version', ?)",
                 (__import__("app.recall.service", fromlist=["graph_version"]).graph_version(conn),))
    llm.recall_replies[:] = [final("No record.", status="abstained")]
    assert svc.ask(USAGE_Q, as_of=DAY)["answer"] != "stale" and len(llm.recall_payloads) == 3


def test_other_questions_keep_their_cache(full_day):
    llm = FakeLLM()
    llm.recall_replies[:] = [final("No record.", status="abstained")]
    svc = RecallService(full_day.conn, llm)
    svc.ask("What happened this afternoon?", as_of=DAY)
    assert svc.ask("What happened this afternoon?", as_of=DAY)["cached"] is True and len(llm.recall_payloads) == 1
