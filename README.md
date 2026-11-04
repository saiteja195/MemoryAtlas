# MemoryAtlas

**A memory that knows what to remember and what to forget.** Built for the Meta AI Developer Hackathon (Indie Developer track).

MemoryAtlas turns consented observations (photos, voice, video, notes, calendar) into an evidence-backed graph of your day. It can:

1. **Reconstruct** answers no single source contains ("Which restaurant did Alex recommend when we met near the office?")
2. **Correct itself** when newer evidence arrives, and keep the history ("Did I leave my wallet at the café?")
3. **Forget verifiably.** When someone withdraws consent, every memory that depended *only* on it is removed from the graph, indexes, caches, chat and exports. Memories with other support stay, and a receipt shows seven automated leak checks. You can also delete a single memory.

Only text is kept; raw photos, audio and video are never stored. Code, not a prompt, decides what is stored, shown and deleted.

## For reviewers

| | |
|---|---|
| **Live app** | <https://memoryatlas.209-145-49-232.sslip.io> (HTTPS, live Muse models) |
| **Demo logins** | `Bob-Demo` / `123456`: the scripted sample day. Public on purpose and holds only demo content; **Settings > Reset demo data** restores it. |
| | `Tej` / `123456`: the owner's own memories, added live (photos, voice, video and notes, kept as text only). **It has no reset, so please look around without deleting anything or withdrawing consent.** |
| **Wiki** | <https://github.com/saiteja195/MemoryAtlas/wiki>: architecture, forgetting, API and the demo script |
| **Evaluation** | 39.7 of 40 questions handled correctly, against 24 to 30 for a plain retrieval baseline ([method and limits](docs/EVALUATION.md), [results](eval/results/after-temporal-fix-2026-11-03/RESULTS.md)) |

**Two-minute tour.** Sign in, open the **Atlas** and ask *"Which restaurant did Alex recommend when we met near the office?"* (the answer comes with receipts). Open the **Consent** tab, press **Alex withdraws…** and enter the demo PIN shown. The receipt lists what was removed and what was kept, with 7 of 7 checks. Ask again: the recommendation is gone. You can also add your own photos, voice, video or notes with **Add memory**; the scripted sample day lives under **Demo tools**.

## Meta models used

- **Muse Spark 1.3:** reads photos and video frames, extracts facts, answers questions.
- **Muse Voice 1.0:** transcribes voice recordings.
- **SAM 3.1:** optional on a video; finds the objects you name and records when each was visible.

## Run it locally

No API key needed (it replays recorded model responses):

```bash
make setup && make test && make dev
```

Or with Docker: `docker compose up --build`, then open <http://localhost:8080>. Live mode needs your own Meta model key, and a phone camera needs HTTPS; both are in the guides below.

## Docs

[Local setup and live mode](docs/LOCAL_SETUP.md) · [Docker](docs/DOCKER.md) · [Deploying with HTTPS](docs/DEPLOY.md) · [How the demo profiles are built](fixtures/profiles/README.md) · [Implementation plan](docs/IMPLEMENTATION_PLAN.md) · [Contributing](CONTRIBUTING.md)
