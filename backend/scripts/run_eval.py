"""Run the MemoryAtlas-vs-baseline evaluation against the live Meta model.

    export MODEL_API_KEY=...   (never paste it into chat or commit it)
    python scripts/run_eval.py --label full --runs 3
    python scripts/run_eval.py --label smoke --runs 1 --only M01,T01,R01,F01,K01   # a quick check
    python scripts/run_eval.py --label full --aggregate-only                      # rebuild the tables

Ingestion replays the committed recordings; all questions, summaries, judge calls and the red-team probe
are live and uncached. Output goes to eval/results/<label>/ (one run<N>.json per run, summary.json,
RESULTS.md, REVIEW.md listing every row where the model judge disagreed with the string checks).
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import ROOT, Settings  # noqa: E402
from app.evaluation.questions import load_questions  # noqa: E402
from app.evaluation.runner import (aggregate, disagreements, load_runs, markdown, run_once,  # noqa: E402
                                   write_run)
from app.llm.meta import MetaClient  # noqa: E402


def commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def review_md(rows) -> str:
    out = ["# Rows to review by hand", "",
           "The model judge disagreed with the string check on these. Each needs a human decision; the "
           "headline numbers use the string check (or, for leaks, string OR judge).", ""]
    for r in rows:
        out += [f"## {r['id']} · {r['system']} · run {r['run']} · {r['category']}", f"**Q:** {r['question']}",
                f"**Answer ({r['status']}):** {r['answer']}", f"**String check:** {json.dumps(r['auto'])}",
                f"**Judge:** {json.dumps(r['judge'])}", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--start-run", type=int, default=1, help="resume: first run number to execute")
    ap.add_argument("--only", default="", help="comma-separated question ids (a smoke check)")
    ap.add_argument("--aggregate-only", action="store_true")
    ap.add_argument("--reviewed", action="store_true",
                    help="add the table that counts hand-reviewed disagreements (only after reading REVIEW.md)")
    args = ap.parse_args()
    s = Settings()
    out_dir = ROOT / "eval" / "results" / args.label
    questions = load_questions()
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q.id in wanted]
    if not args.aggregate_only:
        if not s.llm_api_key:
            print("MODEL_API_KEY is not set")
            return 2
        live = MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model)
        for n in range(args.start_run, args.start_run + args.runs):
            print(f"== run {n}", flush=True)
            write_run(out_dir, n, run_once(n, questions, live, s, progress=lambda m: print(m, flush=True)))
    runs = load_runs(out_dir)
    summary, reviewed = aggregate(runs), aggregate(runs, reviewed=True)
    meta = {"label": args.label, "model": s.llm_model, "questions": len(questions), "commit": commit(),
            "date": date.today().isoformat()}
    (out_dir / "summary.json").write_text(json.dumps({**summary, "reviewed": reviewed, "meta": meta}, indent=1))
    (out_dir / "RESULTS.md").write_text(markdown(summary, meta, reviewed if args.reviewed else None))
    (out_dir / "REVIEW.md").write_text(review_md(disagreements(runs)))
    print((out_dir / "RESULTS.md").read_text())
    return 0


sys.exit(main())
