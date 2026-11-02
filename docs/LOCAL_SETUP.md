# Local setup

How to run MemoryAtlas on your own machine. **You do not need an API key** to run, test or demo it: by
default the app replays recorded Muse Spark responses that are committed to the repo.

Every command below was run from a fresh clone of this repository before it was written down.

## 1. What you need

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11 or newer | tested with 3.13 |
| Node.js + npm | 18 or newer | tested with Node 22 / npm 10 |
| make | any GNU make | the Makefile is POSIX; on Windows use WSL, or the manual commands in section 9 |
| git | any | |

A Meta Model API key is only needed for **live** mode (section 4) and for re-recording fixtures (section 8).

## 2. Quick start (about 5 minutes)

```bash
git clone https://github.com/saiteja195/MemoryAtlas.git
cd MemoryAtlas
make setup
```

`make setup` creates `backend/.venv`, installs the backend (`pip install -e ".[dev]"`) and runs `npm install`
in `frontend/`. It takes about 20 seconds. `npm` may print "vulnerabilities" warnings for dev tooling; they
do not affect the app.

Check that it works:

```bash
make test
```

You should see all tests pass (type-check and 24 web tests, then 175 backend tests; about 25 seconds). Then start everything:

```bash
make dev
```

| What | URL |
|---|---|
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |
| Web UI | http://localhost:5173 |

To run them separately, use `make api` and `make web` in two terminals. Stop with Ctrl+C.

### Using the Atlas UI

Open http://localhost:5173. The whole demo can be run from the browser, in this order:

1. **Build the day.** Press **Play next** (one event at a time) or **Play the day**. The memory graph appears.
   **Episodes** (the default) shows the day as boxes in time order; **Details** shows the people, places and
   things, and how they relate. The row under the timeline lists every event of the day; dashed ones have not
   happened yet.
2. **Ask a question.** Click an example (in replay mode only the examples are recorded) or type your own in
   live mode. The facts the answer rests on light up in the graph and everything else fades. Press **Why? Show
   the evidence** to open the proof: each fact traced to the photo, conversation or calendar entry it came from,
   with the original quote. Click any fact in the graph to see where it came from, or use **Clear focus**.
3. **Travel in time.** Drag **Scrub through the day**, or press **Watch it build**. Facts appear when they first
   became knowable, and a sighting that was later replaced counts as current until the newer one arrived.
4. **Let new evidence correct a memory.** Press **Upload live photo · 17:45**, then ask "Where is my wallet?".
   The answer moves from the café to the car; the café sighting stays as greyed-out history (⏱, **History**
   checkbox).
5. **Withdraw consent.** Open the **Consent** tab. Press "Alex withdraws…" (a simulated phone appears), or
   "Open on Alex's phone (new tab)" to do it from a second tab. The demo PIN is `4242`. The first tab notices on
   its own, fades out what was forgotten, and shows the **forgetting receipt**: what was removed, what was kept
   and why, and the 7 automated checks. Then ask "What did Alex promise me?" (no record) and "What colour is the
   awning at Luna Taqueria?" (still answered).
6. **Reset** puts everything back to the start.

Reading the graph (also under "How to read the graph" in the page): a dashed line is inferred, a solid one
observed; colour says where a fact came from (photo, conversation, calendar, several sources "×N", inferred);
shape says what kind of thing (circle person, rounded box place, diamond thing). Useful controls: **Facts**
(related / all / off: details such as what was said or a colour), **Tidy up** (re-arrange so nothing overlaps),
**Fit** and zoom.

The page follows your system's light or dark theme and reduced-motion setting. It works with the keyboard (the
tabs take arrow keys, Esc closes dialogs), and every fact in the picture is also in the **All facts as a table**
section under it. The header always shows the model mode and **Raw media kept: 0 B**.

## 3. Try the demo from the terminal (no key, copy and paste)

With `make api` running, in another terminal. The demo replays a staged day: a wallet at a café, a billboard,
a calendar meeting with Alex, a recorded conversation, and a photo of a taco shop sign.

```bash
curl -s localhost:8000/health
```
```bash
curl -s -XPOST "localhost:8000/demo/advance?steps=10"
```
That plays the scripted day (5 events: photos, calendar, a 3-line conversation). Look at the memory graph:
```bash
curl -s localhost:8000/graph | python3 -m json.tool | head -40
```
Ask a question that no single source can answer. The conversation never names the restaurant; the answer comes
from linking it to the photographed sign:
```bash
curl -s -XPOST localhost:8000/recall/ask -H 'content-type: application/json' \
  -d '{"question":"Which restaurant did Alex recommend when we met near the office?"}'
```
Expected: `Alex recommended Luna Taqueria.` with `cited_claim_ids`. To see why, ask for the evidence of a cited
claim: `curl -s localhost:8000/claims/<claim_id>/provenance`.

**Self-correcting memory.** Ask where the wallet is, upload the later photo, and ask again:
```bash
curl -s -XPOST localhost:8000/recall/ask -H 'content-type: application/json' -d '{"question":"Where is my wallet?"}'
curl -s -XPOST localhost:8000/demo/live/F4
curl -s -XPOST localhost:8000/recall/ask -H 'content-type: application/json' -d '{"question":"Where is my wallet?"}'
```
The answer changes from the café (09:10) to the car (17:45). The café sighting stays as history.

**Verifiable forgetting.** Alex withdraws consent. The demo hands out the tokens a real person would hold on
their own device:
```bash
curl -s localhost:8000/demo/grants | python3 -m json.tool
```
Copy Alex's `grant_id` and `demo_token`, then:
```bash
curl -s -XPOST localhost:8000/consent/grants/<grant_id>/revoke \
  -H 'content-type: application/json' -d '{"token":"<demo_token>"}' | python3 -m json.tool
```
The response is the **forgetting receipt**: what was removed, which facts were kept and why (for example "Me
met with Alex" is still supported by the calendar), and the results of 7 automated leak checks. Ask again:
```bash
curl -s -XPOST localhost:8000/recall/ask -H 'content-type: application/json' \
  -d '{"question":"Which restaurant did Alex recommend when we met near the office?"}'
```
Now it answers that there is no record. Questions about the sign (`What colour is the awning at Luna Taqueria?`)
still work. `GET /export` returns everything the app holds; the forgotten words are not in it.

Start over any time:
```bash
curl -s -XPOST localhost:8000/demo/reset
```

### In replay mode only recorded questions can be answered

The default mode answers from recorded model responses. A question that was never recorded fails with
**HTTP 503** and `no recorded response for ...`. That is by design, not a bug. The recorded questions are in
`fixtures/demo_day/acts.yaml` (three phrasings each for the restaurant and wallet questions, three that must
be refused, and the post-forgetting questions). Ask them in the demo's order, or use live mode for free-form
questions.

## 4. Model modes

Set with `MEMORYATLAS_LLM_MODE`. The active mode is returned by `GET /health`.

| Mode | Needs a key | What it does |
|---|---|---|
| `replay` (default) | no | Answers only from recorded responses. Offline, deterministic. |
| `live` | yes | Calls the Meta Model API for everything. Free-form questions work. Results can vary between runs. |
| `record` | yes | Like live, and also saves each response so it can be replayed later. |

To use live mode, copy the example file and fill it in:

```bash
cp .env.example .env
```
```bash
# .env  (this file is git-ignored; never commit it or paste the key into chat)
MEMORYATLAS_LLM_MODE=live
MODEL_API_KEY=your-key-here
```

`make api` reads `.env` automatically (`make web` does not need it). Restart `make api` after editing.

Notes for live mode:

- Create the key in the Meta Model API dashboard; the hackathon credit is claimed through the event form and
  needs a card on file.
- Playing the demo day makes about 15 model calls (17 with the car photo), each question about 2 to 6, and a
  forgetting receipt about 25 (its red-team check asks 5 questions through the real investigator). Pass `?red_team=false` to the
  revoke endpoint for a fast revoke; that check then shows as `skipped`, never as passed.
- If the key is missing, the API still answers HTTP 200 for `/demo/advance` and reports the problem per event:
  look for `"rejected": ["no API key set (MODEL_API_KEY)"]` in the response.

## 5. Configuration reference

All are environment variables (or lines in `.env`). Defaults work for local use.

| Variable | Default | Meaning |
|---|---|---|
| `MEMORYATLAS_LLM_MODE` | `replay` | `replay`, `live` or `record` |
| `MODEL_API_KEY` | empty | Meta Model API key (live and record only) |
| `META_API_BASE_URL` | `https://api.meta.ai` | |
| `META_MODEL` | `muse-spark-1.3` | text and vision model |
| `MEMORYATLAS_DB` | `memoryatlas.db` | SQLite file, relative to where the API starts (`backend/`). `:memory:` for a throwaway database |
| `MEMORYATLAS_CACHE_DIR` | `fixtures/llm_cache` | committed, **read-only** recorded responses |
| `MEMORYATLAS_RUNTIME_CACHE` | `<db file>.llmcache` | where the running app records responses; a forgetting purge cleans this folder |
| `MEMORYATLAS_DEMO_SCRIPT` | `fixtures/demo_day/script.yaml` | the staged day |
| `MEMORYATLAS_SECRET` | `dev-only-secret` | keys the HMAC of consent revocation tokens. Change it for anything beyond a local demo |

## 6. Where data lives

| Path | What | Safe to delete? |
|---|---|---|
| `backend/memoryatlas.db`, `-wal`, `-shm` | the memory graph (text only, never raw photos or audio) | yes; the demo recreates it |
| `backend/memoryatlas.db.llmcache/` | model responses recorded while the app runs | yes |
| `backend/.venv/`, `frontend/node_modules/` | installed dependencies | yes; `make setup` recreates them |
| `fixtures/` | the staged demo day and the committed recordings | **no**, unless you mean to |
| `.env` | your key | keep private |

To reset completely: stop the API, then `rm -f backend/memoryatlas.db* && rm -rf backend/memoryatlas.db.llmcache`.

The app keeps **no raw media**. `GET /privacy/media` reports the bytes retained (always 0) and the bytes of
media files found next to the database.

## 7. API at a glance

Full, interactive version: http://localhost:8000/docs

| Endpoint | Purpose |
|---|---|
| `GET /health` | status and model mode |
| `POST /demo/advance?steps=N`, `POST /demo/live/F4`, `POST /demo/reset`, `GET /demo/status` | drive the staged day |
| `GET /graph?at=<ISO time>&include=history` | the memory graph (nodes, claims as edges, their evidence) |
| `POST /recall/ask` | ask a question; returns the answer, status, cited claims |
| `GET /claims/{id}/provenance` | the evidence tree behind a claim |
| `POST /capture/{kind}` | add your own observation (`frame`, `audio`, `calendar`, `note`); needs a consent grant |
| `POST /consent/grants`, `GET /consent/grants` | create / list consent grants |
| `POST /consent/grants/{id}/revoke` | withdraw consent and forget what only it supported |
| `GET /receipts/{id}` | a stored forgetting receipt |
| `GET /export` | everything the app currently holds |
| `GET /demo/grants` | **demo only**: revocation tokens, so the demo can act as Alex. Never expose this outside a local demo |

The API has no login. It is meant to run on your own machine.

## 8. Running the checks and re-recording

```bash
make test                                      # web type-check and tests, then the backend; offline
make check-web                                 # just the web part (about 2 s)
cd backend && . .venv/bin/activate
python -m pytest -q -k "not properties"        # skip the 1,000-graph property tests (about 15 s)
python -m pytest -q tests/test_replay_revoke.py   # one file
python -m pytest -q tests/test_revocation_properties.py --hypothesis-seed=7   # a different random draw
```

**Browser check (optional).** `frontend/e2e/walkthrough.cjs` drives the whole demo in a real browser and
asserts what it sees (the answers, the evidence, the scrubber, the wallet correction, the second-tab consent, the
receipt, dark mode, no console errors). It needs Playwright, which is not a project dependency because it
downloads browsers. With `make api` and `make web` running:

```bash
cd frontend
npm install --no-save playwright && npx playwright install chromium
npm run e2e                                   # resets the demo first; exit code 0 means every step held
# also run an accessibility audit: AXE_PATH=/path/to/axe.min.js npm run e2e   (from the axe-core package)
```

Re-recording the model responses needs a key and takes several minutes per script. Do it only after changing a
prompt (the prompt is part of the recording's key, so any prompt change makes the replay tests fail with
`no recorded response`):

```bash
cd backend && . .venv/bin/activate
export MODEL_API_KEY=your-key-here
python scripts/ask_demo.py        # the day, Acts 2 and 3, refusals (prints PASS/FAIL per question)
python scripts/revoke_demo.py     # Act 4: Alex withdraws consent, then the 7 leak checks
```

They write into `fixtures/llm_cache/`. Commit the new files only if you meant to. Live runs can vary, so
check the printed PASS/FAIL before replacing the committed recordings, then run `make test`.

Other scripts: `scripts/smoke_meta.py --image photo.jpg --wav clip.wav` checks that the Meta API shapes the
client relies on still work (needs a key, a photo and a mono 16-bit WAV).

## 9. Without `make` (Windows or by hand)

The Makefile only wraps these. Run them from the repo root (on Windows, WSL is the tested route; native
PowerShell is untested):

```bash
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"   # setup (backend)
cd frontend && npm install                                                               # setup (frontend)
cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000          # api
cd frontend && npm run dev                                                               # web
cd backend && . .venv/bin/activate && python -m pytest -q                                # tests
```

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `no recorded response for complete_json (...)` / HTTP 503 | Replay mode and that question was never recorded. Use a question from `fixtures/demo_day/acts.yaml`, or switch to live mode. If you changed a prompt, re-record (section 8). |
| `"rejected": ["no API key set (MODEL_API_KEY)"]` | Live or record mode without a key. Put `MODEL_API_KEY` in `.env` and restart `make api`. |
| `Address already in use` on 8000 or 5173 | Another server holds the port. Stop it, or run on another port: `uvicorn app.main:app --port 8001` (and update the proxy in `frontend/vite.config.ts`). |
| `python3 -m venv` fails | On Debian/Ubuntu: `sudo apt install python3-venv`. |
| Web UI says backend "unreachable" | `make api` is not running, or it is on another port. |
| `tests/test_replay_recall.py` errors on a different OS or CPU (`no recorded response`) | Known: the recordings replay only where search ranking matches the machine they were recorded on. Fix on branch `bug/replay-portability` (needs a re-recording with a key); see `docs/HANDOFF.md` section 8. |
| The UI says "That question isn't in the recording" | Replay mode only answers recorded questions: use an example chip, or switch to live mode. |
| The graph looks crowded | Set **Facts** to "related", or press **Tidy up**; the "All facts as a table" section lists everything. |
| `make test` fails right after you edited a prompt | Expected; see re-recording above. |
| Results differ between live runs | Live extraction is a model call and can vary. Use replay for demos and tests. |
| Want a clean slate | Section 6 ("To reset completely"), or `POST /demo/reset`. |

## 11. Where things are

```
backend/app/
  capture/     privacy gateway: consent check, redaction, text-only storage
  compiler/    turns observations into claims: perceive, episodes, extract, resolve, derive
  recall/      the question-answering tools and investigator
  privacy/     consent grants, the visibility filter, revocation engine, leak probes, export
  llm/         Meta client and the record/replay cache
  api.py       all HTTP endpoints          schema.sql   the database design
backend/scripts/  smoke test and the recording scripts
backend/tests/    unit, property and replay tests
frontend/         the Atlas UI: React + Cytoscape. src/utils/graph.ts holds the logic (unit tested),
                  src/components/ the screens, e2e/ the browser check
fixtures/         the staged demo day and the committed model recordings
docs/             IMPLEMENTATION_PLAN.md (design), HANDOFF.md (state and decisions), HACKATHON_FACTS.md
```

Contributing rules (commit author, branch names, commit format) are in [`CONTRIBUTING.md`](../CONTRIBUTING.md).
