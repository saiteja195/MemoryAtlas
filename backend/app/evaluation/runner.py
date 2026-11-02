"""Runs the evaluation: builds the staged day, asks every question of MemoryAtlas and the baseline,
scores the answers, and aggregates over runs.

Ingestion replays the committed recorded model responses (the day is the same text each time); every
question, summary, judge call and the red-team probe goes to the live model, uncached, so latency is real
and the runs vary honestly.
"""
import json
import os
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .. import db
from ..capture.adapters import MockDayAdapter
from ..config import Settings
from ..demo import DemoRunner
from ..demo_acts import load_acts
from ..engine import MemoryEngine
from ..llm.base import LLMClient, LLMUnavailable
from ..llm.replay import RecordReplayClient
from ..privacy.revocation import RevocationEngine
from ..recall.service import RecallService
from .baseline import Baseline
from .questions import ANSWERABLE, CATEGORIES, Question
from .scoring import auto_score, combine, judge

SYSTEMS = ("memoryatlas", "baseline_stale", "baseline_rebuilt")
Progress = Callable[[str], None]


class CountingClient:
    """Counts model calls; adds nothing else (no cache), so each call is a real one."""

    def __init__(self, inner: LLMClient):
        self.inner, self.calls, self.mode = inner, 0, "live"

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return self.inner.complete_json(system, user, schema)

    def describe_image(self, image: bytes, prompt: str) -> dict[str, Any]:
        self.calls += 1
        return self.inner.describe_image(image, prompt)

    def transcribe(self, audio: bytes, keywords: list[str] | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        return self.inner.transcribe(audio, keywords)


def _timed(fn: Callable[[], dict[str, Any]], counter: CountingClient) -> dict[str, Any]:
    before, t0 = counter.calls, time.perf_counter()
    try:
        out = fn()
    except LLMUnavailable as e:
        out = {"status": "error", "answer": f"model error: {str(e)[:160]}"}
    out["latency_s"] = round(time.perf_counter() - t0, 3)
    out["llm_calls"] = counter.calls - before
    return out


def _row(system: str, run: int, q: Question, out: dict[str, Any], judge_llm: LLMClient) -> dict[str, Any]:
    auto = auto_score(q, out)
    jd = judge(judge_llm, q, out)
    final = combine(q, auto, jd)
    return {"system": system, "run": run, "id": q.id, "category": q.category, "phase": q.phase,
            "question": q.question, "status": out.get("status"), "answer": out.get("answer", ""),
            "latency_s": out["latency_s"], "llm_calls": out["llm_calls"], "steps": out.get("steps"),
            "cited": out.get("cited_claim_ids", out.get("cited", [])),
            "retrieved": out.get("retrieved"), "trace": out.get("trace"),
            "note": out.get("uncertainty_note", ""), "checks": out.get("checks"),
            "auto": auto, "judge": jd, "final": final}


def _sources(conn) -> list[dict[str, str]]:
    return [dict(r) for r in conn.execute(
        "SELECT source_id, captured_at, text FROM sources WHERE status='active' AND text IS NOT NULL"
        " ORDER BY captured_at, source_id")]


def run_once(run_no: int, questions: list[Question], live: LLMClient, settings: Settings,
             progress: Progress = print, workdir: str | None = None) -> dict[str, Any]:
    """One full pass: the day, the live photo, Alex's withdrawal. Returns rows and run-level facts."""
    counter = CountingClient(live)
    ingest_llm = RecordReplayClient(tempfile.mkdtemp(prefix="eval-ingest-"), "replay",
                                    seed_dir=settings.cache_dir)
    adapter = MockDayAdapter(settings.demo_script)
    path = os.path.join(workdir or tempfile.mkdtemp(prefix="eval-run-"), f"run{run_no}.db")
    conn = db.connect(path)
    demo = DemoRunner(MemoryEngine(conn, ingest_llm, adapter.owner, adapter.names), adapter,
                      settings.revocation_secret)
    recall = RecallService(conn, counter)
    stale, rebuilt = Baseline(counter, False), Baseline(counter, True)
    bl_counter = counter
    rows: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}

    def ask_phase(phase: str) -> None:
        for q in (x for x in questions if x.phase == phase):
            progress(f"  run {run_no} {phase} {q.id}")
            rows.append(_row("memoryatlas", run_no, q,
                             _timed(lambda: recall.ask(q.question), counter), live))
            if phase != "after_revoke":
                rows.append(_row("baseline", run_no, q,
                                 _timed(lambda: stale.ask(q.question), bl_counter), live))
            else:
                rows.append(_row("baseline_stale", run_no, q,
                                 _timed(lambda: stale.ask(q.question), bl_counter), live))
                rows.append(_row("baseline_rebuilt", run_no, q,
                                 _timed(lambda: rebuilt.ask(q.question), bl_counter), live))

    # Phase 1: the scheduled day.
    demo.advance(50)
    for b in (stale, rebuilt):
        b.sync(_sources(conn))
    ask_phase("day")
    # Phase 2: the live photo of the wallet in the car.
    demo.play("F4")
    for b in (stale, rebuilt):
        b.sync(_sources(conn))
    ask_phase("after_live")
    # Phase 3: Alex withdraws consent.
    alex = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'").fetchone()[0]
    engine = RevocationEngine(conn, settings.revocation_secret, counter, adapter.owner, db_path=path,
                              red_team_questions=[x["question"] for x in load_acts()["red_team"]])
    t0 = time.perf_counter()
    receipt = engine.revoke(alex, demo.tokens["alex:sync-alex"])
    facts["revocation_s"] = round(time.perf_counter() - t0, 3)
    facts["probes_passed"] = receipt["summary"]["probes_passed"]
    facts["probes_total"] = receipt["summary"]["probes_total"]
    facts["probes"] = [{"id": p["id"], "name": p["name"], "status": p["status"]} for p in receipt["probes"]]
    for b in (stale, rebuilt):
        b.sync(_sources(conn))
    ask_phase("after_revoke")

    terms = sorted({t.lower() for q in questions if q.category == "forget" for t in q.leak_terms})
    scan = {}
    for name, b in (("baseline_stale", stale), ("baseline_rebuilt", rebuilt)):
        scan[name] = {"chunks": [t for t in terms if t in b.dump(include_summary=False).lower()],
                      "summary": [t for t in terms if t in b.summary_text().lower()]}
    facts["store_scan"] = scan
    facts["leak_terms"] = terms
    facts["raw_media_bytes"] = conn.execute(
        "SELECT COALESCE(SUM(media_bytes_retained),0) FROM sources").fetchone()[0]
    facts["llm_calls_total"] = counter.calls
    conn.close()
    return {"rows": rows, "facts": facts}


# ---------------------------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------------------------

def _view(rows: list[dict[str, Any]], system: str) -> list[dict[str, Any]]:
    """Rows for one reported system. The baseline was asked once before the deletion; its after-deletion
    variants are separate, so each variant's view is the shared rows plus its own."""
    if system == "memoryatlas":
        return [r for r in rows if r["system"] == "memoryatlas"]
    return [r for r in rows if r["system"] in ("baseline", system)]


def _p95(xs: list[float]) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))] if s else 0.0


def _dev_questions() -> set[str]:
    """Questions the system was developed against (the demo-act questions), lower-cased."""
    return {x["question"].strip().lower() for group in load_acts().values() for x in group}


def _ok(r: dict[str, Any], reviewed: bool) -> bool:
    """Correct under the strict string check. With `reviewed`, a row where the judge disagreed and said
    correct also counts: every such row was read by hand (docs/EVALUATION.md) and the judge was right on
    each; in the other direction (judge no, strings yes) the strings were right, so they stand."""
    if bool(r["final"].get("correct")):
        return True
    return bool(reviewed and r["final"].get("disagree") and r["judge"].get("verdict") is True)


def _good(r: dict[str, Any], reviewed: bool = False) -> bool:
    """The row went the right way: a forget question without a leak, anything else correct."""
    return not r["final"].get("leaked") if r["category"] == "forget" else _ok(r, reviewed)


def metrics_for(rows: list[dict[str, Any]], reviewed: bool = False) -> dict[str, Any]:
    """Counts for one system in one run."""
    dev = _dev_questions()
    seen = [r for r in rows if r["question"].strip().lower() in dev]
    new = [r for r in rows if r["question"].strip().lower() not in dev]
    by = defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)

    def n_correct(cat: str) -> int:
        return sum(_ok(r, reviewed) for r in by[cat])

    answerable = [r for c in ANSWERABLE for r in by[c]]
    rated = [r for r in answerable + by["refuse"] if r["judge"].get("verdict") is not None]
    lat = [r["latency_s"] for r in rows]
    return {
        "overall_good": [sum(_good(r, reviewed) for r in rows), len(rows)],
        "overall_good_new": [sum(_good(r, reviewed) for r in new), len(new)],
        "overall_good_seen": [sum(_good(r, reviewed) for r in seen), len(seen)],
        "answerable_correct": [sum(_ok(r, reviewed) for r in answerable), len(answerable)],
        "judge_correct": [sum(bool(r["judge"]["verdict"]) for r in rated), len(rated)],
        "multi_source": [n_correct("multi_source"), len(by["multi_source"])],
        "timing": [n_correct("timing"), len(by["timing"])],
        "correction": [n_correct("correction"), len(by["correction"])],
        "refuse_ok": [n_correct("refuse"), len(by["refuse"])],
        "unsupported_confident": [len(by["refuse"]) - n_correct("refuse"), len(by["refuse"])],
        "wrong_confident": [sum(r["status"] not in ("abstained", "error") and not _ok(r, reviewed)
                                for r in answerable), len(answerable)],
        "leaked": [sum(bool(r["final"].get("leaked")) for r in by["forget"]), len(by["forget"])],
        "leaked_by_string": [sum(bool(r["final"].get("leak_by_string")) for r in by["forget"]), len(by["forget"])],
        "facts_lost": [len(by["keep"]) - n_correct("keep"), len(by["keep"])],
        "errors": [sum(r["status"] == "error" for r in rows), len(rows)],
        "latency_median_s": round(statistics.median(lat), 2) if lat else 0.0,
        "latency_p95_s": round(_p95(lat), 2),
        "llm_calls_per_question": round(statistics.mean(r["llm_calls"] for r in rows), 2) if rows else 0.0,
        "judge_disagreements": sum(bool(r["final"].get("disagree")) for r in rows),
    }


def aggregate(runs: list[dict[str, Any]], reviewed: bool = False) -> dict[str, Any]:
    """Mean and range of each metric over the runs, per system."""
    out: dict[str, Any] = {"runs": len(runs), "systems": {}}
    for system in SYSTEMS:
        per_run = [metrics_for(_view(r["rows"], system), reviewed) for r in runs]
        agg: dict[str, Any] = {}
        for key in per_run[0]:
            vals = per_run[0][key]
            if isinstance(vals, list):                      # [count, total]
                counts = [m[key][0] for m in per_run]
                agg[key] = {"mean": round(statistics.mean(counts), 2), "min": min(counts), "max": max(counts),
                            "of": per_run[0][key][1]}
            else:
                xs = [m[key] for m in per_run]
                agg[key] = {"mean": round(statistics.mean(xs), 2), "min": min(xs), "max": max(xs)}
        out["systems"][system] = agg
    out["facts"] = [r["facts"] for r in runs]
    return out


def disagreements(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for run in runs for r in run["rows"] if r["final"].get("disagree")]


def write_run(dirpath: Path, run_no: int, result: dict[str, Any]) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    with open(dirpath / f"run{run_no}.json", "w") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)


def load_runs(dirpath: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(dirpath.glob("run*.json"))]


def _cell(m: dict[str, Any], key: str) -> str:
    v = m[key]
    if "of" in v:
        base = f"{v['mean']:g}/{v['of']}"
        return base if v["min"] == v["max"] else f"{base} (range {v['min']}–{v['max']})"
    return f"{v['mean']:g}" if v["min"] == v["max"] else f"{v['mean']:g} (range {v['min']:g}–{v['max']:g})"


def _table(summary: dict[str, Any], rows: list[tuple[str, str]]) -> list[str]:
    s = summary["systems"]
    ma, bs, br = s["memoryatlas"], s["baseline_stale"], s["baseline_rebuilt"]
    lines = ["| Measure | MemoryAtlas | Baseline (stale summary) | Baseline (rebuilt summary) |", "|---|---|---|---|"]
    for label, key in rows:
        lines.append(f"| {label} | {_cell(ma, key)} | {_cell(bs, key)} | {_cell(br, key)} |")
    return lines


STRICT_ROWS = [
    ("All 40 questions handled correctly (correct answer, correct refusal, or no leak)", "overall_good"),
    ("  new questions, not used during development", "overall_good_new"),
    ("  questions that were also demo-act questions during development", "overall_good_seen"),
    ("All answerable questions correct", "answerable_correct"),
    ("Multi-source questions answered correctly", "multi_source"),
    ("Timing and last-seen questions correct", "timing"),
    ("Contradiction / correction questions correct", "correction"),
    ("Questions that should be refused, correctly refused", "refuse_ok"),
    ("Confident answers with no support (should-refuse questions answered)", "unsupported_confident"),
    ("Confident but wrong answers (answerable questions)", "wrong_confident"),
    ("Forgotten facts still recoverable from answers (lower is better)", "leaked"),
    ("  of which found by the string check", "leaked_by_string"),
    ("Facts wrongly lost (kept questions not answered)", "facts_lost"),
]
REVIEWED_ROWS = [r for r in STRICT_ROWS if r[1] not in ("leaked", "leaked_by_string", "unsupported_confident")]
COST_ROWS = [
    ("Model errors", "errors"),
    ("Recall latency, median seconds", "latency_median_s"),
    ("Recall latency, 95th percentile seconds", "latency_p95_s"),
    ("Model calls per question", "llm_calls_per_question"),
]


def markdown(summary: dict[str, Any], meta: dict[str, Any], reviewed: dict[str, Any] | None = None) -> str:
    lines = [f"# Evaluation results — {meta['label']}", "",
             f"Model `{meta['model']}` · {summary['runs']} run(s) · {meta['questions']} questions · commit `{meta['commit']}` · {meta['date']}",
             "", "Values are the mean over runs; the range is the lowest–highest run.", "",
             "## Strict scoring (fixed before the run)", "",
             "An answer counts only if it contains the expected strings, including clock times such as `17:45`.", ""]
    lines += _table(summary, STRICT_ROWS + COST_ROWS)
    if reviewed:
        lines += ["", "## After reading every row where the judge and the strings disagreed", "",
                  "All disagreeing rows were read by hand (see `README.md` in this folder). Where the judge said "
                  "correct and the strings said wrong, the answer was right but omitted a clock time; those now count. "
                  "Leaks need no adjustment: they are already counted if the strings or the judge found one, and "
                  "each judge-only leak was confirmed.", ""]
        lines += _table(reviewed, REVIEWED_ROWS)
    facts = summary["facts"]
    probes = [f"{f['probes_passed']}/{f['probes_total']}" for f in facts]
    lines += ["", f"- Raw media retained after processing: **{max(f['raw_media_bytes'] for f in facts)} bytes** "
              "(MemoryAtlas); the baseline indexes the same text observations, so it keeps none either.",
              f"- MemoryAtlas leak probes passed per run: {', '.join(probes)}.",
              "- Revocation took " + ", ".join(f"{f['revocation_s']}s" for f in facts) +
              " (includes the red-team probe's live model calls).",
              "- Baseline stores after Alex's withdrawal (leak terms still present):"]
    for i, f in enumerate(facts, 1):
        for name in ("baseline_stale", "baseline_rebuilt"):
            sc = f["store_scan"][name]
            lines.append(f"  - run {i}, {name}: in chunks {sc['chunks'] or 'none'}; in the summary note {sc['summary'] or 'none'}")
    return "\n".join(lines) + "\n"
