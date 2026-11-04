# MemoryAtlas

**A memory that knows what to remember and what to forget.**

MemoryAtlas turns temporary, consented observations (what you see, hear, where you go, your calendar) into an evidence-backed temporal graph of your experiences. It can:

1. **Reconstruct** answers that no single source contains ("Which restaurant did Alex recommend when we met near the office?")
2. **Correct itself** when newer evidence arrives, while keeping the history ("Did I leave my wallet at the café?")
3. **Forget verifiably:** when someone withdraws consent, every memory that depended *only* on that consent is removed from the graph, search indexes, caches, chat and exports. Memories backed by other authorized sources stay. A forgetting receipt proves it.

Built for the Meta AI Developer Hackathon (Indie Developer track) with Meta's Muse models.

**Status:** the memory engine works end to end: capture, claims graph, cross-source recall, self-correction and
verifiable forgetting (with a receipt of 7 automated leak checks), all in a browser UI (the "Atlas"). Evaluation
and submission are still to do; see the open issues and [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

The dashboard shows what the models processed (counts only), how much of the day the memories cover and a tracked to-do
list; one **Ask your memory** assistant, shared by every page, answers fact, summary, to-do and "about my memory"
questions with its receipts. See [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md#the-dashboard-and-the-assistant).

## Run it locally

No API key needed (it replays recorded model responses):

```bash
make setup
make test
make dev
```

With Docker instead (separate `web` and `backend` services on one network, no local Python or Node needed):
`docker compose up --build`, then open <http://localhost:8080>. See [`docs/DOCKER.md`](docs/DOCKER.md).

Full guide, including the copy-and-paste demo and live mode: [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).
Everyone signs in with a name and passcode and gets a private Atlas; to look around without signing up, use a demo profile (below). Adding your own photos, voice, video and notes: [Adding your own memories](docs/LOCAL_SETUP.md#adding-your-own-memories). Running it on a VM with HTTPS so a phone can use the camera: [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Try it live

**<https://memoryatlas.209-145-49-232.sslip.io>** (HTTPS, live Muse model).

## Demo profiles for reviewers

Sign in at the live site above (or your own running copy) with one of these. They hold only demo content, and
**Settings > Reset demo data** puts them back as they were. Or create your own profile: every profile is private.

| Profile | Name | Passcode | What it holds |
|---|---|---|---|
| Staged day | `Bob-Demo` | `123456` | the scripted "A Day You Forgot" |
| Real photos | _not created yet_ | _not created yet_ | a real day, from the owner's own photos |

The passcode is public on purpose, so anyone can look around. Please don't put anything private in a demo profile.

How they are built and what is checked before they are published: [`fixtures/profiles/README.md`](fixtures/profiles/README.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch naming, commit conventions and the authorship rule.
