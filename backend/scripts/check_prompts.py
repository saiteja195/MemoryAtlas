"""Ask the twelve non-to-do assistant prompts of the dashboard design through the LIVE model, on the sample day.

    export MODEL_API_KEY=...        (in your own shell; never paste it into chat or commit it)
    python scripts/check_prompts.py

It loads the committed sample day into a scratch profile in a temporary directory (no real data is touched),
asks each prompt with `as_of` set to the sample day, and prints the answer, its status, the steps taken, how
many memories it cites, the tools it cites, the post-check notes and whether the deterministic template
fallback was used. The exit code is non-zero only when the model cannot be reached or no key is set: an
imperfect answer is output to read, not a failure.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402

AS_OF = "2026-10-29"
PROMPTS = [
    "Where did I leave my wallet?",
    "Which restaurant did Alex recommend?",
    "Who did I meet today?",
    "What time was my meeting with Alex?",
    "Summarise my day.",
    "What happened this morning?",
    "What was the most important moment?",
    "Where did I spend the most time?",
    "What did the models read today?",
    "How much of my day is covered?",
    "What happened between 13:20 and 17:45?",
    "What are you unsure about?",
]


def main() -> int:
    if not os.environ.get("MODEL_API_KEY"):
        print("MODEL_API_KEY is not set. In your own shell run: export MODEL_API_KEY=...  then run this again.")
        return 2
    with tempfile.TemporaryDirectory() as scratch:
        settings = Settings(auth=True, llm_mode="live", data_dir=scratch,
                            db_path=os.path.join(scratch, "unused.db"), cache_dir=os.path.join(scratch, "seed"))
        client = TestClient(create_app(settings))
        r = client.post("/auth/signup", json={"name": "Prompt Check", "passcode": "prompt-check-1"})
        r.raise_for_status()
        client.post("/demo/load-sample").raise_for_status()
        counts = {"answered": 0, "partial": 0, "abstained": 0}
        fallbacks = 0
        for q in PROMPTS:
            r = client.post("/recall/ask", json={"question": q, "as_of": AS_OF})
            if r.status_code == 503:
                print(f"\n{q}\n  model unavailable: {r.json().get('detail')}")
                return 3
            r.raise_for_status()
            out = r.json()
            fell_back = any(str(c).startswith("fallback:") for c in out.get("checks", []))
            fallbacks += fell_back
            counts[out["status"]] = counts.get(out["status"], 0) + 1
            print(f"\n{q}\n  {out['status']} in {out['steps']} steps: {out['answer']}"
                  f"\n  cited memories: {len(out['cited_claim_ids'])}  cited tools: {out.get('cited_tools', [])}"
                  f"  template fallback: {'yes' if fell_back else 'no'}")
            for c in out.get("checks", []):
                print(f"  check: {c}")
        print(f"\nSummary: {counts['answered']} answered, {counts['partial']} partial, "
              f"{counts['abstained']} abstained, {fallbacks} used the template fallback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
