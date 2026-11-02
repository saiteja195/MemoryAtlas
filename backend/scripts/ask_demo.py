"""Play the demo day and ask the Act 2 / Act 3 questions through the real model.

    export MODEL_API_KEY=...   (never paste it into chat or commit it)
    python scripts/ask_demo.py [--cache DIR]

Every model call is cached in fixtures/llm_cache (record mode serves existing entries first),
so tests/test_replay_recall.py can replay the same run offline. Re-run after changing a prompt.
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db  # noqa: E402
from app.capture.adapters import MockDayAdapter  # noqa: E402
from app.config import Settings  # noqa: E402
from app.demo import DemoRunner  # noqa: E402
from app.demo_acts import load_acts, run_group  # noqa: E402
from app.engine import MemoryEngine  # noqa: E402
from app.llm.meta import MetaClient  # noqa: E402
from app.llm.replay import RecordReplayClient  # noqa: E402
from app.recall.service import RecallService  # noqa: E402


def show(title, rows):
    print(f"\n== {title}")
    for r in rows:
        o = r["out"]
        print(f"{'PASS' if not r['problems'] else 'FAIL'} [{o['status']}, {o['steps']} steps] "
              f"{r['question']}\n     -> {o['answer']}"
              + (f"\n     note: {o['uncertainty_note']}" if o["uncertainty_note"] else "")
              + (f"\n     checks: {o['checks']}" if o["checks"] else "")
              + (f"\n     PROBLEMS: {r['problems']}" if r["problems"] else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=Settings().cache_dir)
    args = ap.parse_args()
    s = Settings()
    llm = RecordReplayClient(args.cache, "record",
                             inner=MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model))
    adapter = MockDayAdapter(s.demo_script)
    conn = db.connect(os.path.join(tempfile.mkdtemp(), "ask.db"))
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter,
                      s.revocation_secret)
    recall = RecallService(conn, llm)
    acts = load_acts()
    played = demo.advance(50)
    print("compile problems:", [p for p in played if p["rejected"]] or "none")
    failed = 0
    groups = [("Act 2: connect", "act2_connect", False), ("Act 3: before upload", "act3_before", False),
              ("Must abstain", "must_abstain", True)]
    for title, key, abstain in groups:
        rows = run_group(recall, acts[key], abstain)
        failed += sum(bool(r["problems"]) for r in rows)
        show(title, rows)
    demo.play("F4")
    rows = run_group(recall, acts["act3_after"])
    failed += sum(bool(r["problems"]) for r in rows)
    show("Act 3: after upload (wallet in the car)", rows)
    print(f"\n{failed} question(s) failed")
    return 1 if failed else 0


sys.exit(main())
