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

**Unverified guesses in `MetaClient` (confirm with `backend/scripts/smoke_meta.py`):** the `input_image` content part with a base64 data URL, a `system`-role message in `input`, and JSON output. The client currently asks for JSON in the prompt and parses it. Native structured-output parameters are not used yet. Fix the client only if live calls show these are wrong.

## 5. Repo state

Branches on `origin` (both authored only by `saiteja195`):

| Branch | Contents |
|---|---|
| `feature/implementation-plan` | README, CONTRIBUTING, CLAUDE.md, `docs/IMPLEMENTATION_PLAN.md` |
| `feature/scaffold` (branched from the above) | Everything in Phase 0 and the Meta client, plus this file |

`main` holds only the initial commit. A stale remote branch `claude/recallos-hackathon-plan-su6eaz` still exists; the owner should delete it (`git push origin --delete claude/recallos-hackathon-plan-su6eaz`). No pull requests exist yet.

**Built (Phase 0, 13 tests passing in `backend/`):**
- `backend/app/schema.sql`: sources, consent grants, entities, claims, justifications (OR over justifications, AND over premises), FTS index, vectors, answer cache, chat, receipts, blocked hashes. `media_bytes_retained` is constrained to 0.
- `backend/app/llm/`: `LLMClient` protocol (`complete_json`, `describe_image`, `transcribe`), `MetaClient`, `RecordReplayClient` (record/replay by request hash; a replay miss raises instead of guessing), factory.
- `backend/app/main.py`: FastAPI with `/health` reporting the LLM mode. `backend/app/config.py`: env settings. `backend/app/embed.py`: local hashed n-gram embeddings.
- `backend/scripts/smoke_meta.py`: checks JSON output, image input and diarized transcription. Needs `--image` and `--wav` sample files.
- `frontend/`: Vite + React + Cytoscape shell that shows backend status. `Makefile`: `make setup`, `make test`, `make dev`. `.env.example`.
- Not run: `make dev` end to end, and any live Meta call (no key was available in the session).

**Not built yet:** capture gateway, compiler, derivation rules, investigator, revocation engine and leak probes, Atlas UI, eval, baseline, demo fixtures.

## 6. Next steps

**Do first (the owner's actions)**
1. Claim the $150 credits, put a card on file, create a key.
2. Add the key to the cloud environment as `MODEL_API_KEY` (a new session picks it up), or to a local `.env`. Never paste it into chat.
3. Confirm the repo is public.
4. Ask in #office-hours how to enable ZDR.
5. Provide two sample files for the smoke test: a photo and a short mono WAV.

**Then, in this order (see plan §8 for gates)**
1. Run `cd backend && python scripts/smoke_meta.py --image <jpg> --wav <wav>`. Fix `MetaClient` for any FAIL.
2. **Phase 1, `feature/capture-compiler`:** demo-day fixtures (plan §5), capture gateway with consent gate, redaction, ephemeral buffer and blocked hashes, compiler (perceive, episode binding, claim extraction, entity resolution, contradiction pass), `/graph` endpoint. Gate: replaying the demo day builds the graph; 0 media bytes on disk. If the owner hasn't recorded real media, build against placeholder text fixtures first.
3. **Phase 2, `feature/recall`:** derivation rules, tool-calling investigator with citation-integrity checks, supersession and disputes.
4. **Phase 3, `feature/revocation`:** grants, HMAC revoke, least-fixpoint recompute, purge across every store, 7 leak probes, receipt, property tests.
5. **Phase 4, `feature/atlas-ui` and `feature/eval`:** graph UI and a fair baseline (same text, same model, plain retrieval).
6. **Phase 5, `feature/submission`:** README, results, 3-minute video, submission form. Feature freeze noon ET Wed.

**Cut list if time runs short:** SAM 3.1 and glasses support first, then held-out day size, then UI polish. Never cut the revocation probes or the baseline comparison.

## 7. Principle to keep

The model proposes claims and plans queries. **Deterministic code decides storage, visibility and deletion.** Never move a privacy decision into a prompt.
