# MemoryAtlas

**A memory that knows what to remember and what to forget.**

MemoryAtlas turns temporary, consented observations (what you see, hear, where you go, your calendar) into an evidence-backed graph of claims. It can:

1. **Reconstruct** answers that no single source contains, such as "Which restaurant did Alex recommend when we met near the office?"
2. **Correct itself** when newer evidence arrives, while keeping the history ("last confirmed sighting at 17:45 in the car; earlier at 09:10 at Blue Door Café").
3. **Forget verifiably.** When someone withdraws consent, every memory that depended only on that consent is deleted from the graph, search indexes, caches, chat log and exports. Memories that other authorised sources also support stay. A forgetting receipt shows seven automated checks.

Built for the Meta AI Developer Hackathon (Indie Developer track) with Meta's Muse models.

> The model proposes claims and plans searches. **Deterministic code decides what is stored, who can see it and what is deleted.** No privacy decision is made in a prompt.

## Where to start

| If you want to... | Read |
|---|---|
| Understand the idea in two minutes | [Problem and Solution](Problem-and-Solution) |
| See how the parts fit | [Architecture](Architecture) |
| Run it | [Getting Started](Getting-Started) |
| Know how forgetting works | [Forgetting and Consent](Forgetting-and-Consent) |
| See which Meta models are used | [Meta Models](Meta-Models) |
| See the numbers | [Evaluation](Evaluation) |
| Use the app | [Web App](Web-App) |
| Call the API | [API Reference](API-Reference) |
| Contribute | [Contributing](Contributing) |

## At a glance

| | |
|---|---|
| Backend | Python, FastAPI, SQLite (FTS5 + local vectors) |
| Frontend | React 18, TypeScript, Vite, Cytoscape |
| Models | Muse Spark 1.3 (text, vision), Muse Voice Transcribe 1.0 (speech), SAM 3.1 (opt-in object tracking) |
| Deployment | Docker Compose: separate `backend` and `web` (nginx) services on one network |
| Tests | 762 backend, 219 frontend, Playwright browser walkthroughs |
| Raw media kept | 0 bytes. Only derived text is stored. |

Repository: <https://github.com/saiteja195/MemoryAtlas>. These pages summarise the project; the detailed, versioned documents live in the repository's [`docs/`](https://github.com/saiteja195/MemoryAtlas/tree/main/docs) folder and are the source of truth.
