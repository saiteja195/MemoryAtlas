# Dashboard and shared assistant: design

Status: draft for approval. Project 2 of 3. Project 1 (profiles and onboarding) and Project 3 (the soft-card Atlas)
are merged. Builds on `main`.

## Intent

Today the dashboard counts facts and sources, and asking a question means going to the Atlas. A person looking at
their memory should see, at a glance, three things: **what the models read and how much** (so they can trust and
audit the system), **how much of their day the memories cover and where the gaps are**, and **what they promised or
were asked to do and may have forgotten**. They should be able to ask anything about their memory from either page,
in one conversation, and get an answer that is grounded in their own memories or says plainly that there is none.

## Goals

- **Model activity (new):** per model (Muse Spark for reading and answering, Muse Voice for transcription): calls,
  photos read, audio minutes transcribed, words read, average response time, split by purpose (reading memories,
  answering questions), and how many requests were replayed from the saved cache instead of the model.
- **Day coverage (new):** a 24-hour strip of which hours have memories, the share of waking hours covered (06:00 to
  22:00), the busiest hour and the longest gap.
- **To-dos (new):** a tracked list on the dashboard of promises the person made and requests made of them, each with who,
  what, when and the memory behind it. The person can mark one done or dismiss it.
- **Memory analytics (kept, redesigned):** confidence, facts by kind, where facts come from, most-mentioned people and
  places, what Muse is unsure about, the "raw media kept: 0 B" line.
- **Shared assistant (new):** a floating launcher that opens a docked panel and expands to full height. One
  conversation, shared by the Dashboard and the Atlas, kept across reloads. It replaces the Atlas Ask panel.
- **Every prompt below works** (backend and UI), each backed by a test:
  - Facts: "Where did I leave my wallet?", "Which restaurant did Alex recommend?", "Who did I meet today?",
    "What time was my meeting with Alex?"
  - Summary: "Summarise my day.", "What happened this morning?", "What was the most important moment?",
    "Where did I spend the most time?"
  - To-dos: "What did I say I would do today?", "Did I promise anyone anything?", "Did anyone ask me to do
    something?", "What did I forget to follow up on?"
  - About the memory: "What did the models read today?", "How much of my day is covered?",
    "What happened between 13:20 and 17:45?", "What are you unsure about?"
- Suggested prompts are tailored to the person's own people and places and to the goals they chose at sign-up.

## Non-goals

- No charts library, no new heavy dependency. Charts are CSS and SVG.
- No due-date parsing: a to-do shows the person's own words ("by Friday") but has no structured date, reminders or
  notifications.
- No to-dos for promises made by other people ("Alex said they would send it").
- No change to consent, revocation, or the rule that raw media is never kept.
- No new model provider, and no model for embeddings (they stay local and are not counted as model calls).
- No multi-day trends. The dashboard shows one day at a time (the latest day with memories by default, with a day picker
  when there are several).

## Anti-goals

- The usage log holding content: it stores counts and sizes only, never prompts, replies, transcripts or media.
- An answer to a memory-about-memory question (usage, coverage) that quotes a number the code did not compute.
- The assistant inventing a promise, a fact or a number. When nothing is found it says so.
- One profile seeing another's usage, to-dos or conversation.
- A forgotten memory still showing up as a to-do, in the conversation, or in an answer.

## Constraints

- `CLAUDE.md`: the LLM proposes; code decides storage, visibility and deletion. To-do visibility and forgetting are
  enforced by the same privacy filter the recall tools use, not by prompts.
- Per-profile isolation as built in Project 1: the usage log, to-do state and conversation live in the profile's own
  SQLite file. All new routes use the per-profile runtime dependency and the `spend` budget where they call a model.
- Existing tests keep passing. New behaviour is test-first.
- Light appearance is the default, dark and auto are supported. Soft-card styling and tokens as on the Atlas.
- Recorded model replies (`fixtures/llm_cache`) are keyed by a hash of the request (system prompt, user text and schema).
  **Existing prompts stay byte-identical**, so every recorded reply and every existing test keeps working. New behaviour
  uses new prompts, which only need recording if the owner wants them in the sample day (see "Needs the owner").
- Commits only as `saiteja195`, no trailers. Conventional commits.

## Design

### Phase 1: usage log, coverage, model cards

- **Usage log.** A table `model_calls` in each profile database: `call_id`, `at`, `model`, `kind`
  (`text` | `vision` | `asr`), `purpose` (`read_memory` | `answer` | `summarise` | `other`), `served_from`
  (`live` | `cache`), `duration_ms`, `ok`, and size fields: `images`, `words_in`, `words_out`, `audio_ms`, and
  nullable `tokens_in` / `tokens_out` (recorded only if the model API returns usage; the client does not read it today).
- **Metering.** A decorator client wraps the profile's `LLMClient` where the runtime is built. It times each call,
  measures sizes from the arguments and result, and learns whether the call was served from cache. The caller sets the
  purpose (ingest paths say `read_memory`, the investigator `answer`). Failed calls are logged with `ok = false`.
- **Insights route.** `GET /insights?day=YYYY-MM-DD` returns `{ day, days, coverage, models, todos_open }`.
  Stored times are naive local wall-clock strings (`2026-10-29T09:10:00`, no offset) and are used as they are: no timezone
  conversion anywhere. Coverage is computed from `sources.captured_at` and episode spans for that day: per-hour coverage for 06:00 to 22:00,
  covered share, busiest hour, longest gap (start, end, minutes). Models aggregates the log for that day.
- **Demo and old profiles.** Profiles without log rows show "No model calls recorded yet". A demo profile built from a
  snapshot says "Built from recorded replies".

### Phase 2: recall extensions and to-dos

- **Date context, without touching the existing investigator prompt.** The recall service passes `as_of`: the day shown.
  "Today", "this morning", "this afternoon" and "tonight" resolve against it. A code router (keyword rules, tested) sends a
  question to an **extended** investigator prompt only when it needs something new: a relative-time word, a summary, a
  to-do, or a memory-about-memory question. The extended prompt is the existing prompt plus the date, the time-of-day windows
  and the new tools. Every other question uses the existing prompt unchanged, so its recorded replies still match.
- **New tools** (deterministic code, results are cited): `day_summary(time_from, time_to)` returns moments, people, places
  and counts for a window; `open_todos()`; `coverage(time_from, time_to)` returns covered spans and gaps;
  `usage_stats(day?)` returns the aggregated log; `uncertain_claims()` returns disputed, partial and low-confidence claims.
  They are only offered by the extended prompt.
- **Citations for memory-about-memory answers.** An answer built from `coverage` or `usage_stats` cites that tool result
  instead of a claim. A post-check requires every number in such an answer to appear in the tool result, whose figures are
  also given pre-formatted ("13:20", "4 h 25 min"). If the check fails, the model gets one retry with the failure named
  (the existing retry rule). If it fails again, the reply is a **deterministic answer built from the tool result** by a
  small template (one for coverage, one for usage), never "I can't verify that" and never an unchecked number.
- **Promises and requests, as a separate pass.** `committed_to` is already in the vocabulary and the existing extraction
  prompt emits it when it notices a promise. A new **to-do pass** runs after extraction on conversation segments and notes
  only, with its own new prompt: it proposes `requested(person, value)` ("Alex asked me to send the notes", the owner being
  the one asked) and any `committed_to` the first pass missed. Claims go through the normal store, which already merges
  identical claims, so there are no duplicates. The pass is one extra model call per such observation, logged as purpose
  `todo_scan`. The existing extraction prompt is not edited.
- **To-dos.** A to-do is an active, readable claim with predicate `committed_to` whose subject is the owner, or `requested`
  whose target is the owner. State lives in `todo_state(claim_id PRIMARY KEY, state, updated_at)` with `open` (default),
  `done`, `dismissed`. `GET /todos?state=open|done|all` joins claims through the privacy filter, so a forgotten or
  expired memory drops out. `POST /todos/{claim_id}` sets the state. Revocation also deletes the `todo_state` rows of
  the claims it removes.

### Phase 3: dashboard and assistant interface

- **Dashboard layout** (mockup B, approved): story line and confidence ring on top, the coverage strip, the two model
  cards, the to-do list (open and done tabs), then memory analytics. Cards are the Atlas soft-card style. At phone
  width the grid becomes one column and the strip scrolls sideways.
- **Assistant.** A launcher button bottom-right (also `Cmd/Ctrl+K`) opens a docked panel, and an expand control makes it
  full height. State lives above the Dashboard and the Atlas, so the conversation is the same on both. Messages persist
  in the existing `chat_messages` table and are redacted by the existing revocation code.
- **Which day it answers for.** The selected day is shared state: the dashboard's day picker, the Atlas and the assistant all
  use it, and it defaults to the latest day with memories. Each question is sent with its `as_of`, each stored message keeps
  it, and a message about a different day than the one now selected shows a small date chip.
- **Prompts.** Grouped suggestions (Facts, Summary, To-dos, About my memory). People and places come from the profile's
  graph, ordering from the goals saved at sign-up. A profile with no memories shows "Add a memory to start" and no
  questions. On the Atlas, a selected card adds "Ask about this".
- **States.** Every card and the panel have loading, empty and error states. Answers show their receipt chips; a chip
  opens the memory behind it.

## Decisions I made (please check)

- **D1.** Waking window 06:00 to 22:00 for the coverage percentage.
- **D2.** "Today" means the latest day with memories, not the computer's date, so the sample day (29 October) always
  answers "today".
- **D3.** To-dos include only the owner's own promises and requests made of the owner. No due dates.
- **D4.** The usage log stores counts only and is kept when a memory is forgotten (it holds no content).
- **D5.** Models appear as Muse Spark (text and vision) and Muse Voice (transcription). Token cards appear only if the API
  returns usage.
- **D6.** One docked panel for both pages, `Cmd/Ctrl+K`, replacing the Atlas Ask panel.
- **D7.** Phases ship in order and each leaves the app working: usage and coverage, then recall and to-dos, then the
  assistant UI.
- **D8.** No existing prompt is edited. Promises and requests come from a separate to-do pass, and new question types use
  an extended investigator prompt chosen by a code router, so all recorded replies and existing tests stay valid.
- **D9.** The scripted sample day is not changed. It already holds one natural promise ("will check it out"). A request is
  covered by scripted-reply tests, not by the sample.
- **D10.** The sample profile loads from its snapshot, so it has no usage rows until it is used; the model cards say
  "Built from recorded replies" and fill in as the person asks questions. No usage numbers are ever invented or seeded by hand.
- **D11.** The assistant follows the shared selected day; messages remember theirs (see Phase 3).
- **D12.** A failed number check gets one retry, then a deterministic templated answer (see Phase 2).
- **D13.** Times are naive local wall-clock, with no timezone handling.

## Open for the builder

- Exact SQL for the coverage calculation and its behaviour across midnight.
- How the purpose is passed from the callers to the metering client.
- The wording of the new prompt sentence for `requested` and of the date context.
- Chart details inside the approved layout.

## Needs the owner

Nothing blocks the build. One optional step makes the demo richer:

- **Optional live recording of the sample day.** With `MODEL_API_KEY` set in the owner's own shell (never pasted into
  chat or committed), run the to-do pass and the model log through the live model once and rebuild
  `fixtures/profiles/staged.db`. The sample then shows its natural promise as a to-do and real, recorded model usage. Until
  this is done the sample's to-do list shows its empty state and its model cards say "Built from recorded replies".

## Verification

- Backend: a metering test per call kind (text, vision, speech, cache hit, failure); coverage tests (gaps, midnight,
  empty day, several days); to-do tests (state changes, forgetting removes the item, isolation between profiles);
  a test per prompt in the Goals list with scripted model replies, including "nothing found" for to-dos.
- Frontend: `npm run check`; unit tests for the coverage strip geometry, suggestions and the conversation state.
- Browser: sign up, load the sample, see all dashboard cards, open the assistant, ask one prompt of each group, switch to
  the Atlas and see the same conversation, tick a to-do. Light and dark, desktop and phone width.
- Live check with the real model on the sample day for the twelve non-to-do prompts.
