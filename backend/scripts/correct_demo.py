"""Correct a remembered fact against the real model, and see the next answer change.

    export MODEL_API_KEY=...   (never paste it into chat or commit it)
    python scripts/correct_demo.py [--cache DIR]

Model calls are cached in fixtures/llm_cache (record mode serves existing entries first), so
tests/test_replay_correct.py replays the same run offline.
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db  # noqa: E402
from app.capture.adapters import MockDayAdapter  # noqa: E402
from app.config import Settings  # noqa: E402
from app.corrections import correct_claim  # noqa: E402
from app.demo import DemoRunner  # noqa: E402
from app.engine import MemoryEngine  # noqa: E402
from app.llm.meta import MetaClient  # noqa: E402
from app.llm.replay import RecordReplayClient  # noqa: E402
from app.recall.service import RecallService  # noqa: E402

QUESTION = "What did Alex promise me?"
CORRECTION = "Actually, Alex said he would send the proposal by Monday, not Friday."
AT = "2026-10-29T18:30:00"      # fixed: the time is part of the request, so a replay needs it pinned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=Settings().cache_dir)
    args = ap.parse_args()
    s = Settings()
    llm = RecordReplayClient(args.cache, "record",
                             inner=MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model))
    adapter = MockDayAdapter(s.demo_script)
    conn = db.connect(os.path.join(tempfile.mkdtemp(), "correct.db"))
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter, s.revocation_secret)
    recall = RecallService(conn, llm)
    demo.advance(50)
    demo.play("F4")
    before = recall.ask(QUESTION)
    print("BEFORE:", before["answer"])
    target = before["cited_claim_ids"][0]
    out = correct_claim(demo.engine, target, CORRECTION, at=AT)
    print("CORRECTION:", out)
    after = recall.ask(QUESTION)
    print("AFTER :", after["answer"])
    ok = "monday" in after["answer"].lower() and "friday" not in after["answer"].lower()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


sys.exit(main())
