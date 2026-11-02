"""Play the scripted demo day through the real model and cache every response.

    export MODEL_API_KEY=...   (never paste it into chat or commit it)
    python scripts/record_demo.py [--cache DIR] [--no-live-frame]

Writes responses to fixtures/llm_cache (by request hash) so `MEMORYATLAS_LLM_MODE=replay`
reproduces the same graph offline. Re-run after changing any prompt, because the prompt is
part of the cache key. Prints a summary of the graph and any rejected observations.
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
from app.engine import MemoryEngine  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.llm.meta import MetaClient  # noqa: E402
from app.llm.replay import RecordReplayClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=Settings().cache_dir)
    ap.add_argument("--no-live-frame", action="store_true")
    args = ap.parse_args()
    s = Settings()
    if not s.llm_api_key and not any(os.scandir(args.cache) if os.path.isdir(args.cache) else []):
        print("MODEL_API_KEY is not set and the cache is empty")
        return 2
    llm = RecordReplayClient(args.cache, "record",
                             inner=MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model))
    adapter = MockDayAdapter(s.demo_script)
    conn = db.connect(os.path.join(tempfile.mkdtemp(), "record.db"))
    demo = DemoRunner(MemoryEngine(conn, llm, adapter.owner, adapter.names), adapter,
                      s.revocation_secret)
    played = demo.advance(50)
    if not args.no_live_frame:
        demo.play("F4")
    bad = [p for p in played if p["rejected"]]
    g = build_graph(conn, include_history=True)
    print(f"events played: {len(played)}  rejected: {bad or 'none'}")
    print(f"nodes: {len(g['nodes'])}  edges: {len(g['edges'])}")
    names = {n["id"]: n["name"] for n in g["nodes"]}
    for e in g["edges"]:
        if e["predicate"] == "part_of_episode":
            continue
        tgt = names.get(e["target"]) or e["value"]
        print(f"  [{e['status']:8}] {names[e['source']]} --{e['predicate']}--> {tgt}"
              f"  ({e['confidence']}, {len(e['support'])} support)")
    return 1 if bad else 0


sys.exit(main())
