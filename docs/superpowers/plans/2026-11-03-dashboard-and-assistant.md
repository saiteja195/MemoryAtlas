# Dashboard and Shared Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every profile a dashboard that shows what the models processed, how much of the day the memories cover, a tracked to-do list and memory analytics, plus one shared floating assistant (dashboard and Atlas) that can answer fact, summary, to-do and memory-about-memory questions.

**Architecture:** Phase 1 meters every model call into a per-profile `model_calls` table and computes coverage from sources, exposed by `GET /insights`. Phase 2 adds a separate to-do scan pass, a `todo_state` table, an extended investigator prompt chosen by a code router (the existing prompt stays byte-identical), five new recall tools and a deterministic fallback for number-bearing answers. Phase 3 lifts the conversation above the pages, adds the launcher and docked panel, the to-do card, and the redesigned dashboard.

**Tech Stack:** FastAPI, SQLite per profile, pytest with `FakeLLM`; React, TypeScript, Vite, vitest, Playwright (CSS and SVG charts, no chart library).

**Spec:** `docs/superpowers/specs/2026-11-03-dashboard-and-assistant-design.md`

## Global Constraints

- Commits only as `saiteja195 <108951028+saiteja195@users.noreply.github.com>`; no `Co-authored-by:` or any trailer. Branch `feature/dashboard-and-assistant`. Conventional commits, scopes from `CONTRIBUTING.md`.
- Existing prompts stay **byte-identical** (`SYSTEM` in `recall/investigator.py`, the extraction prompt in `compiler/extract.py`, `EXTRACTABLE`). Recorded replies in `fixtures/llm_cache` are keyed by request hash.
- No chart library, no new heavy dependency. Embeddings stay local and are not metered.
- The usage log stores counts and sizes only: never prompts, replies, transcripts or media.
- Waking window `06:00` to `22:00`. "Today" is the latest day with memories. Times are naive local wall-clock strings; no timezone conversion.
- To-dos: only the owner's own `committed_to` claims and `requested` claims aimed at the owner; no due dates.
- Per-profile isolation: new tables live in the profile's database; new routes use `Depends(get_runtime)`; routes that call a model also use `dependencies=[Depends(spend)]`.
- Existing tests keep passing at every task. Light appearance default; dark supported. Soft-card tokens as on the Atlas.
- Code decides storage, visibility and deletion (`privacy/filter.py`); prompts decide nothing about privacy.

## Rulings (plan-level, against the spec)

- **R1.** The spec says the model cards aggregate the log "for that day". Calls happen at real time, not on the memory day, so `model_calls` gets a nullable `memory_day` (set while reading a memory, from the observation's `captured_at[:10]`). The cards show profile totals plus "from this day" figures for reads; `usage_stats` returns both.
- **R2.** `committed_to` is already emitted by the existing prompt for any speaker. The to-do list filters it to the owner as subject; promises by others never appear.
- **R3.** Answers that use `usage_stats` or `coverage` are never served from `answer_cache` (usage changes without `graph_version` changing).

## Review Focus

1. **Recorded replies still hit.** Pin a digest of the existing `SYSTEM` and extraction prompts, and run the existing `test_replay_*` suites unchanged. (Task 6, Task 8.)
2. **The to-do scan must never break ingestion.** In replay mode (no recording) or on a model outage the pass is skipped and the memory is still stored. (Task 6.)
3. **Forgetting reaches every new store.** Forgotten claims vanish from `/todos`, `todo_state`, restored chat history, extended answers and `day_summary`; usage rows survive (counts only). (Tasks 7, 9, 12.)
4. **Coverage edge cases.** Empty day, one source, sources before 06:00 or after 22:00, an episode crossing midnight, several days. (Task 3.)
5. **Metering must never fail a model call** or hold a database lock: a write error is swallowed and logged; concurrent requests of one profile are safe. (Task 1.)
6. **Phone width, empty profile, no usage yet, long names** in every new card and the panel. (Tasks 13 to 16.)

---

## Phase 1: usage log, coverage, model cards

### Task 1: Metering client and the `model_calls` table

**Files:**
- Create: `backend/app/llm/metered.py`, `backend/tests/test_metered.py`
- Modify: `backend/app/schema.sql`, `backend/app/llm/replay.py`, `backend/app/llm/meta.py`, `backend/app/config.py`

**Interfaces:**
- Produces: `usage_purpose(name: str, memory_day: str | None = None)` context manager (sets a `contextvars` purpose, default `"other"`); `class MeteredLLM` with `__init__(self, inner: LLMClient, conn: sqlite3.Connection, models: dict[str, str])` (`models` keys `"text"`, `"asr"`), `mode` property delegating to `inner.mode`, and `complete_json`, `describe_image`, `transcribe` with the `LLMClient` signatures; `RecordReplayClient.last_served: str` (`"cache"` or `"live"`); `MetaClient.last_usage: dict[str, int] | None` (`tokens_in`, `tokens_out`, read defensively from a `usage` object in the response, else `None`); `Settings.asr_model: str` (default `"muse-voice-transcribe-1.0"`).
- Table `model_calls(call_id TEXT PRIMARY KEY, at TEXT, model TEXT, kind TEXT CHECK IN ('text','vision','asr'), purpose TEXT, memory_day TEXT, served_from TEXT CHECK IN ('live','cache'), duration_ms INTEGER, ok INTEGER, images INTEGER, words_in INTEGER, words_out INTEGER, audio_ms INTEGER, tokens_in INTEGER NULL, tokens_out INTEGER NULL)`; `at` comes from `privacy.clock.now_iso()`.

- [ ] **Step 1: Write failing tests** in `test_metered.py` using a small fake inner client and an in-memory `db.connect()`:
  - `test_text_call_is_logged_with_purpose_and_sizes`: inside `usage_purpose("answer")`, `complete_json("sys words", "user words here", {})` returns the inner result unchanged and writes one row with `kind='text'`, `purpose='answer'`, `words_in == 5`, `ok == 1`, `served_from == 'live'`, `model` from `models["text"]`.
  - `test_vision_call_counts_one_image` (`images == 1`), `test_asr_call_counts_audio_ms_from_turns` (`audio_ms` equals the largest `end_ms`, `model` from `models["asr"]`).
  - `test_cache_hit_is_logged_as_cache`: wrap a `RecordReplayClient` in replay mode with a recorded reply; second call row has `served_from == 'cache'`.
  - `test_failure_is_logged_and_reraised`: inner raises `LLMUnavailable`; the exception propagates and the row has `ok == 0`.
  - `test_logging_error_never_fails_the_call`: a connection whose `execute` raises `sqlite3.Error` still returns the result.
  - `test_no_content_is_stored`: no column of any row contains the prompt text.
  - `test_meta_client_reads_usage_when_present` in `test_meta_client.py`: a response with `{"usage": {"input_tokens": 12, "output_tokens": 7}}` sets `last_usage`; one without it leaves `None`.
- [ ] **Step 2: Run** `cd backend && .venv/bin/pytest tests/test_metered.py tests/test_meta_client.py -q`. Expected: FAIL (module and attributes missing).
- [ ] **Step 3: Implement.** Add the table to `schema.sql`; add `last_served` to `RecordReplayClient._call` (set before returning or raising); add `last_usage` parsing to `MetaClient._responses_text`/`transcribe` paths; implement `MeteredLLM` (time with `time.perf_counter`, words by `len(text.split())`, write inside `try/except sqlite3.Error` then `log.warning`, commit after insert); add `asr_model` to `Settings` and pass it into `MetaClient`.
- [ ] **Step 4: Run** the same command plus `.venv/bin/pytest -q`. Expected: PASS, whole suite green.
- [ ] **Step 5: Commit** `feat(llm): meter every model call into a per-profile usage log`.

### Task 2: Wire metering into the runtime and the callers

**Files:**
- Modify: `backend/app/profiles/runtime.py`, `backend/app/engine.py`, `backend/app/capture/preview.py`, `backend/app/recall/investigator.py`
- Test: `backend/tests/test_metered_wiring.py`

**Interfaces:**
- Consumes: Task 1's `MeteredLLM`, `usage_purpose`.
- Produces: every `ProfileRuntime.llm` is a `MeteredLLM`; `MemoryEngine.ingest` runs under `usage_purpose("read_memory", cap.captured_at[:10])`; capture preview calls (`transcribe`, `describe_image`) run under `read_memory` with the draft's day when known; `Investigator.ask` runs under `usage_purpose("answer")`.

- [ ] **Step 1: Write failing tests:**
  - `test_ingest_logs_read_memory_with_the_memory_day`: advance the demo day two steps with `FakeLLM`; rows exist, all `purpose == 'read_memory'`, `memory_day == '2026-10-29'`.
  - `test_ask_logs_answer_calls`: after a scripted `/recall/ask` through the app, rows with `purpose == 'answer'` exist.
  - `test_usage_is_per_profile`: two profiles; one ingests, the other's `model_calls` stays empty.
  - `test_injected_test_llm_is_still_wrapped`: `create_app(Settings(...), FakeLLM())` yields `rt.llm` that is a `MeteredLLM` and still returns the fake's replies.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_metered_wiring.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** In `Runtimes._build`, wrap `llm = MeteredLLM(llm, conn, {"text": s.llm_model, "asr": s.asr_model})` before it is handed to the engine, recall and revoker. Add the `with usage_purpose(...)` blocks at the three call sites.
- [ ] **Step 4: Run** the new tests and the full suite. Expected: PASS (existing tests that assert `rt.llm is fake` are updated to compare through the wrapper's `inner`; list any such change in the commit body).
- [ ] **Step 5: Commit** `feat(profiles): meter model calls per profile with their purpose`.

### Task 3: Coverage calculation

**Files:**
- Create: `backend/app/insights/__init__.py`, `backend/app/insights/coverage.py`, `backend/tests/test_coverage.py`

**Interfaces:**
- Produces: `coverage(conn, day: str, window: tuple[int, int] = (6, 22)) -> dict` returning `{"day", "window": [6, 22], "hours": [{"hour": int, "covered": bool, "count": int}], "spans": [{"start": "HH:MM", "end": "HH:MM"}], "covered_hours": int, "waking_hours": int, "share": float, "busiest_hour": int | None, "longest_gap": {"start": "HH:MM", "end": "HH:MM", "minutes": int} | None}`; `memory_days(conn) -> list[str]` (days with at least one readable source, ascending). Uses `privacy.filter.valid_source_ids` so withdrawn sources do not count.

- [ ] **Step 1: Write failing tests** (build data with the demo day and `FakeLLM`, plus small direct inserts):
  - `test_sample_day_numbers`: `covered_hours == 4`, `waking_hours == 16`, `share == 0.25`, `busiest_hour == 12`, `longest_gap == {"start": "13:20", "end": "17:45", "minutes": 265}`.
  - `test_empty_day`: no sources gives `covered_hours == 0`, `share == 0`, `busiest_hour is None`, `longest_gap is None`, `spans == []`.
  - `test_single_source_gap_is_the_longer_side`: one source at 09:00 gives a trailing gap `09:00` to `22:00` of 780 minutes.
  - `test_sources_outside_the_window_are_listed_but_not_counted`: a source at 05:30 appears in `spans`, adds no covered hour, and clamps gaps to the window.
  - `test_episode_crossing_midnight_is_cut_at_the_day`: an episode 23:30 to 00:30 covers hour 23 only on its own day (outside the window), and the next day's `spans` starts at `00:00`.
  - `test_withdrawn_source_does_not_count`: revoke the conversation grant; its hours drop out.
  - `test_memory_days_lists_each_day_once`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_coverage.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** from `sources.captured_at` (readable ids only) and episode `attrs.start/end` for that day; an hour is covered when a source falls in it or an episode overlaps it; busiest hour is the hour with the most sources (earliest on a tie); gaps are measured between sorted spans including the leading and trailing gap inside the window.
- [ ] **Step 4: Run** the tests and the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(insights): day coverage with gaps and busiest hour`.

### Task 4: Usage summary and `GET /insights`

**Files:**
- Create: `backend/app/insights/usage.py`, `backend/tests/test_insights_api.py`
- Modify: `backend/app/api.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces: `usage_summary(conn, memory_day: str | None = None) -> dict` returning `{"recorded": bool, "since": str | None, "total": Bucket, "day": Bucket | None, "models": [ModelRow]}`, where a `Bucket` is `{"calls", "live", "cache", "failed", "reading", "answering", "photos", "words_read", "audio_minutes", "avg_ms"}` and a `ModelRow` is `{"model", "kind_label": "Reads and answers" | "Transcribes", "calls", "photos", "words_read", "audio_minutes", "avg_ms", "reading", "answering", "cache"}`. Route `GET /insights?day=YYYY-MM-DD` returns `{"day": str | None, "days": [str], "coverage": dict | None, "usage": dict}`; with no `day` it uses the latest memory day; with no memories `day` is `None` and `coverage` is `None`. `todos_open` is added in Task 7.

- [ ] **Step 1: Write failing tests:**
  - `test_usage_summary_totals_and_split`: seeded rows give the exact buckets (reading vs answering, photos, words, audio minutes rounded to one decimal, average ms of live calls only).
  - `test_no_rows_means_not_recorded`: `recorded == False`, zero buckets.
  - `test_day_bucket_uses_memory_day_not_call_time`.
  - `test_insights_defaults_to_the_latest_day` and `test_insights_with_a_chosen_day`; unknown day returns `coverage` with zero hours, not an error; malformed `day` returns 422.
  - `test_insights_requires_sign_in_and_is_private`: 401 without a session; profile B never sees A's numbers.
  - `test_insights_for_an_empty_profile`: `{"day": None, "days": [], "coverage": None, ...}` with `usage.recorded == False`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_insights_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `usage_summary`, then the route using `rt.conn`.
- [ ] **Step 4: Run** tests and full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): insights route with coverage and model usage`.

### Task 5: Frontend data layer and the two new cards

**Files:**
- Create: `frontend/src/utils/insights.ts`, `frontend/src/utils/insights.test.ts`, `frontend/src/components/CoverageStrip.tsx`, `frontend/src/components/ModelCards.tsx`
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/styles.css`

**Interfaces:**
- Produces: types `Insights`, `Coverage`, `UsageSummary`, `ModelRow`; `api.insights(day?: string): Promise<Insights>`; pure helpers in `insights.ts`: `stripBlocks(coverage): { left: number; width: number }[]` (percent of the window), `gapBox(coverage): { left: number; width: number; label: string } | null`, `formatMinutes(n: number): string` (`265` becomes `"4 h 25 min"`, `45` becomes `"45 min"`, `0` becomes `"0 min"`), `modelLine(row: ModelRow): string[]`; components `CoverageStrip({ coverage })` and `ModelCards({ usage, day })`.

- [ ] **Step 1: Write failing tests** in `insights.test.ts`: `formatMinutes` cases (`0`, `1`, `60`, `265`, `1440`); `stripBlocks` for the sample coverage returns percentages `19.8, 23, 40.6, 73.4` (one decimal) and never a negative or over-100 value for spans outside the window; `gapBox` is `null` when there is no gap and otherwise carries `"4 h 25 min with no memories"`; `modelLine` omits token figures when absent and shows "replayed, no model call" count when `cache > 0`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/utils/insights.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the helpers, the types, `api.insights`, and the two components. States: `CoverageStrip` with no memories shows "Add a memory to see your day"; `ModelCards` with `recorded == false` shows "No model calls recorded yet" (and "Built from recorded replies" when the profile is a demo profile, via a `demo` prop the Dashboard sets from `me.profile.demo_kind`). Long values wrap; the strip scrolls sideways under 520 px.
- [ ] **Step 4: Run** `npm run check`. Expected: PASS, type-check clean.
- [ ] **Step 5: Commit** `feat(ui): coverage strip and model cards`.

---

## Phase 2: to-dos and recall extensions

### Task 6: The to-do scan pass

**Files:**
- Create: `backend/app/compiler/todo_scan.py`, `backend/tests/test_todo_scan.py`
- Modify: `backend/app/compiler/pipeline.py`, `backend/app/compiler/extract.py` (`PREDICATES` only, to add `requested`; **not** `EXTRACTABLE` and not the prompt), `backend/tests/fakes.py`, `frontend/src/utils/graph.ts` (`PREDICATES` map: `requested: "asked"`), `backend/tests/test_prompt_pins.py`

**Interfaces:**
- Consumes: `ExtractedClaim` fields, `LLMClient.complete_json`.
- Produces: `TODO_PREDICATES = ("committed_to", "requested")`; `scan_todos(llm, obs: Observation, known: list[str]) -> list[ExtractedClaim]` using its own system prompt (starts with `"You find promises and requests"`) and its own Pydantic model whose predicate `Literal` is `TODO_PREDICATES`; it runs under `usage_purpose("todo_scan", ...)`; it returns `[]` on `LLMUnavailable` of any kind and on invalid replies after one repair attempt. `CompilePipeline` calls it only for observations from a conversation (`transcript_segment`) or a typed note (the executor confirms which source kind notes are stored under), never for photos, calendar entries or location, and stores the claims through the existing store path; a skipped or failed scan never rejects the observation.

- [ ] **Step 1: Write failing tests:**
  - `test_prompt_pins`: SHA-256 of `recall.investigator.SYSTEM` and of the extraction system prompt equals the digests recorded in the test (compute them from the current code in this step and paste them in; this guards "byte-identical").
  - `test_request_aimed_at_the_owner_is_stored`: a fake scan reply `requested(Alex, value="send the notes", object="Me")` produces an active claim with predicate `requested`, subject Alex, object Me, justified by the observation's source.
  - `test_promise_missed_by_extraction_is_added_once`: when extraction already produced the same `committed_to` text, only one claim exists afterwards.
  - `test_scan_unavailable_does_not_reject_the_memory`: a fake that raises `LLMUnavailable("no recorded response")` for the scan prompt only still stores the extraction claims and reports the observation as ingested.
  - `test_invalid_scan_reply_is_dropped`: a reply with an unknown predicate yields no claims and no error.
  - `test_scan_skips_frames_and_calendar`: a photo observation causes no scan call.
  - `test_existing_replay_suites_still_pass`: not a new test; Step 4 runs `tests/test_replay_*.py` unchanged.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_todo_scan.py -q`. Expected: FAIL (the pin test passes once its digests are filled in; the rest fail).
- [ ] **Step 3: Implement** `todo_scan.py` and the pipeline hook; extend `FakeLLM.complete_json` to answer the scan prompt from a `todo_replies` list (default `{"claims": []}`) **before** the forced `extraction_replies`, so existing tests that script extraction replies are unaffected.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` (all suites, including every `test_replay_*`). Expected: PASS with no recorded-reply miss.
- [ ] **Step 5: Commit** `feat(compiler): scan conversations and notes for promises and requests`.

### Task 7: To-do store, routes and forgetting

**Files:**
- Create: `backend/app/todos.py`, `backend/tests/test_todos.py`
- Modify: `backend/app/schema.sql`, `backend/app/api.py`, `backend/app/privacy/revocation.py`, `backend/app/db.py` (`_TABLES_IN_DELETE_ORDER`), `backend/app/insights/` route from Task 4

**Interfaces:**
- Table `todo_state(claim_id TEXT PRIMARY KEY, state TEXT CHECK IN ('open','done','dismissed'), updated_at TEXT)`.
- Produces: `list_todos(conn, owner_id: str, state: str = "open") -> list[dict]` where each item is `{"claim_id", "kind": "promise" | "request", "text", "who": str | None, "when": str | None, "source_label": str, "state", "citations": [ClaimView]}`; `set_todo_state(conn, claim_id, state) -> None` (raises `KeyError` for an id that is not a visible to-do); `count_open(conn, owner_id) -> int`. Routes `GET /todos?state=open|done|dismissed|all`, `POST /todos/{claim_id}` body `{"state": ...}` (404 for non-to-dos and for other profiles' ids, 422 for a bad state). The insights response gains `"todos_open": int`.

- [ ] **Step 1: Write failing tests:**
  - `test_owner_promise_and_request_become_todos`; `test_other_peoples_promise_is_not_a_todo` (the staged day's "Alex committed to send the proposal by Friday" is excluded).
  - `test_state_changes_and_filters`: open to done to open; `state=done` lists only done.
  - `test_forgetting_removes_the_todo_and_its_state`: revoke the grant behind the claim; `GET /todos?state=all` no longer lists it and `todo_state` has no row for it.
  - `test_superseded_or_retracted_claim_drops_out` (via `/claims/{id}/correct` retract).
  - `test_todo_ids_are_private_to_a_profile`: B posting A's claim id gets 404.
  - `test_db_reset_clears_todo_state`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_todos.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** through `authorized_claim_ids` and `READABLE`; the revocation engine deletes `todo_state` rows whose claim ids it removes; add the table to the reset order.
- [ ] **Step 4: Run** tests and full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(todos): tracked promises and requests with done and dismiss`.

### Task 8: Router, extended prompt, `as_of`, cache rules

**Files:**
- Create: `backend/app/recall/router.py`, `backend/tests/test_recall_router.py`
- Modify: `backend/app/recall/investigator.py`, `backend/app/recall/service.py`, `backend/app/api.py` (`AskBody`)

**Interfaces:**
- Produces: `needs_extended(question: str) -> str | None` returning the route name (`"time"`, `"summary"`, `"todo"`, `"memory"`) or `None`; `EXTENDED_ADDENDUM: str` (date, time-of-day windows morning 05:00 to 11:59, afternoon 12:00 to 17:59, evening and tonight 18:00 to 23:59, and the five new tools' descriptions) appended to `SYSTEM` as `SYSTEM + EXTENDED_ADDENDUM` only for routed questions; `Investigator.ask(question, as_of: str | None = None)`; `RecallService.ask(question, as_of=None)`; `AskBody.as_of: str | None` (`YYYY-MM-DD`, validated). Cache key: unchanged `sha256(norm(question))` for unrouted questions; for routed ones `sha256(route + as_of + norm(question))`, and answers that used `usage_stats` or `coverage` are not cached (R3).

- [ ] **Step 1: Write failing tests:** a parametrized `test_router_matrix` over all sixteen prompts in the spec's Goals list with their expected route (the four fact prompts "Where did I leave my wallet?", "Which restaurant did Alex recommend?", "What time was my meeting with Alex?" give `None`; "Who did I meet today?" gives `"time"`; the summary prompts give `"summary"` or `"time"`; the to-do prompts give `"todo"`; the four memory prompts give `"memory"`); `test_unrouted_question_sends_the_original_system_prompt` (the fake records the system string and it equals the pinned `SYSTEM`); `test_routed_question_sends_system_plus_addendum_and_the_date`; `test_same_question_on_two_days_is_not_shared_by_the_cache`; `test_stats_answers_are_not_cached`; `test_ask_without_as_of_defaults_to_the_latest_memory_day`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_recall_router.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the router (keyword and phrase rules, case-insensitive, tested by the matrix), the addendum, `as_of` plumbing and the cache key rules. The user payload for routed questions adds `"as_of"` and `"today": as_of`; unrouted payloads are unchanged.
- [ ] **Step 4: Run** the tests, every `test_replay_recall*`, and the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(recall): extended prompt for date, summary, to-do and memory questions`.

### Task 9: The five new tools

**Files:**
- Create: `backend/app/recall/tools_extra.py`, `backend/tests/test_tools_extra.py`
- Modify: `backend/app/recall/tools.py` (registry hook), `backend/app/recall/investigator.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 7.
- Produces: `RecallTools(conn, extended: bool = False)`; when `extended` is true the registry also holds `day_summary(time_from, time_to)` (moments with participants and summary text, people, places, counts), `open_todos()`, `coverage(time_from=None, time_to=None)` (covered spans and gaps with preformatted `"13:20"` and `"4 h 25 min"` strings plus raw minutes), `usage_stats(day=None)` (the `usage_summary` figures, preformatted), `uncertain_claims()` (disputed, partial and below-0.6-confidence claims, readable only). Claim-bearing tools register their claim ids in `tools.returned`; `coverage` and `usage_stats` register a stats token `tools.stats_returned: dict[str, dict]` keyed by tool name.

- [ ] **Step 1: Write failing tests:** one per tool on the staged day with exact expectations (for example `coverage` returns the 265-minute gap with `"4 h 25 min"`); `test_forgotten_claims_never_appear` for `day_summary`, `open_todos` and `uncertain_claims` after a revocation; `test_extended_tools_are_absent_by_default` (registry of an unextended `RecallTools` has the original seven names only); `test_unknown_window_returns_empty_not_error`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_tools_extra.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement**, and have `Investigator` build `RecallTools(conn, extended=route is not None)`.
- [ ] **Step 4: Run** tests and the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(recall): summary, to-do, coverage, usage and uncertainty tools`.

### Task 10: Stats citations, the number check and the deterministic fallback

**Files:**
- Create: `backend/app/recall/templates.py`, `backend/tests/test_stats_answers.py`
- Modify: `backend/app/recall/investigator.py`, `backend/app/recall/service.py`

**Interfaces:**
- `Step.cited_tools: list[str] = []`; `Answer.cited_tools: list[str]` and the `as_dict()` output gains `"cited_tools"`; `numbers_in(text: str) -> set[str]` (digit groups and `HH:MM` tokens); `render_coverage(stats: dict) -> str` and `render_usage(stats: dict) -> str` in `templates.py`.
- Post-check: an `answered` or `partial` reply with `cited_tools` (and no claim ids) is valid only if every named tool was called, and every number in the answer appears in the union of that tool's result strings and raw values; failures use the existing one-retry rule; a second failure returns the deterministic template for the first cited tool, with `checks` noting the fallback. A reply with neither claims nor tools still fails the old check.

- [ ] **Step 1: Write failing tests:** `test_coverage_answer_with_correct_numbers_passes`; `test_invented_number_is_retried_then_replaced_by_the_template` (scripted fake returns `"You covered 90% of your day"` twice; the final answer equals `render_coverage(...)`, `checks` mentions the fallback, status is `answered`); `test_equivalent_formats_are_accepted` (`"4 h 25 min"` and `"265 minutes"` both pass because both appear in the tool's preformatted strings); `test_usage_answer_cites_the_tool_not_a_claim`; `test_claim_answers_still_need_claims`; `test_stats_answer_is_not_cached` (second ask calls the model again).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_stats_answers.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the check, templates and the service's no-cache rule for answers with `cited_tools`.
- [ ] **Step 4: Run** tests and the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(recall): verified numbers for usage and coverage answers`.

### Task 11: A test for every prompt, and a live checker

**Files:**
- Create: `backend/tests/test_assistant_prompts.py`, `backend/scripts/check_prompts.py`

**Interfaces:**
- Consumes: Tasks 6 to 10, the staged-day snapshot loaded through `/demo/load-sample`.

- [ ] **Step 1: Write failing tests**, one per prompt in the spec's Goals list (sixteen, parametrized), each driving `POST /recall/ask` with `as_of` where relevant and a scripted `FakeLLM` that plays the tool calls and final reply a good model would give. Assertions per group: facts cite claims and keep the "Last confirmed sighting at HH:MM" form for the wallet; summaries cite claims from several moments; "Did I promise anyone anything?" cites the owner's promise when one exists and **abstains with "no record"** when none does; "What did the models read today?" cites `usage_stats` and its numbers match the log; "What happened between 13:20 and 17:45?" cites `coverage` and mentions the gap; "What are you unsure about?" lists disputed or partial claims or abstains.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_assistant_prompts.py -q`. Expected: FAIL.
- [ ] **Step 3: Fix** any production gap the tests expose (keep fixes minimal, each with its own failing assertion first). Add `scripts/check_prompts.py`: reads `MODEL_API_KEY` from the environment (never printed), loads the sample into a scratch data directory, asks the twelve non-to-do prompts through the live model and prints each answer, status and steps; exits non-zero on a transport error only.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected: PASS. If a key is set in the executor's own shell, run the checker once and note the result in the ledger; otherwise skip it and say so in the final report.
- [ ] **Step 5: Commit** `test(recall): one scripted test per assistant prompt, plus a live checker`.

### Task 12: Chat persistence

**Files:**
- Create: `backend/tests/test_chat_history.py`
- Modify: `backend/app/schema.sql`, `backend/app/migrate.py`, `backend/app/recall/service.py`, `backend/app/api.py`

**Interfaces:**
- `chat_messages` gains `as_of TEXT`, `status TEXT`, `cited_tools TEXT NOT NULL DEFAULT '[]'` (migration adds them to older databases); `RecallService._log(question, out, as_of)` stores them; `GET /chat` returns `[{"id", "role", "text", "as_of", "status", "cited_claim_ids", "citations": [ClaimView], "cited_tools", "redacted": bool}]` oldest first, citations restricted to readable claims.

- [ ] **Step 1: Write failing tests:** `test_history_survives_a_runtime_rebuild`; `test_history_keeps_as_of_and_status`; `test_forgotten_citations_are_dropped_and_text_redacted` (after a revocation the message is redacted by the existing code and `citations == []`); `test_chat_is_private_to_the_profile`; `test_old_database_is_migrated` (a database created without the new columns opens and works).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_chat_history.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the columns, migration and route.
- [ ] **Step 4: Run** tests and full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(chat): keep the conversation with its day and status, and serve it back`.

---

## Phase 3: dashboard and assistant interface

### Task 13: Shared conversation and selected-day state, suggestions

**Files:**
- Create: `frontend/src/hooks/useAssistant.ts`, `frontend/src/utils/assistant.ts`, `frontend/src/utils/assistant.test.ts`
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/App.tsx`

**Interfaces:**
- Produces: `api.ask(question, asOf?)`, `api.chat()`, `api.todos(state)`, `api.setTodo(claimId, state)` and their types; `buildSuggestions(input: { graph: Graph; goals: string[]; todosOpen: number; selection: Selection; hasMemories: boolean }): { empty: string | null; groups: { title: "Facts" | "Summary" | "To-dos" | "About my memory"; prompts: string[] }[] }`; `useAssistant(day: string | null)` returning `{ messages, asking, ask(q), open, setOpen, expanded, setExpanded }`, loading history from `api.chat()` once signed in; a `useDay()` hook (or state in `Gate`) holding the selected day, defaulting to the latest of `insights.days`, shared by the Dashboard, the Atlas and the assistant.

- [ ] **Step 1: Write failing tests** for `buildSuggestions`: names and places in prompts come from the graph (for example "Which restaurant did Alex recommend?" only when a person and a place exist); a profile with no memories returns `empty == "Add a memory to start"` and no prompts; goals reorder groups (`work_meetings` puts To-dos first); a selected card adds "Ask about this" prompts naming it; prompts are unique and each at most 90 characters; a graph with a blank-named entity never yields "Unnamed" in a prompt.
- [ ] **Step 2: Run** `npx vitest run src/utils/assistant.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the utils, hook and client calls; move the conversation state out of `Atlas` into `Gate` (above the page switch) so it is shared; messages carry `asOf` and a derived `dayChip` when it differs from the selected day.
- [ ] **Step 4: Run** `npm run check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): shared assistant state, selected day and tailored prompts`.

### Task 14: Launcher, docked panel, expanded view

**Files:**
- Create: `frontend/src/components/Assistant.tsx`, `frontend/src/components/Thread.tsx`
- Modify: `frontend/src/components/AskPanel.tsx` (extract the thread into `Thread`; remove the panel from the Atlas tabs), `frontend/src/App.tsx`, `frontend/src/styles.css`, `frontend/e2e/walkthrough.cjs`

**Interfaces:**
- Consumes: Task 13. `Assistant` props: `{ assistant: ReturnType<typeof useAssistant>; suggestions; mode; onCite; onWhy }`. Launcher text "Ask your memory", `Cmd/Ctrl+K` toggles; `Escape` closes; the panel is `role="dialog"` with `aria-label`, focus moves to the input on open and returns to the launcher on close; expanded is a full-height sheet; receipts and status badges reuse `Thread`.

- [ ] **Step 1: Write failing tests** for the pure parts only (keyboard-shortcut matcher `isLauncherShortcut(e)`, and `Thread` grouping helpers extracted from `AskPanel`) in `assistant.test.ts` additions; behaviour is proven in the browser step.
- [ ] **Step 2: Run** `npx vitest run`. Expected: FAIL for the new tests.
- [ ] **Step 3: Implement** the components and styles (soft-card look, mockup B). States: loading history, empty profile, asking (the three working steps from `phaseAt`), error and "not recorded" for replay mode, a long answer scrolls inside the panel, long names ellipsize. The Atlas keeps its Facts and Consent tabs. Update `e2e/walkthrough.cjs` wherever it used the Atlas Ask tab to open the launcher instead.
- [ ] **Step 4: Verify.** `npm run check`; rebuild with `docker compose up -d --build web`, sign up, load the sample, open the launcher on the dashboard, ask a prompt, switch to the Atlas and see the same conversation, press `Cmd+K`, expand, close with `Escape`; check light, dark and a 375 px window. Run `npm run e2e:walkthrough` as its header describes. Expected: all hold.
- [ ] **Step 5: Commit** `feat(ui): floating assistant with docked and expanded views, shared across pages`.

### Task 15: To-do card

**Files:**
- Create: `frontend/src/components/TodoCard.tsx`, `frontend/src/utils/todos.ts`, `frontend/src/utils/todos.test.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- `TodoCard({ todos, onSetState, onOpenMemory, loading, error })`; `utils/todos.ts`: `splitByState(items)`, `todoMeta(item): string` (`"You said so · 12:40 conversation"` or `"Alex asked · by Friday"` from the item's own words).

- [ ] **Step 1: Write failing tests** in `todos.test.ts`: `todoMeta` for a promise and a request, with a missing time and with a blank `who` (never prints "undefined" or "Unnamed"); `splitByState` ordering (open newest first).
- [ ] **Step 2: Run** `npx vitest run src/utils/todos.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the card: Open and Done tabs with counts, a circle control to tick done (undo within the list), a dismiss control, the receipt chip opening the memory, empty state "No promises or requests found in your memories", error and loading states, optimistic update with rollback on a failed `POST`.
- [ ] **Step 4: Run** `npm run check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): to-do card with done and dismiss`.

### Task 16: Dashboard redesign, day picker, docs and the end-to-end run

**Files:**
- Create: `frontend/e2e/assistant.cjs`
- Modify: `frontend/src/components/Dashboard.tsx`, `frontend/src/styles.css`, `frontend/package.json` (script `e2e:assistant`), `docs/LOCAL_SETUP.md`, `README.md`, `docs/IMPLEMENTATION_PLAN.md` (one line under scope)

**Interfaces:**
- Consumes: Tasks 5, 13, 15. Dashboard layout (mockup B): hero story line and confidence ring; `CoverageStrip`; `ModelCards`; `TodoCard`; facts by kind; where facts come from; most mentioned; "Not sure about"; privacy line. A day picker (hidden when one day). The old "Suggested next steps" card is replaced by a compact "Next" row for the sample controls (Play next, Play the day, Upload live photo) that appear only while the sample is unfinished.

- [ ] **Step 1: Write the failing end-to-end script** `e2e/assistant.cjs` (header says how to run it, as `profiles.cjs` does): sign up, open sample, assert the coverage strip shows "25%", both model cards render, the to-do card shows its empty state, open the launcher, ask "Summarise my day." (replay mode: the scripted recorded question), see an answered reply with a receipt chip, switch to the Atlas and find the same message, then reload and find it again. Run it first and see it fail on the missing dashboard pieces.
- [ ] **Step 2: Run** the script as documented. Expected: FAIL.
- [ ] **Step 3: Implement** the dashboard assembly; keep `summarize` and its tests; remove nothing the e2e walkthrough still needs.
- [ ] **Step 4: Verify.** `npm run check`; run `npm run e2e:assistant`, `npm run e2e:profiles` and `npm run e2e:walkthrough`; look at light, dark and 375 px in Chromium; update the three documents (how to read the cards, the usage log's privacy line, how the assistant picks its day, the to-do rules, the optional live recording of the sample day with the key kept in the owner's shell).
- [ ] **Step 5: Commit** `feat(ui): dashboard with coverage, model activity, to-dos and memory analytics`.

---

## Self-Review

- **Spec coverage:** model activity (Tasks 1, 2, 4, 5), coverage (3, 4, 5), to-dos (6, 7, 15), analytics kept (16), shared assistant (13, 14), every prompt supported and tested (8 to 11), tailored prompts (13), persistence (12), privacy and forgetting (7, 9, 12), phases in order (1 to 5, 6 to 12, 13 to 16), optional live recording (documented in 16 and checked in 11). Gap check: the spec's "Phase 1: `todos_open` in insights" is added in Task 7.
- **Type consistency:** `usage_purpose`/`MeteredLLM` (1, 2), `coverage`/`memory_days` (3, 4, 9), `usage_summary` (4, 9), `list_todos`/`count_open` (7, 9), `needs_extended`/`as_of` (8, 11, 12), `Step.cited_tools` (10), `api.ask(question, asOf)` (13, 14).
- **Proportion:** each task names files, signatures, the tests and their assertions, and the verification command; bodies are left to the implementer.
