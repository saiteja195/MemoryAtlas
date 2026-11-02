"""The evaluation harness: question set, baseline, scoring, aggregation and one offline end-to-end pass."""
import collections

import pytest

from app.config import Settings
from app.evaluation.baseline import Baseline, chunk_source
from app.evaluation.questions import ANSWERABLE, CATEGORIES, QUESTIONS_PATH, load_questions
from app.evaluation.runner import aggregate, markdown, run_once
from app.evaluation.scoring import auto_refused, auto_score, combine, judge


def q(qid):
    return next(x for x in load_questions() if x.id == qid)


def out(status="answered", answer="x", **kw):
    return {"status": status, "answer": answer, **kw}


# -- the question set ---------------------------------------------------------------------------

def test_the_question_set_has_forty_questions_in_the_planned_categories():
    qs = load_questions()
    counts = collections.Counter(x.category for x in qs)
    assert len(qs) == 40
    assert counts == {"multi_source": 10, "timing": 8, "correction": 6, "refuse": 6, "forget": 6, "keep": 4}
    assert len({x.id for x in qs}) == 40
    assert set(counts) == set(CATEGORIES)


def test_every_question_can_be_scored():
    for x in load_questions():
        if x.category in ANSWERABLE:
            assert x.expect or x.any_of
        if x.category == "forget":
            assert x.leak_terms and x.leak_claim and x.phase == "after_revoke"
        assert x.rubric


def test_a_malformed_question_is_rejected(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text("questions:\n  - {id: X, category: forget, phase: day, question: 'q', rubric: r}\n")
    with pytest.raises(ValueError):
        load_questions(p)


# -- scoring ------------------------------------------------------------------------------------

def test_an_answerable_question_needs_every_expected_string_and_one_alternative():
    t3 = q("T03")
    good = out(answer="Last confirmed sighting at 09:10 at Blue Door Café.")
    assert auto_score(t3, good)["correct"]
    assert not auto_score(t3, out(answer="Last confirmed sighting at 09:10."))["correct"]      # no place
    assert not auto_score(t3, out(answer="Yes, at 09:10 at Blue Door."))["correct"]            # forbid_start + no phrase


def test_an_abstention_is_not_a_correct_answer_to_an_answerable_question():
    assert not auto_score(q("M01"), out("abstained", "Luna Taqueria? I have no record."))["correct"]


def test_refusal_is_recognised_by_status_or_by_wording():
    assert auto_refused(out("abstained", "Sorry."))
    assert auto_refused(out("answered", "I have no record of that."))
    assert not auto_refused(out("answered", "Orbit Fitness."))
    assert auto_score(q("R02"), out("answered", "You went to Orbit Fitness."))["correct"] is False
    assert auto_score(q("R02"), out("abstained", "I don't have a record."))["correct"] is True


def test_a_forgotten_fact_is_a_leak_when_a_leak_term_appears():
    f1 = q("F01")
    assert auto_score(f1, out(answer="He promised a proposal by Friday."))["leaked"]
    assert not auto_score(f1, out("abstained", "I don't have a record that answers that."))["leaked"]


def test_the_judge_can_flag_a_leak_the_strings_missed():
    f2 = q("F02")
    answered = out(answer="Alex pointed you to Luna Taqueria.")
    auto = auto_score(f2, answered)
    assert auto["leaked"] is False

    class Judge:
        def complete_json(self, system, user, schema):
            assert "Alex recommended" in user
            return {"verdict": True, "reason": "names the restaurant"}

    verdict = combine(f2, auto, judge(Judge(), f2, answered))
    assert verdict["leaked"] and verdict["leak_by_judge"] and not verdict["leak_by_string"] and verdict["disagree"]


def test_a_judge_that_is_unavailable_never_changes_the_verdict():
    from app.llm.base import LLMUnavailable

    class Down:
        def complete_json(self, *a):
            raise LLMUnavailable("down")

    m01 = q("M01")
    a = out(answer="Luna Taqueria")
    v = combine(m01, auto_score(m01, a), judge(Down(), m01, a))
    assert v["correct"] and not v["disagree"]


# -- the baseline -------------------------------------------------------------------------------

class Notes:
    """Stand-in model: summarises by quoting the records it is given."""
    mode = "live"

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user, schema):
        self.prompts.append(user)
        if system.startswith("You keep an end-of-day"):
            return {"summary": "The day: " + " ".join(user.split("\n"))}
        return {"status": "answered", "answer": user, "cited": []}


def src(sid, at, text):
    return {"source_id": sid, "captured_at": at, "text": text}


DAY = [src("s1", "2026-10-29T09:10:00", "A wallet on a table at Blue Door Café."),
       src("s2", "2026-10-29T12:35:00", "Alex: try the taco place, best al pastor."),
       src("s3", "2026-10-29T13:20:00", "Luna Taqueria storefront with a green awning.")]


def test_text_is_chunked_with_its_time():
    chunks = chunk_source("s", "2026-10-29T09:10:00", "One. " * 400)
    assert len(chunks) > 1 and all(c.text.startswith("[2026-10-29 09:10]") for c in chunks)
    assert all(len(c.text) < 700 for c in chunks)


def test_retrieval_returns_at_most_eight_chunks_and_finds_the_relevant_one():
    many = [src(f"s{i}", f"2026-10-29T10:{i:02d}:00", f"Filler sentence number {i} about nothing.") for i in range(20)]
    b = Baseline(Notes(), rebuild_summary=False)
    b.sync(many + DAY)
    hits = b.search("What colour is the awning at Luna Taqueria?")
    assert len(hits) <= 8 and any(c.source_id == "s3" for c in hits)


def test_deleting_a_source_removes_its_chunks_but_a_stale_summary_keeps_the_text():
    b = Baseline(Notes(), rebuild_summary=False)
    b.sync(DAY)
    assert "al pastor" in b.summary_text()
    result = b.sync([s for s in DAY if s["source_id"] != "s2"])
    assert result["deleted"] == 1
    assert "al pastor" not in b.dump(include_summary=False)
    assert "al pastor" in b.summary_text()            # what a plain index leaves behind


def test_a_rebuilt_summary_no_longer_holds_the_deleted_text():
    b = Baseline(Notes(), rebuild_summary=True)
    b.sync(DAY)
    b.sync([s for s in DAY if s["source_id"] != "s2"])
    assert "al pastor" not in b.dump()


def test_the_baseline_answer_is_built_from_retrieved_excerpts_only():
    llm = Notes()
    b = Baseline(llm, rebuild_summary=False)
    b.sync(DAY)
    res = b.ask("Where was my wallet?")
    assert "Blue Door" in res["answer"] and res["retrieved"]


# -- aggregation --------------------------------------------------------------------------------

def fake_row(system, cat, correct=None, leaked=None, status="answered", latency=1.0):
    final = {"correct": correct} if leaked is None else {"leaked": leaked, "leak_by_string": leaked}
    return {"system": system, "category": cat, "question": "q", "status": status, "latency_s": latency, "llm_calls": 3,
            "final": final, "judge": {"verdict": None}}


def test_aggregation_reports_mean_and_range_over_runs():
    def run(correct):
        rows = [fake_row("memoryatlas", "multi_source", correct=i < correct) for i in range(10)]
        rows += [fake_row("baseline", "multi_source", correct=True) for _ in range(10)]
        return {"rows": rows, "facts": {"raw_media_bytes": 0, "probes_passed": 7, "probes_total": 7,
                                        "revocation_s": 1.0, "store_scan": {}}}
    agg = aggregate([run(8), run(10)])
    cell = agg["systems"]["memoryatlas"]["multi_source"]
    assert cell == {"mean": 9.0, "min": 8, "max": 10, "of": 10}
    assert agg["systems"]["baseline_stale"]["multi_source"]["mean"] == 10


# -- one offline end-to-end pass ----------------------------------------------------------------

class OfflineLive:
    """Scripted stand-in for the live model: the investigator and the baseline both decline."""
    mode = "live"

    def complete_json(self, system, user, schema):
        if system.startswith("You answer questions about the user's own day"):
            return {"action": "final", "status": "abstained", "answer": "", "cited_claim_ids": []}
        if system.startswith("You answer questions about the user's day from memory"):
            return {"status": "abstained", "answer": "I have no record of that.", "cited": []}
        if system.startswith("You keep an end-of-day"):
            return {"summary": "A café, a billboard, a meeting and a taco place."}
        if system.startswith("You grade one answer"):
            return {"verdict": False, "reason": "scripted"}
        raise AssertionError(system[:60])


def test_a_full_pass_runs_through_the_day_the_live_photo_and_the_withdrawal(tmp_path):
    questions = [x for x in load_questions() if x.id in {"M01", "T04", "R01", "F01", "K03"}]
    result = run_once(1, questions, OfflineLive(), Settings(), progress=lambda m: None, workdir=str(tmp_path))
    systems = collections.Counter(r["system"] for r in result["rows"])
    assert systems == {"memoryatlas": 5, "baseline": 3, "baseline_stale": 2, "baseline_rebuilt": 2}
    assert result["facts"]["probes_passed"] == result["facts"]["probes_total"] == 7
    assert result["facts"]["raw_media_bytes"] == 0
    stale = result["facts"]["store_scan"]["baseline_stale"]
    assert stale["chunks"] == []                       # the conversation's chunks are gone either way
    summary = aggregate([result])
    assert summary["systems"]["memoryatlas"]["refuse_ok"]["of"] == 1
    assert "MemoryAtlas" in markdown(summary, {"label": "t", "model": "m", "questions": 5, "commit": "c", "date": "d"})
