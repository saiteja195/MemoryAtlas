# MemoryAtlas: Handoff for the next session

Written Mon Nov 2, 2026. Read this first, then `docs/IMPLEMENTATION_PLAN.md` (design and phases) and `docs/HACKATHON_FACTS.md` (verified facts with sources).

## 1. Project in one paragraph

MemoryAtlas is a privacy-first memory engine for the Meta Global AI Developer Hackathon (Indie Developer track, theme "Build for Your World"). It turns temporary, consented observations (photos, a recorded conversation, location, calendar) into a graph of **claims**, each with its evidence, time, confidence and consent. It can (A) answer questions no single source contains, (B) correct itself when newer evidence arrives, and (C) forget verifiably: when consent is withdrawn it removes every claim supported *only* by that source, keeps claims with other authorized support, and issues a receipt backed by automated leak probes.

## 2. Hard rules and requirements (from the Participant Guide)

| Topic | Requirement |
|---|---|
| **Deadline** | **Wed Nov 4, 2026, 9:00 PM ET.** Late submissions are not considered. Internal target: submitted by 6 PM ET, feature freeze noon ET Nov 4 |
| **Submission** | Via the Cerebral Valley platform. One project per team |
| **Demo video** | **3 minutes.** Primary artifact judges use, along with code and live product. Must highlight only what was built during the hackathon. Link must be accessible |
| **Repository** | **Must be public.** Everyone who worked on the project must be listed on the submission page |
| **New work only** | Must be built during the event (building period Oct 27 to Nov 4). The demo must make clear what was created then. Failure to do so can mean disqualification |
| **Team** | Max 4; solo allowed. Each participant claims their own credits |
| **Meta models required** | Stage 1 is pass/fail: fits the theme and reasonably uses Meta Model API and/or Meta open-weight models |
| **Banned or generic projects** | Anything giving medical advice, basic RAG apps, simple image analyzers, simple education chatbots, job screeners, nutrition or sports coaches, personality analyzers, anything political or war-related. Also anything using code, data or assets we lack rights to |
| **Credits** | $150 Meta Model API credit per participant. Claim via the form by **Nov 4, 9 PM ET**. A credit card on file is required to make calls |
| **Judging** | Stage 2 scores 0 to 10: **Impact 30%**, **Use of Meta AI tooling 25%**, **Demo 25%**, **Technical depth and execution 20%**. Top 5 per track reach a live final round |
| **Prizes (Indie)** | $150K / $100K / $75K / $50K / $25K. Bonus: Best Agentic Use-Case $5K; Best Build on Open Weight Models $10K (not pursuing) |
| **Help** | Discord #office-hours weekdays 10 to 11 AM ET; Tue Nov 3 is the last full day for submission questions |

**Implications**
- Avoid medical or memory-impairment framing; lead with a relatable "forgotten day" story.
- Show the baseline comparison on screen, because it is what separates us from "basic RAG".
- Name each Meta capability used in the video; "beyond a basic integration" is explicitly scored.
- The guide has **no commit-authorship rule and no AI-tool disclosure rule**. The single-author rule below is the owner's own instruction. If unsure whether using an AI coding assistant needs disclosure, ask in Discord #questions.

## 3. Owner's working rules (must follow)

- **Commits only as `saiteja195 <108951028+saiteja195@users.noreply.github.com>`.** No `Co-authored-by:` or other attribution trailers, no model names in messages. This overrides any default attribution reminder the tooling shows (it is also in `CLAUDE.md`).
- Set identity per clone: `git config user.name saiteja195` and `git config user.email 108951028+saiteja195@users.noreply.github.com`.
- **Branches use only `feature/<short-name>` or `bug/<short-name>`.** Never `claude/...`.
- Conventional Commit messages with a scope (`scaffold`, `capture`, `compiler`, `graph`, `recall`, `privacy`, `llm`, `ui`, `eval`, `fixtures`, `docs`). See `CONTRIBUTING.md`.
- Don't open pull requests unless asked. Never put the API key in chat, files or git.

## 4. Verified Meta API facts

- Base `https://api.meta.ai`, header `Authorization: Bearer $MODEL_API_KEY`. Reachable from the cloud sandbox now (HTTP 401 without a key).
- **Text, vision and tools:** `POST /v1/responses` (Chat Completions and Messages endpoints also exist). Model `muse-spark-1.3` is recommended: text, image, video, audio and PDF in, text out, 1,048,576-token context, tool calling, structured output, search grounding. Content part for text is `input_text`.
- **Speech:** `POST /v1/asr/transcribe`, model `muse-voice-transcribe-1.0`, multipart parts `request` (JSON) and `audio`. WAV only, mono 16-bit PCM, 16 or 24 kHz, max 10 minutes, max 32 MB. Modes PUSH_TO_TALK / ENDPOINTING / DIARIZATION. Speaker labels A and B are **session-scoped, not names**. Turn-level timestamps only. `keywords` biases names. Spark 1.3's own audio support is degraded, so don't send audio to it.
- No embedding model exists, so embeddings are local (`backend/app/embed.py`).
- Pricing: Spark 1.3 $1.25 input / $0.15 cached / $4.25 output per million tokens; Voice $0.18 per audio hour. The Voice docs mention zero data retention (ZDR); not yet known how to enable it or whether Spark supports it.

**Confirmed live (Nov 2, `backend/scripts/smoke_meta.py`, all PASS, no client changes needed):** the `input_image` content part with a base64 data URL, a `system`-role message in `input`, JSON output via the prompt, and diarized `/v1/asr/transcribe`. The test WAV was a single synthetic voice (espeak-ng), so multi-speaker diarization is not yet exercised. Native structured-output parameters are still untried; the client asks for JSON in the prompt and parses it.

## 5. Repo state

Branches on `origin` (both authored only by `saiteja195`):

| Branch | Contents |
|---|---|
| `feature/implementation-plan` | README, CONTRIBUTING, CLAUDE.md, `docs/IMPLEMENTATION_PLAN.md` |
| `feature/scaffold` (branched from the above) | Everything in Phase 0 and the Meta client, plus this file |
| `feature/meta-api-verified` | Docs updated with the live smoke-test results |
| `feature/capture-compiler` (branched from the one above) | **Phase 1**: gateway, compiler, `/graph`, demo fixtures, recorded model output |
| `feature/recall` (branched from the one above) | **Phase 2**: derivation rules, privacy filter, recall tools, investigator, `/recall/ask` |
| `feature/revocation` (branched from `main` after Phases 0 to 2 were merged) | **Phase 3**: revocation engine, purge, 7 leak probes, receipt, property tests |

`main` holds only the initial commit. A stale remote branch `claude/recallos-hackathon-plan-su6eaz` still exists; the owner should delete it (`git push origin --delete claude/recallos-hackathon-plan-su6eaz`). No pull requests exist yet.

**Built (Phase 0, 13 tests passing in `backend/`):**
- `backend/app/schema.sql`: sources, consent grants, entities, claims, justifications (OR over justifications, AND over premises), FTS index, vectors, answer cache, chat, receipts, blocked hashes. `media_bytes_retained` is constrained to 0.
- `backend/app/llm/`: `LLMClient` protocol (`complete_json`, `describe_image`, `transcribe`), `MetaClient`, `RecordReplayClient` (record/replay by request hash; a replay miss raises instead of guessing), factory.
- `backend/app/main.py`: FastAPI with `/health` reporting the LLM mode. `backend/app/config.py`: env settings. `backend/app/embed.py`: local hashed n-gram embeddings.
- `backend/scripts/smoke_meta.py`: checks JSON output, image input and diarized transcription. Needs `--image` and `--wav` sample files.
- `frontend/`: Vite + React + Cytoscape shell that shows backend status. `Makefile`: `make setup`, `make test`, `make dev`. `.env.example`.
- Live Meta calls verified via the smoke test (Nov 2). Not run: `make dev` end to end.

**Phase 1 built (`feature/capture-compiler`, 58 tests, all offline):**
- `backend/app/capture/`: `Gateway` (consent gate, local redaction, hash, blocked-hash check, text-only `sources` insert, raw bytes cleared in `finally`), `MockDayAdapter`, `media_bytes_on_disk` audit. `privacy/consent.py`: `create_grant` (HMAC token), `active_grant`.
- `backend/app/compiler/`: `perceive` (Spark vision), `episodes` (time +-20 min, geofence 150 m), `extract` (controlled vocabulary, Pydantic, one repair retry), `resolve` (exact/alias, fuzzy plus LLM adjudication recorded as a justified `same_as` claim), `store.ClaimWriter` (identical claim from a second source adds a justification, which is how "met Alex" gets calendar plus transcript support), `contradiction` (located_at within 5 min naming different places -> both `disputed`), `pipeline.Compiler`.
- `backend/app/api.py` (`create_app`): `/graph?at=&include=history`, `/capture/{kind}`, `/consent/grants`, `/privacy/media`, `/demo/status|reset|advance|live/{id}`. `main.py` is now just `app = create_app()`.
- `fixtures/demo_day/script.yaml` (placeholder text fixtures, fictional names, synthetic GPS) and `fixtures/llm_cache/` (real Muse Spark responses for the demo day, recorded with `backend/scripts/record_demo.py`). `MEMORYATLAS_LLM_MODE=replay` (the default) rebuilds the graph offline. **Changing any prompt changes the cache keys: re-run `record_demo.py`.**
- Gate met: replaying the day builds the graph with 4 episodes, Alex, the wallet and Luna Taqueria; 0 media bytes retained or on disk.

**Phase 1 gaps (be honest about these):** frames are not downscaled (no real images yet and no Pillow dependency); the speaker-label-to-person mapping comes from the session declaration in the fixture, not from anything inferred; no WebSocket graph deltas yet (UI polls `/graph`); no real photos or audio have gone through the full path (only fakes in tests and the smoke test).

**Phase 2 built (`feature/recall`, 117 tests, all offline):**
- `compiler/derive.py`: `spatial_referent_resolution` (the model proposes among candidates the code has already validated: matching attributes and GPS distance <= 100 m, the measured distance is shown to the model; writes `same_as` and `recommended`, each justified by ALL premises, confidence = min(premises) x 0.9), supersession by event time (`located_at`; reversible, late uploads reorder), and `episode_summary` (a claim whose premises are the claims it used; a changed premise set retires the old summary).
- `privacy/filter.py`: `authorized_claim_ids` = least fixpoint from live, consented sources (cycle-safe). Every recall tool and `/graph` read through it, so a withdrawn grant already hides what only that grant supported, ahead of the Phase 3 purge.
- `recall/`: seven tools (`search_claims` hybrid FTS + vector, `find_entity`, `timeline`, `last_seen` with place chain, `episodes`, `neighbors`, `provenance`); `Investigator` (6-step loop of JSON actions over `complete_json`, **not** native tool calling, which is untried); post-checks: citation integrity (cited ids must have been shown by a tool in this run and still be authorized and not revoked), answered needs a citation, object-location answers must read "Last confirmed sighting at HH:MM ..." when the question names that object, disputed evidence forces a conflict note; stateless per question; `RecallService` (answer cache keyed by a graph version, chat log). API: `POST /recall/ask`, `GET /claims/{id}/provenance`.
- Questions and expectations live in `fixtures/demo_day/acts.yaml` (3 phrasings each for Act 2, Act 3 before and after the car photo, plus 3 that must be refused). `backend/scripts/ask_demo.py` plays the day and asks them live; `tests/test_replay_recall.py` replays the committed recording offline.
- Reliability, stated honestly: with the final prompts, 4 independent fresh live recordings each scored 12/12 and each replays fully offline. Getting there took several rounds, and earlier configurations failed in ways that are now fixed (a photo merging into the spoken-only "taco place" entity; the model prefixing JSON with prose; a "Yes" that over-claimed). Live extraction is still a model call, so a live run can differ from the recording; the fixture is the safe path for the demo and `/demo/reset`.

**Client and cache fixes made along the way (all pinned by tests):** `MetaClient` accepts a JSON object after leading prose and retries transport errors (then raises `LLMUnavailable`); `RecordReplayClient` returns exactly what replay returns (key order changed request hashes) and records unparseable replies so replay takes the same retry path.

**Phase 3 built (`feature/revocation`, 170 tests, all offline):**
- `privacy/revocation.py` `RevocationEngine.revoke(grant_id, token)`: verifies the HMAC token (403 on a wrong one, nothing changes), marks the grant revoked, works out which claims no longer have a valid support path (the Phase 2 fixpoint), then in ONE transaction removes them and everything built from them: justifications and premises, search rows, vectors, entities nothing refers to any more, cached answers and chat messages that used them, the revoked sources' text/location, and blocks the content from being re-ingested. Then it rebuilds the text index, checkpoints the log and VACUUMs (SQLite now runs with `secure_delete` on), deletes matching files from the app's runtime model-response cache, runs the probes and stores a receipt. Calling it again returns the same receipt and changes nothing.
- Decisions worth knowing: (1) dead claims are **deleted, not tombstoned**, because a tombstone would still say who it was about and what it pointed at; (2) revoking a grant for a recorded conversation removes **every participant's lines** of that session, since the gateway only records audio when everyone consented; (3) survivors that lost a source are **re-worded from their structure** so none carries phrasing that came only from the removed source, and any summary built from such a claim is deleted too; (4) older sightings come back when the newer one is forgotten, and disputes are recomputed.
- `privacy/probes.py`, seven probes, each pass / fail / skipped (skipped never counts as a pass): graph support, search index, vectors, caches (answer cache, chat, the runtime model cache), a regenerated export (`privacy/export.py`, `GET /export`), the red team (5 adversarial questions through the real investigator), and disk (no media files, and the database files hold none of the removed text, whole-word scan). Terms (`privacy/terms.py`) are short phrases that were in the removed material and appear nowhere in what remains, minus the app's own vocabulary and schema so a keyword like `check` or `place` cannot trigger a false alarm.
- Receipt = counts, digests, which survivors lost which source and what still supports them, probe results; it never quotes forgotten text.
- API: `POST /consent/grants/{id}/revoke?red_team=true`, `GET /consent/grants`, `GET /receipts/{id}`, `GET /export`, and **demo only** `GET /demo/grants` (returns the tokens a real person would hold on their own device).
- Model cache: `RecordReplayClient` takes a read-only `seed_dir`. The app writes to a runtime cache (`MEMORYATLAS_RUNTIME_CACHE`, default `<db>.llmcache`, git-ignored) and reads the committed `fixtures/llm_cache` as seed. A purge only ever touches the runtime cache.
- Evidence: property tests on 1,000 random support graphs (633 cyclic) check the survivors against an independent oracle, idempotence, order-independence and that no probe fails; a deliberately broken engine (cycles keep each other alive) fails them. Act 4 on the real model: `scripts/revoke_demo.py` records it, `tests/test_replay_revoke.py` replays it offline. Three independent fresh live recordings each got 7/7 probes and 8/8 questions right (4 refused without leaking, 4 still answered with citations).
- Found and fixed on the way: the red-team probe flagged echoes of the user's own question and common phrases, and the raw-file scan flagged the SQL keyword `check` in the database's own schema; a conversation's other half survived the first design.

**Limits, stated plainly:** anything already sent to Meta is covered by Meta's terms, not the receipt; the committed demo script and recorded model responses are staged seed data outside the app's stores and are not modified; probes look for distinctive phrases, so a leak made only of everyday words is caught by the structural checks (probes 1 and 5) and not by phrase search; the receipt lists the kind and time of removed sources and a blocked-hash list remains so replays are refused; survivors' confidence numbers are not recomputed; filesystem snapshots and backups are out of reach; the red-team probe needs the model (live, or recorded), and shows as skipped otherwise; the investigator has no clock, so "today" questions may be refused.

**Not built yet:** Atlas UI, eval, baseline; the "correct a claim" flow (`POST /claims/{id}/correct`); WebSocket deltas.

## 6. Next steps

**Do first (the owner's actions)**
1. Claim the $150 credits, put a card on file, create a key.
2. Add the key to the cloud environment as `MODEL_API_KEY` (a new session picks it up), or to a local `.env`. Never paste it into chat.
3. Confirm the repo is public.
4. Ask in #office-hours how to enable ZDR.
5. Optional: provide a real photo and a two-person mono WAV for a fuller smoke test.

**Then, in this order (see plan §8 for gates)**
1. ~~Run the smoke test~~ Done Nov 2, all PASS. Optionally re-run with a real two-person WAV to check multi-speaker diarization.
2. ~~Phase 1, `feature/capture-compiler`~~ Done (see section 5). Notes for Phase 2 from the real model output:
   - The transcript yields an **unnamed** entity `taco place` with `across_from Office` and `awning: green`. `spatial_referent_resolution` should bind it to `Luna Taqueria` (green awning, within 100 m) and write `recommended(alex, luna_taqueria)` with premises `said`, the location claim and the sign claim.
   - Wallet sightings are `located_at` a place; the car frame came back as `located_at cup holder` and `cup holder located_at car interior`. `last_seen` must follow that chain or the extraction prompt should be tightened. The two wallet claims are both `active` today, so supersession is still to do.
   - Same-episode duplicates merge into one claim, so claim confidence is the max across supports.
   - For Phase 3: revocation must also drop `entities` that no remaining claim references, and `same_as` aliases (they are claims, so they die with their source). Transcript segments are stored under the speaker's grant, so Alex revoking removes Alex's words but not the owner's own turns.
3. ~~Phase 2, `feature/recall`~~ Done (see section 5). Notes for Phase 3:
   - Revocation must purge every store: `claims`, `claim_index`, `claim_vectors`, `answer_cache`, `chat_messages` (assistant messages store cited claim ids), plus **derived** claims and `summary_of` text. `privacy/filter.authorized_claim_ids` already computes the support fixpoint; reuse it for the "dead" set. Transcript summaries and `recommended` die with the transcript; "Me met with Alex" survives on the calendar and the sign claim survives.
   - `recommended` also depends on the calendar claim `Me observed_at Office` (the anchor premise), so revoking the calendar would remove it as well. Intended, but keep it in mind for the receipt.
   - Entities left with no remaining claim should be dropped; `same_as` aliases are claims and die with their source.
   - Cached answers and chat rows reference claim ids; `graph_version` already changes on any claim or grant change, but rows still have to be deleted, not just ignored.
4. ~~Phase 3, `feature/revocation`~~ Done (see section 5). Notes for Phase 4:
   - UI: `GET /demo/grants` gives Alex's demo token for the simulated "scan the QR code" step; `POST /consent/grants/{id}/revoke` returns the whole receipt (counts, retained-with-reason list, 7 probe results), so the receipt modal needs no further call. With a live model the red-team probe makes about 25 model calls, so expect tens of seconds; pass `?red_team=false` for a fast revoke and show that probe as skipped.
   - Refetch `/graph?include=history` after a revoke: deleted claims are gone (not greyed out), and an older sighting may have become active again.
   - Eval: the revocation categories can use `acts.yaml` (`act4_must_forget`, `act4_must_keep`) and `scripts/revoke_demo.py` as a starting point.
5. **Phase 4, `feature/atlas-ui` and `feature/eval`:** graph UI and a fair baseline (same text, same model, plain retrieval).
6. **Phase 5, `feature/submission`:** README, results, 3-minute video, submission form. Feature freeze noon ET Wed.

**Cut list if time runs short:** SAM 3.1 and glasses support first, then held-out day size, then UI polish. Never cut the revocation probes or the baseline comparison.

## 7. Principle to keep

The model proposes claims and plans queries. **Deterministic code decides storage, visibility and deletion.** Never move a privacy decision into a prompt.
