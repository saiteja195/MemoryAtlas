"""Build the published demo profiles.

    export MODEL_API_KEY=...                       (never paste it into chat or commit it)
    export DEMO_STAGED_NAME=... DEMO_STAGED_PASSCODE=...
    export DEMO_REAL_NAME=...   DEMO_REAL_PASSCODE=...

    python scripts/seed_profiles.py staged --data-dir /tmp/seed-staged
    python scripts/seed_profiles.py real   --data-dir /tmp/seed-real --media ~/demo-photos
    python scripts/seed_profiles.py register staged --data-dir /data   # on the server: create the row only

`staged` and `real` run the content through the live pipeline, print every stored claim for you to review,
and write a text-only snapshot to fixtures/profiles/<kind>.db. Raw media and GPS are never kept.
See fixtures/profiles/README.md for the checklist before you commit a snapshot.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.profiles import seed  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", help="staged, real, or `register`")
    ap.add_argument("register_kind", nargs="?", help="with `register`: staged or real")
    ap.add_argument("--data-dir", required=True, help="an empty scratch directory (or, for register, the app's)")
    ap.add_argument("--media", help="real only: a directory of photos, wav and txt files plus manifest.yaml")
    ap.add_argument("--out", help="where to write the snapshot (default fixtures/profiles/<kind>.db)")
    a = ap.parse_args()
    if a.kind == "register":
        seed.register(a.register_kind or "", data_dir=a.data_dir, env=os.environ)
    else:
        seed.seed(a.kind, data_dir=a.data_dir, media_dir=a.media, out=a.out)


if __name__ == "__main__":
    main()
