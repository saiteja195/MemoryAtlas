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

## Run it locally

No API key needed (it replays recorded model responses):

```bash
make setup
make test
make dev
```

Full guide, including the copy-and-paste demo and live mode: [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md).

## How memory is stored

The memory map is a **claims graph kept in one SQLite file**: entities (people, places, objects, episodes), claims
(facts with time, confidence and evidence type), and the justifications that say why each claim exists. Search is
SQLite FTS5 plus vector similarity. There is no separate graph or vector database, on purpose: forgetting is
deterministic code over a single store that the leak checks can scan completely, including the file itself.

It is sized for a person's days and weeks, not yet a lifetime. Planned next, measured before it is built
(see [#29](https://github.com/saiteja195/MemoryAtlas/issues/29)): incremental support tracking, a faster vector index,
and PostgreSQL if it ever becomes multi-user.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch naming, commit conventions and the authorship rule.
