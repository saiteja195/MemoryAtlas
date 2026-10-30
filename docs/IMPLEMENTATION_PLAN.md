# MemoryAtlas — Implementation Plan

**Meta AI Developer Hackathon, Indie Developer track · "Build for Your World"**
**Submission deadline: Wed Nov 4, 2026, 9:00 PM ET.** Internal target: submitted by **6:00 PM ET** (3-hour buffer).
**Plan date: Fri Oct 30, 2026.** That leaves 5.5 working days. The original schedule assumed Oct 28, so this one is re-baselined.

> **One line:** MemoryAtlas turns temporary, consented observations into a memory graph where every memory records its evidence. It can piece together what happened, correct itself when new evidence arrives, and *prove* that it forgot something once consent is withdrawn.

This repo builds the "RecallOS" concept under the name **MemoryAtlas**. The atlas is the memory map judges see; the engine underneath is what wins.

---

## 0. Day-0 verification checklist (do this first, ~1 hour)

These facts came from the pitch research and **could not be checked from the planning environment**, because the event and Meta docs sites were unreachable. Confirm each one before writing integration code:

| # | Verify | Where | Why it matters |
|---|---|---|---|
| 1 | Exact submission requirements: video length, repo visibility, demo link, required form fields | Cerebral Valley event page / Devpost-style form | The Day 5 schedule depends on it |
| 2 | Whether submissions **must** use a specific Meta model/API | Rules page | Decides whether the Meta model is the default path or optional |
| 3 | Model IDs and capabilities: Muse Spark 1.3 (image input? tool calling? JSON/structured output?), Muse Voice Transcribe | dev.meta.ai model docs | Compiler and investigator design |
| 4 | Whether the API is OpenAI-compatible (base URL + SDK) or needs its own client | Model API docs | Shapes `llm/meta.py` |
| 5 | Rate limits and credits | Hackathon resources | Decides whether eval runs live or need the cache |
| 6 | Data-retention / "Contributor" settings for API inputs | Model API settings | Needed for the honest privacy claims in §9 |
| 7 | Wearables Device Access Toolkit: Mock Device Kit availability, platforms (Android/iOS) | developers.meta.com | Whether the glasses adapter is P1 or P2 |
| 8 | Team-size and pre-existing-code rules | Rules page | Repo was created fresh for the event. Keep it that way |

Write the answers into `docs/HACKATHON_FACTS.md`. Every later decision cites that file, not memory.

---

## 1. What we are proving (and what we are not)

Three behaviors a regular memory chatbot does not show. Each has a pass/fail demo moment and a benchmark category:

| Breakthrough | Demo moment | Proven by |
|---|---|---|
| **A. Cross-source reconstruction** | "Which restaurant did Alex recommend when we met near the office?" → *Luna Taqueria*. No single source contains that answer. | Eval category `cross_source` |
| **B. Self-correcting episodic memory** | The wallet's "last seen" changes from café → car when a later frame arrives. The café sighting stays as history. | `temporal`, `contradiction` |
| **C. Consent-aware, verifiable forgetting** | Alex withdraws consent → every fact that *only* the conversation supported disappears from the graph, search, caches, chat and exports. Facts with other authorized evidence survive. A forgetting receipt proves it. | `revocation_forget`, `revocation_retain`, leak probes |

**Not building:** continuous recording, facial recognition, person re-identification, a native mobile app, cloud infrastructure, or a swarm of agents. Two LLM components plus deterministic services is the whole system.

---

## 2. Architecture

```
 Capture adapters                      ┌───────────────────────────────┐
 ─ MockDayAdapter (scripted day) ─┐    │  Privacy & Capture Gateway    │
 ─ UploadAdapter (web/phone)     ─┼──▶ │  consent check · local PII    │
 ─ WearablesDATAdapter (P2)      ─┘    │  redaction · ephemeral buffer │
                                       └──────────────┬────────────────┘
                                                      │ text-only Observations
                                                      │ (raw media dropped here)
                                       ┌──────────────▼────────────────┐
                                       │  AI #1  Memory Compiler       │  Muse Spark
                                       │  extract claims · resolve     │  (+ Voice Transcribe
                                       │  entities · bind episodes ·   │   upstream)
                                       │  derive inferences            │
                                       └──────────────┬────────────────┘
                                                      ▼
            ┌──────────────────────────────────────────────────────────────┐
            │ Evidence & Consent-Aware Temporal Graph  (SQLite + FTS5)     │
            │ sources · consent_grants · entities · claims · justifications│
            │ claim_index (FTS) · claim_vectors · answer_cache · receipts  │
            └───────▲───────────────────────┬──────────────────────▲───────┘
                    │ every read            │                      │ purge
       ┌────────────┴───────────┐   ┌───────▼──────────────┐  ┌────┴─────────────────┐
       │ Deterministic Privacy  │◀──│ AI #2 Recall         │  │ Revocation Engine    │
       │ Filter (access checks) │   │ Investigator (tools) │  │ support recompute ·  │
       └────────────────────────┘   └───────┬──────────────┘  │ purge · leak probes  │
                                            │                 └──────────────────────┘
                                    ┌───────▼────────────────────────────────────┐
                                    │ React + Cytoscape "Atlas": explore · ask · │
                                    │ verify · correct · forget  (live via WS)   │
                                    └────────────────────────────────────────────┘
```

**Stack:** Python 3.11, FastAPI, Pydantic v2, SQLite (WAL, FTS5), `numpy` cosine search for vectors (corpus is small, so no vector DB). React + Vite + TypeScript, Cytoscape.js (`fcose` layout), WebSocket for live graph deltas. `pytest` + `hypothesis` for property tests.

**Design rule:** the LLM never decides what is *allowed*. It proposes claims and plans queries. Deterministic code decides storage, visibility and deletion.

---

## 3. Data model (the core decision)

The graph stores **claims with justifications**, not bare entity edges. Revocation works like a justification-based truth-maintenance system: a claim stays alive only while at least one valid support path back to an authorized source exists.

```sql
-- Who consented to what. Revoking a grant revokes every source under it.
CREATE TABLE consent_grants (
  grant_id      TEXT PRIMARY KEY,
  grantor       TEXT NOT NULL,          -- entity_id of the consenting person ("me", "alex")
  scope         TEXT NOT NULL,          -- 'capture_session' | 'source'
  scope_ref     TEXT NOT NULL,          -- session_id or source_id
  purposes      TEXT NOT NULL,          -- JSON: ["personal_recall"]
  token_hash    TEXT NOT NULL,          -- HMAC of the revocation token (simulated auth)
  granted_at    TEXT NOT NULL,
  revoked_at    TEXT
);

-- One row per observation that passed the gateway. Text only, never raw media.
CREATE TABLE sources (
  source_id     TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,          -- transcript_segment | frame_observation | location_fix
                                        -- | calendar_event | user_confirmation
  session_id    TEXT,
  grant_id      TEXT REFERENCES consent_grants,
  captured_at   TEXT NOT NULL,          -- event time, not ingest time
  ingested_at   TEXT NOT NULL,
  lat REAL, lon REAL,
  text          TEXT,                   -- transcript text / frame caption+OCR / place name; NULL after revoke
  content_hash  TEXT NOT NULL,          -- sha256 of normalized text; kept for re-ingest blocking
  media_bytes_retained INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'active'   -- active | revoked
);

CREATE TABLE entities (
  entity_id     TEXT PRIMARY KEY,
  type          TEXT NOT NULL,          -- person | place | object | org | episode | item
  name          TEXT NOT NULL,
  attrs         TEXT                    -- JSON (e.g. {"awning":"green"})
);

CREATE TABLE claims (
  claim_id      TEXT PRIMARY KEY,
  subject_id    TEXT NOT NULL REFERENCES entities,
  predicate     TEXT NOT NULL,          -- controlled vocabulary, see below
  object_id     TEXT REFERENCES entities,
  object_value  TEXT,                   -- literal when no entity
  event_time    TEXT,                   -- when it happened
  valid_from    TEXT, valid_to TEXT,    -- for state claims (located_at)
  evidence_type TEXT NOT NULL,          -- direct_observation | user_confirmation | inference
  confidence    REAL NOT NULL,
  episode_id    TEXT REFERENCES entities,
  text          TEXT NOT NULL,          -- human-readable rendering, indexed in FTS
  status        TEXT NOT NULL DEFAULT 'active',  -- active | superseded | disputed | revoked
  superseded_by TEXT REFERENCES claims,
  created_at    TEXT NOT NULL
);

-- OR over justifications, AND over premises inside one justification.
CREATE TABLE justifications (
  justification_id TEXT PRIMARY KEY,
  claim_id      TEXT NOT NULL REFERENCES claims,
  kind          TEXT NOT NULL,          -- 'source' | 'derivation'
  source_id     TEXT REFERENCES sources,           -- when kind='source'
  rule          TEXT                    -- e.g. 'spatial_referent_resolution', 'episode_summary'
);
CREATE TABLE justification_premises (
  justification_id TEXT REFERENCES justifications,
  premise_claim_id TEXT REFERENCES claims,
  PRIMARY KEY (justification_id, premise_claim_id)
);

CREATE VIRTUAL TABLE claim_index USING fts5(claim_id UNINDEXED, text);
CREATE TABLE claim_vectors (claim_id TEXT PRIMARY KEY, vec BLOB);
CREATE TABLE answer_cache  (question_hash TEXT PRIMARY KEY, answer_json TEXT, claim_ids TEXT);
CREATE TABLE chat_messages (msg_id TEXT PRIMARY KEY, role TEXT, text TEXT, claim_ids TEXT, redacted INTEGER DEFAULT 0);
CREATE TABLE forgetting_receipts (receipt_id TEXT PRIMARY KEY, grant_id TEXT, created_at TEXT, report_json TEXT);
CREATE TABLE blocked_hashes (content_hash TEXT PRIMARY KEY, reason TEXT);
```

**Controlled predicate vocabulary.** Keep it small so queries stay deterministic:
`observed_at, located_at, met_with, attended, said, recommended, committed_to, has_attribute, near, across_from, part_of_episode, same_as, summary_of`.

Three consequences that make the system defensible:

1. **Summaries are claims.** An episode summary is a `summary_of` claim whose justification lists its premise claims. When the premises die, the summary dies too. This is where most "memory" products leak.
2. **Entity merges are claims.** `same_as(alex_from_calendar, alex_from_transcript)` has its own justification. If the merge was supported only by the revoked transcript, it is undone. (P1)
3. **Multi-support is explicit.** "I met Alex at 12:30" is supported by *both* the calendar event and the transcript, so it survives revoking the transcript. The demo shows this on purpose.

---

## 4. Components

### 4.1 Privacy & Capture Gateway (`backend/app/capture/`)
- `CaptureAdapter` interface: `stream() -> Iterator[RawCapture]`.
  - `MockDayAdapter` replays `fixtures/demo_day/script.yaml` with real (staged, consented) frames and audio. **This is the primary demo path.**
  - `UploadAdapter` handles drag-and-drop or phone upload in the UI, for live, unscripted captures in front of judges.
  - `WearablesDATAdapter`, the Meta glasses via the companion app. **P2.** Only build it if Day-0 check #7 is green and you are ahead of schedule.
- Consent check: audio is dropped unless an active grant covers the session for **every** participant. Frames carry the user's own grant.
- Local filtering before anything leaves the machine: regex redaction of card numbers, phone numbers and emails in transcripts. Frames are downscaled, and only the derived caption and OCR text are kept.
- **Ephemeral buffer:** raw bytes live in memory (or a `tempfile` deleted in `finally`). Only text plus `content_hash` reach `sources`. `media_bytes_retained` is always 0. The eval measures this (§7).
- Before insert, check `blocked_hashes`. Revoked content cannot be re-ingested by replaying the day.

### 4.2 AI #1 — Memory Compiler (`backend/app/compiler/`)
Pipeline per observation. Deterministic steps are marked ⚙, LLM steps ✦:

1. ✦ **Perceive** (frames only): Muse Spark image call → `{caption, ocr_text[], objects[{label, attrs}], scene}`. Audio goes to Muse Voice Transcribe → diarized segments.
2. ⚙ **Episode binding:** cluster sources by time window (±20 min) plus geofence (≤150 m) plus overlapping calendar events. Produces `episode` entities. Cheap, deterministic, and explainable.
3. ✦ **Extract claims:** structured-output call with the controlled vocabulary. The JSON schema is enforced by Pydantic, with one repair retry, then the observation is rejected and logged. Each claim gets `evidence_type` and a model confidence.
4. ⚙✦ **Entity resolution:** exact or alias match first. For ambiguous cases (same type, fuzzy name, same episode), the LLM adjudicates between the top-3 candidates and the decision becomes a `same_as` claim.
5. ✦⚙ **Derive:** a small set of named inference rules. The LLM proposes bindings and the code validates them:
   - `spatial_referent_resolution`: "the taco place across the street" + meeting location + a frame of a taco shop with matching attributes within 100 m across the street → `recommended(alex, luna_taqueria)`. Premises: the transcript claim, the location claim, the sign claim.
   - `last_seen`: the latest `observed_at` per object by **event time**, not ingest order, so late uploads reorder correctly.
   - `episode_summary`: a one-paragraph summary whose premises are the claims it uses.
6. ⚙ **Contradiction pass:** two `located_at` claims for the same object that overlap in time and name different places → both `disputed`. Answers must surface the conflict.
7. ⚙ Write claims, justifications, the FTS row and the vector, then push a graph delta over WebSocket.

**Confidence (heuristic, stated honestly):** `direct_observation = model_conf × 0.95`, `user_confirmation = 0.99`, `inference = min(premises) × 0.9`. Plot a reliability table on the eval set and report it as-is.

### 4.3 AI #2 — Recall Investigator (`backend/app/recall/`)
A tool-calling loop on Muse Spark, capped at 6 steps. Every tool goes through the Privacy Filter (`status='active'` plus a purpose check). **The model never sees revoked or superseded text unless it asks for history explicitly.**

| Tool | Returns |
|---|---|
| `search_claims(query, k, time_from?, time_to?, predicate?)` | Hybrid FTS + vector hits |
| `find_entity(name, type?)` | Entities plus aliases |
| `timeline(entity_id, from?, to?)` | Time-ordered claims |
| `last_seen(object_id)` | Latest sighting plus prior history |
| `episodes(time_from?, time_to?, near?)` | Episodes with participants and place |
| `neighbors(entity_id, predicate?)` | Adjacent claims |
| `provenance(claim_id)` | Justification tree down to sources |

Final output schema: `{status: answered|partial|abstained, answer, cited_claim_ids[], uncertainty_note}`.
**Post-checks (deterministic):**
- *Citation integrity:* every cited claim id must have been returned by a tool in this run and still be active. Otherwise retry once, then abstain. This blocks invented evidence.
- *No present-tense location:* answers about object location must be phrased as "last confirmed sighting at T". Enforced by the prompt and checked by a regex.
- *Stateless per question:* earlier chat turns are **not** fed back to the model, so forgotten facts cannot leak through conversation history.

### 4.4 Revocation Engine (`backend/app/privacy/`): the differentiator

```python
def revoke(grant_id, token):
    verify_hmac(token, grant.token_hash)                    # simulated authenticated action
    revoked_sources = sources_under(grant_id)
    D = downstream_closure(revoked_sources)                 # every claim reachable via justifications
    supported = {c for c in active_claims() if c not in D}  # outside D: unaffected
    # Least fixpoint, built bottom-up from live sources. This stops cyclic
    # derivations (A supports B, B supports A) from keeping each other alive.
    changed = True
    while changed:
        changed = False
        for c in D - supported:
            if any(valid(j, supported, revoked_sources) for j in justifications(c)):
                supported.add(c); changed = True
    dead = D - supported
    with transaction():
        mark sources revoked; null their text; add content_hash to blocked_hashes
        for c in dead: status='revoked', text='[forgotten]', delete FTS row, vector, provenance text
        drop justifications that reference revoked sources or dead premises
        invalidate answer_cache rows whose claim_ids ∩ dead ≠ ∅
        redact chat_messages whose claim_ids ∩ dead ≠ ∅
        regenerate exports
    report = run_leak_probes(probe_terms_from(revoked_sources))   # runs before the plaintext is discarded
    store forgetting_receipt(grant_id, removed=len(dead), retained=…, report)  # counts and hashes only
    broadcast graph delta (dead nodes fade out, surviving multi-support nodes pulse)
```

**Leak probes, all automated and all in the receipt:**
1. Graph: no active claim has a justification set made only of revoked or dead support.
2. FTS: distinctive n-grams from the revoked text ("al pastor", "proposal by Friday") → 0 hits.
3. Vectors: nearest neighbors of the revoked text embeddings contain no dead claim ids.
4. Answer cache and chat: no rows reference dead ids.
5. Export: `grep` the regenerated JSON export for probe terms → 0.
6. Investigator red-team: 5 adversarial questions ("What did Alex say about food?", "Summarize my afternoon") → none mention a protected fact.
7. Disk: the app data directory holds 0 media files and 0 bytes of raw media.

**Property tests (`hypothesis`):** generate random support DAGs and cyclic graphs, revoke random sources, and assert (a) every surviving claim has a well-founded support path, (b) every claim with such a path survives, (c) revocation is idempotent.

**Honesty line for the pitch:** MemoryAtlas proves what *it* retains. Whatever went to a hosted model provider is covered by that provider's terms (Day-0 check #6). The local redaction step limits what gets sent.

### 4.5 The Atlas UI (`frontend/`)
- **Graph view:** nodes are entities, edges are claims. Edge style shows evidence type (solid = direct, dashed = inferred, double = user-confirmed). Color shows the source kind. Superseded claims are greyed with a clock icon. Revoked claims animate out.
- **Ask panel:** answer, status chip, cited claims (click to highlight a path in the graph), and a "Why?" provenance drawer down to sources.
- **Timeline scrubber:** replay the day and watch the graph build.
- **Consent panel:** list of grants. "Revoke" opens a simulated consent page (QR code / second browser tab as Alex with a PIN) to show it is *Alex's* action, not the user's.
- **Forgetting receipt modal:** removed / retained counts, which retained facts survived and *why* (the alternate source), plus the probe results as green checks.
- **Correct:** "That's wrong" on a claim creates a `user_confirmation` source that supersedes it.
- `frontend/src/lib/` is ignored by the root `.gitignore` (Python template ignores `lib/`). Put shared code in `frontend/src/utils/` or add a `!frontend/src/lib/` exception.

### 4.6 LLM client (`backend/app/llm/`)
- `LLMClient` protocol: `complete_json(schema, messages)`, `run_tools(tools, messages)`, `describe_image(bytes)`, `transcribe(bytes)`, `embed(texts)`.
- `MetaClient` is the real implementation (Day-0 checks #3–4). `RecordReplayClient` wraps any client and caches responses by request hash in `fixtures/llm_cache/`.
- Modes: `live` (default, used for judges' unscripted questions), `record`, `replay` (offline fallback). **The UI shows the active mode.** Never pass replay off as live.
- Embeddings: use the Meta endpoint if one exists. Otherwise a small local sentence-embedding model. Record which one in `HACKATHON_FACTS.md`.

### 4.7 API surface
```
POST /capture/{kind}                 frame | audio | location | calendar | note
POST /consent/grants                 → {grant_id, revocation_token}
POST /consent/grants/{id}/revoke     body: {token}        → forgetting receipt
POST /recall/ask                     {question}           → answer schema (§4.3)
GET  /graph?at=ISO&include=history   nodes/edges with status
GET  /claims/{id}/provenance         justification tree
POST /claims/{id}/correct            {correction}
GET  /receipts/{id}
POST /demo/reset | /demo/advance     deterministic demo control
WS   /events                         graph deltas
```

---

## 5. The scripted day (author this on Day 0, because everything depends on it)

Stage it for real with a friend playing "Alex" who **signs a consent note for the recordings**. Use fictional business names on printed signs if real storefronts are a problem. Location fixes can be synthetic.

| Time | Source | Content | Purpose |
|---|---|---|---|
| 09:10 | frame F1 + GPS | Wallet on a table at **Blue Door Café** | First wallet sighting |
| 09:40 | frame F2 + GPS | Billboard "Orbit Fitness: first month free" | Unrelated memory that must survive revocation |
| 12:30–13:15 | calendar C1 | "Sync with Alex" @ Office, 400 Market St | Second, independent support for "met Alex" |
| 12:35–13:10 | audio A1 (Alex consents) | "You've *got* to try the taco place right across the street from your office, the one with the green awning. Best al pastor." · "I'll send you the proposal by Friday." | Never names the restaurant |
| 13:20 | frame F3 + GPS (across the street) | Storefront sign **Luna Taqueria**, green awning | Names the place, but doesn't say who recommended it |
| 17:45 | frame F4 (uploaded live in Act 3) | Wallet in the car cup holder | Late evidence that corrects last-seen |

Also author a **held-out day** (different places, an object, a person, around 15 questions) *after* the system works, and never tune prompts on it. Run it live during judging to show nothing is hardcoded.

---

## 6. Demo: "A Day You Forgot" (about 3 minutes)

| Act | Action | What the judges see |
|---|---|---|
| 0 · Hook (15 s) | "Your day happened across what you saw, heard and where you went. No single record holds it." | Empty atlas |
| 1 · Remember (30 s) | Scrub the timeline through the day | Graph builds itself, color-coded by source. Counter: **raw media retained: 0 bytes** |
| 2 · Connect (30 s) | Ask "Which restaurant did Alex recommend when we met near the office?" | *Luna Taqueria*. "Why?" lights up a three-source path: transcript → meeting location → sign |
| 3 · Correct (30 s) | Ask "Did I leave my wallet at the café?" → "Last confirmed sighting 09:10 at Blue Door Café." Upload F4 and ask again | Answer flips to car @ 17:45. The café edge greys out but stays as history |
| 4 · Forget (55 s) | Alex scans the QR code and revokes. Ask "What did Alex promise me?" and "Which restaurant did Alex recommend?" | Conversation claims fade out. Answers become abstentions. **"I met Alex at 12:30" survives (calendar)**, Luna Taqueria survives (the sign), the billboard and wallet are untouched. The receipt shows 7/7 probes green |
| 5 · Proof (20 s) | Benchmark table vs the baseline | Numbers, not adjectives |

Closing line: *"We didn't delete a recording. Alex withdrew consent, and every memory that depended only on that consent is gone, provably."*

Add a "Demo reset" button and rehearse the full run at least 5 times. Record a backup video of a clean run on Day 4.

---

## 7. Evaluation (`eval/`)

**Baseline (fair by construction):** the *same* per-source texts (transcripts, frame captions/OCR, place names, calendar text), chunked, hybrid BM25 + vector top-8, and the *same* Muse Spark model answering. Plus an end-of-day "daily summary" note, the way typical memory assistants work. Deletion in the baseline = remove the source's chunks, which is what typical systems do. This isolates the value of the claim/justification architecture.

**Question set (`eval/questions.yaml`), 40 on the demo day plus about 15 held-out:**

| Category | n | Scoring |
|---|---|---|
| `cross_source` | 10 | Canonical answer + aliases |
| `temporal` (ordering, last-seen) | 8 | Exact answer and correct tense |
| `contradiction` / correction | 6 | Surfaces the conflict or the corrected answer |
| `unanswerable` | 6 | Correct abstention |
| `revocation_forget` (after revoke) | 6 | Must abstain. Any protected fact = leak |
| `revocation_retain` (after revoke) | 4 | Must still answer |

**Metrics table (fill in with real numbers, 3 runs, mean ± range):**

| Metric | Baseline | MemoryAtlas |
|---|---|---|
| Cross-source accuracy | | |
| Temporal accuracy | | |
| Contradiction handling | | |
| Unsupported confident answers (lower is better) | | |
| Revoked facts still recoverable (lower is better) | | |
| Facts wrongly lost on revocation (lower is better) | | |
| Raw media bytes retained by the app | | |
| p50 / p95 answer latency | | |

Leak detection: string match against a protected-fact list, plus an LLM judge as a second check, reviewed by hand. Commit the raw outputs to `eval/results/`. Report failures honestly. A known-limitations section makes the submission more credible, not less.

---

## 8. Schedule (Fri Oct 30 → Wed Nov 4)

Each row is one short-lived branch merged into `main` (see `CONTRIBUTING.md`). **The exit criterion is a gate:** don't start the next day's P0 until it passes.

| Day | Branches | P0 deliverables | Exit criterion (must be demonstrable) |
|---|---|---|---|
| **D0 Fri 10/30** (evening) | `chore/project-scaffold`, `docs/hackathon-facts`, `feat/demo-day-fixtures` | §0 checklist. FastAPI + Vite skeletons. `schema.sql`. `LLMClient` + `MetaClient` hello-world (text, image, transcribe). Script and **record** the demo day | `make dev` runs both apps. One real Muse Spark image call and one transcription succeed. Fixtures committed |
| **D1 Sat 10/31** | `feat/capture-gateway`, `feat/compiler-claims`, `feat/graph-view-basic` | Gateway with consent gate + ephemeral buffer. Compiler steps 1–4, 6–7. Episode binding. Bare Cytoscape view over `/graph` | Replaying the demo day produces a graph with episodes, Alex, the wallet, and Luna Taqueria. 0 media bytes on disk |
| **D2 Sun 11/1** | `feat/compiler-derivations`, `feat/recall-investigator`, `feat/temporal-correction` | Derivation rules (spatial referent, last-seen, summary). Investigator tools + post-checks. Supersession and disputes | Acts 2 and 3 work live, with citations, on 3 phrasings each |
| **D3 Mon 11/2** | `feat/privacy-revocation`, `feat/leak-probes`, `test/revocation-properties` | Consent grants + HMAC revoke. Fixpoint recompute. Purge across FTS/vectors/cache/chat/export. Receipt. Property tests | Act 4 works. All 7 probes green. Property tests pass on 1,000 random graphs |
| **D4 Tue 11/3** | `feat/atlas-ui-polish`, `eval/baseline-and-benchmark`, `feat/consent-qr-flow` (P1) | Evidence styling, provenance drawer, receipt modal, timeline scrubber. Baseline + eval runner + results. Held-out day | Full demo dry-run ×3 without touching code. Metrics table filled. **Backup video recorded** |
| **D5 Wed 11/4** | `docs/submission`, `fix/*` only | **Feature freeze 12:00 ET.** README, architecture diagram, results, limitations. Final video. Submission form | **Submitted by 18:00 ET.** Tag `v1.0-submission` |

Rough daily budget: 10–12 focused hours. If a day slips by more than 3 hours, apply the cut list below. Don't borrow from D4.

### Priority tiers / cut list
- **P0 (no submission without these):** scripted day, gateway, compiler, claim/justification store, investigator with citations, last-seen correction, revocation with fixpoint plus probes 1–5, basic graph view, eval on the demo day, video.
- **P1:** QR consent flow as Alex, held-out day, `same_as` merge revocation, chat redaction, timeline scrubber, live upload in Act 3.
- **P2:** Wearables DAT adapter, SAM 3.1 object tracking across frames, voice questions, person-scoped revocation ("forget everything about Alex").
- **Cut first:** P2 → held-out day size → UI animation polish. **Never cut** the revocation probes or the baseline comparison. They are the proof.

---

## 9. Mapping to judging (creativity · technical ambition · it works)

| Judges look for | Where MemoryAtlas shows it |
|---|---|
| Real problem, "Build for Your World" | Forgotten commitments, lost objects, fragmented days. Frees mental space without surveillance |
| Creativity | Consent as a first-class part of the data model. Forgetting as a *verifiable* feature, with a receipt |
| Technical ambition | Truth-maintenance-style support graph, well-founded revocation over cycles, cross-source spatial/temporal inference, citation-integrity checks |
| Works | Live unscripted questions, held-out day, reproducible benchmark committed in the repo |
| Use of Meta tech | Muse Spark (perception, extraction, investigation), Muse Voice Transcribe, optional SAM 3.1 and Wearables DAT |

**Claims to avoid:** "perfect privacy", "never forgets anything", "the provider never sees your data". **Claims to make:** "the app retains zero raw media", "revoked facts are unrecoverable from every store we control, verified by automated probes".

---

## 10. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Meta API access, quota or capability gaps (e.g. no image input) | Med | Day-0 verification. `RecordReplayClient`. Recorded fixtures for eval. If image input is missing, use SAM/OCR locally, with Muse Spark on the text |
| LLM extraction drifts or is inconsistent | High | Controlled vocabulary, Pydantic schema + one repair, fixture regression test asserting the key claims exist |
| Spatial inference is brittle | Med | Rule-validated bindings. Unit tests with the exact demo geometry. Graceful "partial" answer showing candidates |
| Graph too cluttered to read on video | Med | Episode-collapsed default view, focus mode on the cited path |
| Demo flakiness on stage | Med | `/demo/reset`, pre-warmed model, backup video, replay mode clearly labeled |
| Scope creep (glasses, SAM) | High | P2 only after the D3 exit criterion passes |
| Rule violations (authorship, pre-existing code) | Low | Fresh repo, commits by `saiteja195` only, no co-author trailers (see `CONTRIBUTING.md`) |

---

## 11. Submission checklist (D5)

- [ ] Public repo, `main` green, tag `v1.0-submission`
- [ ] README: one-paragraph pitch, 60-second quickstart (`make dev`, `make demo`, `make eval`), architecture diagram, Meta tech used, results table, limitations, privacy statement
- [ ] Video at the required length (Day-0 check #1), following §6, with captions
- [ ] `eval/results/` with raw outputs and the command to reproduce
- [ ] Consent notes for everyone recorded in the fixtures (don't commit personal details)
- [ ] `.env.example`, no secrets in git history (`git log -p | grep -i key` sanity check)
- [ ] Every commit authored by `saiteja195` (`git log --format='%an %ae' | sort -u`) and no `Co-authored-by` trailers (`git log --format=%B | grep -i co-authored` returns nothing)

---

## 12. Pitch (submission text)

**MemoryAtlas: a memory that knows what to remember and what to forget.**
Our days are spread across what we see, hear and where we go. MemoryAtlas turns temporary, consented observations into an evidence-backed graph of experiences. It can reconstruct what happened from fragments no single record contains, and correct itself when new evidence arrives. Every memory records why it exists and who allowed it. When someone withdraws consent, MemoryAtlas removes every memory that depended only on that consent, keeps what other authorized sources still support, and issues a receipt proving the removal. We're not just teaching AI to remember. We're building a memory that can explain what it knows, why it knows it, and whether it is still allowed to know it.
