"""Check each Meta Model API shape that is not yet verified. Run locally with a key:

    export MODEL_API_KEY=...   (never paste it into chat or commit it)
    python scripts/smoke_meta.py [--image photo.jpg] [--wav clip.wav]

Prints PASS/FAIL per capability with a short snippet. The key is never printed.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import Settings  # noqa: E402
from app.llm.base import LLMUnavailable  # noqa: E402
from app.llm.meta import MetaClient  # noqa: E402


def check(name, fn):
    try:
        print(f"PASS {name}: {str(fn())[:200]}")
    except (LLMUnavailable, OSError) as e:
        print(f"FAIL {name}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--wav")
    args = ap.parse_args()
    s = Settings()
    c = MetaClient(s.llm_base_url, s.llm_api_key, s.llm_model)
    schema = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
    check("json output", lambda: c.complete_json("You extract facts.", "I met Alex in Phoenix.", schema))
    if args.image:
        check("image input", lambda: c.describe_image(
            open(args.image, "rb").read(),
            'Return JSON {"caption": str, "ocr_text": [str], "objects": [str]}.'))
    if args.wav:
        check("transcribe (diarization)", lambda: c.transcribe(open(args.wav, "rb").read()))


main()
