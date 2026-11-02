"""Act 4 against the real model: play the day, ask two questions, have Alex withdraw consent,
read the receipt, then ask what must be forgotten and what must survive.

    export MODEL_API_KEY=...   (never paste it into chat or commit it)
    python scripts/revoke_demo.py [--cache DIR]

Model calls are cached in fixtures/llm_cache (record mode serves existing entries first), so
tests/test_replay_revoke.py replays the same run offline. The committed cache is read-only seed
data for the app, so this script does not give the revocation engine a runtime cache to purge.
"""
import argparse
import json
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
from app.privacy.revocation import RevocationEngine  # noqa: E402
from app.recall.service import RecallService  # noqa: E402

BEFORE = ["Which restaurant did Alex recommend when we met near the office?",
          "What did the billboard advertise?"]


def show(title, rows):
    print(f"\n== {title}")
    for r in rows:
        o = r["out"]
        print(f"{'PASS' if not r['problems'] else 'FAIL'} [{o['status']}, {o['steps']} steps] "
              f"{r['question']}\n     -> {o['answer']}"
              + (f"\n     PROBLEMS: {r['problems']}" if r["problems"] else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=Settings().cache_dir)
    args = ap.parse_args()
    s = Settings()
    llm = RecordReplayClient(args.cache, "record",
                             inner=MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model))
    adapter = MockDayAdapter(s.demo_script)
    path = os.path.join(tempfile.mkdtemp(), "revoke.db")
    conn = db.connect(path)
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter,
                      s.revocation_secret)
    recall, acts = RecallService(conn, llm), load_acts()
    played = demo.advance(50)
    demo.play("F4")
    print("compile problems:", [p for p in played if p["rejected"]] or "none")
    for q in BEFORE:
        print("BEFORE:", q, "->", recall.ask(q)["answer"])
    alex = conn.execute("SELECT grant_id FROM consent_grants WHERE grantor='alex'").fetchone()[0]
    engine = RevocationEngine(conn, s.revocation_secret, llm, adapter.owner, db_path=path,
                              red_team_questions=[q["question"] for q in acts["red_team"]])
    receipt = engine.revoke(alex, demo.tokens["alex:sync-alex"])
    print("\n== Receipt")
    print(json.dumps({k: receipt[k] for k in ("removed", "kept", "summary")}, indent=1))
    for r in receipt["retained"]:
        print(f"  kept: {r['text']}  | lost: {r['lost_support']} | still: {r['still_supported_by']}")
    for p in receipt["probes"]:
        print(f"  {p['status'].upper():7} probe {p['id']}: {p['name']}  {json.dumps(p['detail'])[:150]}")
    forget = run_group(recall, acts["act4_must_forget"], forgotten=True)
    keep = run_group(recall, acts["act4_must_keep"])
    show("After Alex withdraws consent: must be forgotten", forget)
    show("After Alex withdraws consent: must survive", keep)
    bad = sum(bool(r["problems"]) for r in forget + keep)
    print(f"\nprobes: {receipt['summary']}\n{bad} question(s) failed")
    return 1 if bad or not receipt["summary"]["all_passed"] else 0


sys.exit(main())
