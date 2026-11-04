# Roadmap

State as of **4 November 2026**, the submission day (deadline 9 PM ET). The source of truth for scope and schedule is [`docs/IMPLEMENTATION_PLAN.md`](https://github.com/saiteja195/MemoryAtlas/blob/main/docs/IMPLEMENTATION_PLAN.md); open work is tracked in [GitHub issues](https://github.com/saiteja195/MemoryAtlas/issues).

## Built

- Capture gateway with consent, local redaction, text-only storage and blocked hashes
- Memory compiler: perceive, extract, resolve, derive, contradictions, episodes, to-do scan
- Claims graph with justifications and a least-fixpoint support rule
- Recall investigator with deterministic post-checks
- Verifiable forgetting: purge, seven leak checks, receipts with no claim text
- User corrections that supersede, consent expiry, owner withdrawal, deleting one memory
- Upload review flow for photos (up to eight together), voice, video and notes, with opt-in object tracking (SAM 3.1)
- Atlas UI, dashboard, assistant, to-dos, private profiles, demo profiles
- Evaluation against a retrieval baseline (two full runs, hand reviewed)
- Docker deployment as separate services, and a public HTTPS deployment recipe

## Open

| Issue | Item |
|---|---|
| [#9](https://github.com/saiteja195/MemoryAtlas/issues/9) | **Submission**: README, 3-minute video, entry form |
| [#12](https://github.com/saiteja195/MemoryAtlas/issues/12) | **Held-out test day.** A second staged day (new people and places, two similar conversations with only one revoked, role- and place-based links, distractors) with 40 frozen questions, drafted on branch `feature/heldout-day` and not yet run. Rules: no tuning on its results, run three times, publish whatever comes out |
| [#11](https://github.com/saiteja195/MemoryAtlas/issues/11) | Test with real photos and audio instead of placeholder text |
| [#10](https://github.com/saiteja195/MemoryAtlas/issues/10) | The correction half is built. **Live graph updates over a WebSocket (`/events`) are not built**; the page refreshes after changes |
| [#13](https://github.com/saiteja195/MemoryAtlas/issues/13) | Try Meta's native structured output and tool calling (the client currently asks for JSON in the prompt and validates it) |
| [#29](https://github.com/saiteja195/MemoryAtlas/issues/29) | Storage at scale: benchmark the claims graph and decide the next engine. SQLite is the current engine (one small file per profile); whether a graph database or other engine pays off at scale is what this issue measures |
| [#14](https://github.com/saiteja195/MemoryAtlas/issues/14) | Owner to-dos: credits, public repository, data-retention question, an old branch |

## Known limits

See [Privacy and Limits](Privacy-and-Limits) and the "Reading it honestly" notes in [Evaluation](Evaluation).
