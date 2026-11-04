# Testing

## Suites

| Suite | Command | What it covers |
|---|---|---|
| Backend | `cd backend && python -m pytest -q` | 762 tests: consent and gateway rules, the compiler, recall and its post-checks, revocation and probes, corrections, expiry, migrations, uploads, jobs, profiles |
| Frontend | `make check-web` (type-check and `vitest`) | 219 tests of pure helpers: add-memory rules, graph shaping, save jobs, media maths |
| Both | `make test` | Frontend check, then backend |
| Browser | Playwright scripts in `frontend/e2e/` | Walkthrough, assistant and profile-privacy flows with accessibility audits |

## How tests run without a model

Backend tests use scripted stand-ins for the model, or the recorded responses in `fixtures/llm_cache/`. Recordings are keyed by a hash of the request, so changing a prompt, a tool output or a pinned time invalidates them; re-record with a key (`scripts/record_demo.py`, `ask_demo.py`, `revoke_demo.py`, `correct_demo.py`). Replay-portability tests check the recordings still work on another machine.

## What is tested on purpose

- **Forgetting is exact**: property tests build random support graphs, including cycles, revoke random sources and assert that every surviving claim has well-founded support and every supported claim survives.
- **Leak probes** run on the demo day and in the evaluation (7 of 7 in every run).
- **Regressions from review**: legacy databases without consent rows, episodes with stale revoked metadata, a verification crash after a purge, lapsed grants.
- **Privacy by construction**: receipts contain no claim text, model logs contain no content, media bytes stay 0.
- **Uploads**: size limits, bad media, per-file times, people adding up across photos, a "no" dropping the whole memory.

## Browser checks

`frontend/e2e/*.cjs` need Playwright (not a project dependency) and a running backend and web UI; each script's header says how to start them. They check the flows in a real browser, the single announcement region, light and dark themes, and axe accessibility audits.

## Before opening a pull request

```bash
make test
```

and, if the change touches anything a model reads or writes, re-record the affected demo responses and run the evaluation (see [Evaluation](Evaluation)).
