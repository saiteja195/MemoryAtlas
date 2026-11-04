# Upload sources and Atlas chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user add a photo, video, voice recording or text note (uploaded, or captured live with the phone or laptop camera and mic), have Muse read it, answer only the questions Muse cannot settle, and save it to the Atlas; and turn the Ask panel into a conversation.

**Architecture:** A two-phase backend API (`POST /capture/preview` stores nothing and returns a draft with fields and questions; `POST /capture/commit` creates consent grants and feeds the existing `engine.ingest`). Questions and consent rules are built by deterministic code. The frontend adds an Add memory dialog and rewrites `AskPanel` as a chat thread; `/recall/ask` and the graph code are untouched.

**Tech Stack:** FastAPI, Pydantic, SQLite, Pillow (new, EXIF), pytest; React 18, TypeScript, Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-11-03-upload-and-chat-design.md`

## Global Constraints

- Commit only as `saiteja195 <108951028+saiteja195@users.noreply.github.com>`. No `Co-authored-by:` or any attribution trailer. This overrides any default attribution. Branch is `feature/upload-and-chat`.
- Commit messages: Conventional Commits with scope from `capture`, `ui`, `docs` (see `CONTRIBUTING.md`).
- Strict scope: do not edit `GraphView.tsx`, `graphStyle.ts`, `graph.ts`, `Timeline.tsx`, `Dashboard.tsx`, `ConsentPanel.tsx`, `ReceiptDialog.tsx`, the compiler, `recall/`, or `evaluation/`.
- Privacy decisions (who consented, what is stored) live in code, never in a prompt. Raw bytes are never persisted or logged; `media_bytes_retained` stays 0.
- Video is decoded in the browser into at most 4 JPEG frames plus a WAV audio track; the backend never decodes video. Muse is only reached through `LLMClient` (`describe_image`, `transcribe`, `complete_json`). No new Muse methods.
- Upload limits: image 10 MB, audio 32 MB, text note 5000 characters, video preview at most 4 frames (each 10 MB) plus one audio track. Browser capture caps: voice 600 s, video 60 s. Audio must be mono 16-bit PCM WAV at 16000 or 24000 Hz, at most 600 seconds.
- Drafts live in memory for 900 seconds and hold text only.
- Backend tests: `cd backend && python -m pytest -q`. Frontend: `cd frontend && npm run check`. Both stay green at every commit.
- Camera and microphone permission is requested only when the user presses a capture button, never on page load; all streams are stopped when capture ends or the dialog closes. Capture needs `window.isSecureContext`.
- Use the UI tokens already in `frontend/src/styles.css` (`--surface`, `--accent`, `--ok`, `--warn`, ...). No new colors, no new frontend dependencies.

## Review Focus

1. A photo with no EXIF and no GPS (screenshot, stripped by a messenger) must produce `ask` questions for when and where. It must never invent a time or place.
2. Bytes that are not an image, or audio that is not mono 16-bit WAV (for example MP3), must return a clear 4xx, never a 500.
3. Saving the same draft twice (double click) must store once; the second call gets 404, with no duplicate claims.
4. An oversize upload must be refused with 413 before the base64 is decoded.
5. A person answering "no" to consent must result in nothing stored and no grant created, with the reason shown to the user.

---

### Task 1: Media checks and EXIF reader

**Files:**
- Create: `backend/app/capture/media_info.py`
- Create: `backend/tests/test_media_info.py`
- Modify: `backend/pyproject.toml` (add `"pillow>=10"` to `dependencies`)

**Interfaces:**
- Produces:
  - `class MediaError(ValueError)`
  - `@dataclass(frozen=True) class ExifInfo: taken_at: str | None; lat: float | None; lon: float | None` (`taken_at` is naive ISO `YYYY-MM-DDTHH:MM:SS`)
  - `read_exif(image: bytes) -> ExifInfo` never raises; garbage gives all-None
  - `check_image(image: bytes) -> None` raises `MediaError` unless Pillow can open it as JPEG or PNG
  - `check_wav(audio: bytes) -> float` returns duration in seconds; raises `MediaError` for anything but mono 16-bit PCM WAV at 16000/24000 Hz and at most 600 s

- [ ] **Step 1: Write failing tests** in `test_media_info.py`: `test_read_exif_time_and_gps` (build a JPEG with Pillow `Image.new` plus an `Exif` carrying DateTimeOriginal `2026:10:29 12:42:10` and GPS 37.7749 N / 122.4194 W; assert `taken_at == "2026-10-29T12:42:10"` and lat/lon within 1e-3, lon negative), `test_read_exif_missing_is_all_none` (plain PNG), `test_read_exif_garbage_never_raises` (`b"nope"`), `test_check_image_rejects_non_image`, `test_check_wav_accepts_mono_16k` (write 1 s of silence with stdlib `wave`; returns about 1.0), `test_check_wav_rejects_stereo`, `test_check_wav_rejects_mp3_bytes`, `test_check_wav_rejects_over_ten_minutes` (header-only is fine: use a WAV whose frame count implies 601 s).
- [ ] **Step 2:** Run `cd backend && python -m pytest tests/test_media_info.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement with Pillow (`Image.open(BytesIO(...))`, `getexif()`, IFD `0x8769` tag `36867`, GPS IFD `0x8825`; S and W refs negate) and stdlib `wave`. Add `pillow>=10` to `pyproject.toml` and run `pip install -e ".[dev]"` in `backend/.venv`.
- [ ] **Step 4:** Rerun the file. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(capture): read EXIF and validate uploaded media`.

---

### Task 2: Draft model, question builder, draft store

**Files:**
- Create: `backend/app/capture/draft.py`
- Create: `backend/tests/test_draft.py`

**Interfaces:**
- Consumes: `ExifInfo` (Task 1); `Perception` / `parse_perception` from `app/compiler/perceive.py`.
- Produces (Pydantic models, all JSON-serialisable):
  - `DraftField(key: Literal["when","where","doing","people"], value: str | None, source: Literal["exif","file","image","voice","note","user"] | None, confidence: Literal["sure","check","ask"])`
  - `Question(id: str, field: str, prompt: str, kind: Literal["datetime","text","choice","consent"], options: list[str] = [], ref: str | None = None)`
  - `Draft(draft_id: str, kind: Literal["frame","audio","note","video"], fields: list[DraftField], questions: list[Question], captured_at: str | None, lat: float | None, lon: float | None, place_name: str | None, text: str | None, perceptions: list[dict], frame_offsets_ms: list[int], turns: list[dict] | None, speakers: list[str])` (a photo is `kind="frame"` with one perception and offset `[0]`; a video has up to 4 of each)
  - `build_draft(kind: str, *, perceptions: list[dict] | None = None, frame_offsets_ms: list[int] | None = None, turns: list[dict] | None = None, text: str | None = None, exif: ExifInfo | None = None, file_modified_at: str | None = None) -> Draft` (draft_id left `""`)
  - `class DraftStore: __init__(ttl_seconds: float = 900, clock: Callable[[], float] = time.monotonic)`, `put(draft: Draft) -> Draft` (assigns `draft_id` as `uuid4().hex`), `take(draft_id: str) -> Draft` (removes it; raises `KeyError` if unknown or expired)

Rules `build_draft` must implement (question ids are fixed strings):
- `when`: EXIF time gives `source="exif", confidence="sure"`; else `file_modified_at` gives `source="file", confidence="check"` and `captured_at` set; else `confidence="ask"` and question `id="when", kind="datetime"`.
- `where` (frame and video): first non-empty `ocr_text` across all perceptions gives `value=<that text>, source="image", confidence="check"`, `place_name` set, and question `id="where_confirm", kind="choice", options=["Yes","Different place"]`; no OCR gives `confidence="ask"` and question `id="where", kind="text"` (GPS, when present, is kept in `lat`/`lon` regardless). Audio and note drafts have no `where` question.
- `doing`: frame and video use the first non-empty `caption` (`source="image", confidence="sure"`); note uses its text (`source="note"`); audio has no `doing` field.
- `people`: for audio, `speakers` is the sorted distinct non-null `speaker` labels. With 2 or more speakers add question `id="owner_speaker", kind="choice", options=speakers`, and one `kind="consent"` question per speaker with `id=f"person_{label}"`, `ref=label`. With one speaker, no people questions. For frames and videos, count objects in the perception with the most people whose lowercase label contains `person`, `people`, `man`, `woman`, `child`, `boy` or `girl` (capped at 3); each gives a `kind="consent"` question `id=f"person_visible{n}"`, `ref=f"visible{n}"` (n from 1). Notes have none.

- [ ] **Step 1: Write failing tests** `test_draft.py`: `test_photo_with_exif_is_sure_and_asks_only_where`, `test_photo_without_exif_or_file_time_asks_when` (assert `Question.id == "when"`, `captured_at is None`), `test_file_time_is_marked_check`, `test_ocr_text_becomes_confirmable_place`, `test_no_ocr_asks_where_even_with_gps` (lat/lon retained), `test_two_speakers_ask_owner_and_consent_for_each`, `test_one_speaker_asks_nothing_about_people`, `test_visible_person_asks_consent`, `test_note_has_doing_and_no_people`, `test_video_uses_ocr_from_any_frame_and_max_people`, `test_video_with_audio_asks_owner_speaker`, `test_store_take_removes_draft`, `test_store_expires` (inject a fake clock; 901 s later `take` raises `KeyError`), `test_store_unknown_id_raises`.
- [ ] **Step 2:** Run `python -m pytest tests/test_draft.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement per the rules above.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(capture): draft model with deterministic questions`.

---

### Task 3: `POST /capture/preview`

**Files:**
- Modify: `backend/app/api.py` (new `PreviewBody`, new route, `DraftStore` created in `create_app` and put on `app.state.drafts`)
- Create: `backend/tests/test_upload_api.py`

**Interfaces:**
- Consumes: `read_exif`, `check_image`, `check_wav`, `MediaError` (Task 1); `build_draft`, `DraftStore` (Task 2); `perceive_frame` and `llm.transcribe`.
- Produces: `POST /capture/preview` with body `PreviewBody(kind: Literal["frame","audio","note","video"], data_b64: str | None = None, frames_b64: list[str] = [], frame_offsets_ms: list[int] = [], audio_b64: str | None = None, text: str | None = None, file_modified_at: str | None = None)` (`frame`: `data_b64` is the image; `audio`: `data_b64` is the WAV; `video`: 1 to 4 `frames_b64` with matching `frame_offsets_ms`, and an optional `audio_b64` WAV; more than 4 frames or mismatched lengths is 422), returning `Draft` JSON. Errors: 413 oversize (checked on `len(data_b64)` before decoding, using base64 expansion of the limits), 415 `MediaError` text, 422 missing data or note over 5000 characters, 503 `LLMUnavailable`. The route registers before `/capture/{kind}` so `preview` is not read as a kind. Nothing is written to the database. Image bytes go to `perceive_frame(llm, image)`; audio to `llm.transcribe(audio, None)`; both byte strings are dropped after the call.

- [ ] **Step 1: Write failing tests** in `test_upload_api.py` using `TestClient(create_app(Settings(db_path=":memory:", llm_mode="live"), FakeLLM()))` (pattern in `tests/test_expiry.py`): `test_preview_photo_returns_fields_and_no_sources` (assert `sources` row count is 0 afterwards and `fake.described` has one entry), `test_preview_photo_without_exif_asks_when` (Review Focus 1), `test_preview_rejects_non_image_with_415` and `test_preview_rejects_mp3_as_audio_with_415` (Review Focus 2), `test_preview_oversize_413_before_decode` (10 MB + 1 as a string of `"A"` padded; assert `fake.described == []`), `test_preview_note_returns_doing`, `test_preview_video_describes_each_frame_and_transcribes_audio` (3 frames, WAV; `len(fake.described) == 3`, one transcribe), `test_preview_video_without_audio_has_no_speakers`, `test_preview_video_over_four_frames_is_422`, `test_preview_replay_unrecorded_is_503` (client whose `describe_image` raises `LLMUnavailable("no recorded response")`).
- [ ] **Step 2:** Run `python -m pytest tests/test_upload_api.py -q`. Expected: FAIL (404).
- [ ] **Step 3:** Implement the route in `create_app`, next to the existing `capture` route.
- [ ] **Step 4:** Rerun the file plus `python -m pytest -q`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(capture): preview endpoint that reads an upload without storing it`.

---

### Task 4: `POST /capture/commit`

**Files:**
- Modify: `backend/app/api.py` (new bodies and route)
- Modify: `backend/tests/test_upload_api.py`

**Interfaces:**
- Consumes: `app.state.drafts`, `Draft` (Tasks 2-3); `active_grant`, `create_grant` from `app/privacy/consent.py`; `engine.ingest`; `engine.gateway.owner`.
- Produces: `POST /capture/commit` with `CommitBody(draft_id: str, answers: Answers)`, where `Answers(when: str | None = None, where: str | None = None, owner_speaker: str | None = None, people: list[PersonAnswer] = [])` and `PersonAnswer(ref: str, name: str | None = None, consented: bool)`. Returns `{"session_id": str, "results": [{status, reason, source_id, claims, compile_rejected}], "grants": [{"person": str, "grant_id": str, "revocation_token": str}]}` (same `results` shape as `/capture/{kind}`).

Rules (all deterministic):
- `draft_id` unknown or expired: 404 `"draft expired or unknown"`. The draft is taken (removed) before work starts, so a second commit gets 404.
- `captured_at = draft.captured_at or answers.when`; neither: 422. `answers.when` must parse with `datetime.fromisoformat` (422 otherwise). `place_name = answers.where or draft.place_name`.
- `session_id = "upload-" + captured_at[:10]`. Owner grant: `active_grant(conn, owner, session_id)` or else `create_grant(...)` with `settings.revocation_secret`; include it in `grants`.
- Audio with 2 or more speakers: `answers.owner_speaker` must be one of `draft.speakers` (422). Every other speaker needs a `PersonAnswer` (422 if missing, or if `consented` and `name` empty). Person id is `slug(name)` (lowercase, runs of non-alphanumerics become `-`); a slug equal to the owner id is 422.
- Any non-owner person (audio speaker or frame visible person) with `consented == false`: return `results=[{"status":"rejected","reason":"no_consent",...}]`, create no grants at all (including the owner grant), ingest nothing.
- Otherwise create a grant per consenting audio person and build the `RawCapture`: frame and video ingest one `RawCapture(kind="frame")` per perception with `captured_at` shifted by its offset, using `lat`/`lon` and `place_name`; a video with `turns` also ingests the audio capture as below; audio uses `turns=draft.turns`, `participants=[person ids]`, `speaker_map={owner_speaker: owner, <label>: person_id}`; note uses `text`. Call `engine.ingest`; `LLMUnavailable` becomes 503. Do not call Muse for perception or transcription again.

- [ ] **Step 1: Write failing tests** (same file): `test_commit_photo_ingests_and_creates_owner_grant` (assert one source row, `media_bytes_retained == 0`, claims > 0, owner grant present), `test_commit_twice_second_is_404` and assert source count stays 1 (Review Focus 3), `test_commit_missing_when_is_422`, `test_commit_audio_creates_grant_for_consenting_person` (two speakers; names `Alex`; assert grant `alex` exists and `fake.transcribed` has exactly one entry across preview+commit), `test_commit_audio_without_owner_speaker_is_422`, `test_commit_person_declines_stores_nothing_and_creates_no_grant` (Review Focus 5; assert zero sources and zero `consent_grants` rows), `test_commit_visible_person_declines_rejects_photo`, `test_commit_duplicate_photo_reports_duplicate`, `test_commit_video_ingests_frames_and_audio` (3 frames, 2 speakers; results include 3 frame results and the audio results), `test_commit_video_person_declines_stores_nothing`, `test_commit_uses_answered_place` (answers `where="Mikado Ramen"` appears in the stored source text as `Location: Mikado Ramen`).
- [ ] **Step 2:** Run the file. Expected: FAIL.
- [ ] **Step 3:** Implement the route.
- [ ] **Step 4:** Run `python -m pytest -q`. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat(capture): commit endpoint with deterministic consent checks`.

---

### Task 5: Frontend API types and pure Add-memory helpers

**Files:**
- Modify: `frontend/src/api/types.ts` (add `Draft`, `DraftField`, `Question`, `Answers`, `PersonAnswer`, `CommitResult`, mirroring Tasks 2 and 4 JSON)
- Modify: `frontend/src/api/client.ts` (`api.previewCapture(body)`, `api.commitCapture(body)`; both `post<...>`)
- Create: `frontend/src/utils/addMemory.ts`
- Create: `frontend/src/utils/addMemory.test.ts`

**Interfaces:**
- Produces in `addMemory.ts`:
  - `classifyFile(file: { name: string; type: string }): { kind: "frame" | "audio" | "video" } | { unsupported: string }` (image/jpeg and image/png give `frame`; any `audio/*` or `.wav`/`.m4a`/`.webm`/`.mp3` gives `audio` (the browser converts to WAV in Task 10); `video/*` gives `video`; anything else unsupported with a message naming the type)
  - `type AnswerState = { when?: string; where?: string | null; ownerSpeaker?: string; people: Record<string, { name: string; consented: boolean | null }> }`
  - `unanswered(draft: Draft, a: AnswerState): string[]` returns ids of questions still open, treating `where_confirm` as answered when `where === null` (accepted) or non-empty text; the owner's own `person_<label>` question is never open
  - `toCommitBody(draft: Draft, a: AnswerState): { draft_id: string; answers: Answers }`
  - `maxBytes(kind: "frame" | "audio" | "video"): number` (10 MB, 32 MB, 200 MB for the source video file before frame extraction)

- [ ] **Step 1: Write failing tests** `addMemory.test.ts`: `classifyFile` for jpg, png, wav, m4a (audio), mp4 and webm (video), pdf (unsupported), `unanswered` lists `when` for a draft with a `when` question and clears it once answered, `unanswered_hides_owner_consent_question`, `unanswered_requires_consent_choice_and_name_when_consenting`, `toCommitBody_maps_people_and_omits_unset_fields`.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/utils/addMemory.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement types, client methods and helpers.
- [ ] **Step 4:** Run `npm run check`. Expected: type-check and all tests PASS.
- [ ] **Step 5:** Commit: `feat(ui): API types and helpers for adding a memory`.

---

### Task 6: Add memory dialog

**Files:**
- Create: `frontend/src/components/AddMemory.tsx`
- Modify: `frontend/src/components/Header.tsx` (new prop `onAdd: () => void`; one `btn` labelled "Add memory" in the last `group`, before "How it works")
- Modify: `frontend/src/App.tsx` (state `adding`; render `<AddMemory open={adding} mode={atlas.health?.llm_mode} onClose=... onSaved={() => atlas.refresh()} />`; pass `onAdd` to `Header`)
- Modify: `frontend/src/styles.css` (append `.add-*` rules using existing tokens; layout matches the approved mockup `upload-flow-v2`)

**Interfaces:**
- Consumes: `api.previewCapture`, `api.commitCapture`, `classifyFile`, `unanswered`, `toCommitBody`, `maxBytes` (Task 5); `Dialog` component.
- Produces: `AddMemory({ open, mode, onClose, onSaved }: { open: boolean; mode: LlmMode | undefined; onClose: () => void; onSaved: () => void })`.

Behaviour: one `Dialog` with three states in order. (1) Add: drop zone with click-to-browse (`accept="image/jpeg,image/png,audio/*,video/*"` plus drag and drop), a note textarea (max 5000), and an "Analyze with Muse" button. Unsupported files show `classifyFile`'s message inline and are not added. Audio and video files go through the converters from Task 10 before `previewCapture`. The dialog also hosts the capture buttons from Task 11 (the Add step shows Take photo, Record voice, Record video above the drop zone). In replay mode the zone is disabled with the text "Adding memories needs live Muse. Run with a key (see docs/LOCAL_SETUP.md)". (2) Reading: progress indicator while `previewCapture` runs; the file is read to base64 with `FileReader`, `lastModified` sent as `file_modified_at`; errors (4xx/5xx) show the server message with a Try again button. (3) Review: found fields (`when`, `where`, `doing`, `people`) with a Sure / Check / Ask badge and the source, then the open questions as cards (pill buttons for choices, text input for text, `datetime-local` for datetime, name field plus Yes/No for consent). "Save to Atlas" is disabled while `unanswered(...)` is non-empty. A "No" consent answer shows an inline warning "Saving will drop this memory: someone in it did not agree." Success shows "Saved N claims" (or the rejection reason from `results`) and calls `onSaved`. Closing at any step discards the state.

- [ ] **Step 1:** Implement the component, header button, App wiring and CSS.
- [ ] **Step 2:** Run `cd frontend && npm run check`. Expected: PASS.
- [ ] **Step 3:** Rebuild and look at it: `docker compose up --build -d`, open http://localhost:8080, press Add memory, drop a JPEG; check it at 375 px width and in dark mode. Expected: dialog usable at both widths, keyboard focus trapped, Esc closes.
- [ ] **Step 4:** Commit: `feat(ui): add memory dialog with Muse-read draft and questions`.

---

### Task 7: Chat helpers

**Files:**
- Create: `frontend/src/utils/chat.ts`
- Create: `frontend/src/utils/chat.test.ts`

**Interfaces:**
- Produces:
  - `oldestFirst<T>(items: T[]): T[]` (returns a reversed copy; `App` stores newest first)
  - `PHASES: readonly ["Understanding the question", "Searching your memories", "Checking the answer"]`
  - `phaseAt(elapsedMs: number): 0 | 1 | 2` (below 1500 gives 0; below 4000 gives 1; else 2)
  - `followUps(asked: string[], groups: PromptGroup[], max?: number): string[]` (default `max` 3; first unasked prompts in group order, case-insensitive compare, never a question already asked)

- [ ] **Step 1: Write failing tests** `chat.test.ts`: `oldestFirst_does_not_mutate`, `phaseAt` boundaries 0, 1499, 1500, 3999, 4000, `followUps_skips_asked_case_insensitively`, `followUps_respects_max`, `followUps_empty_when_all_asked`.
- [ ] **Step 2:** Run `npx vitest run src/utils/chat.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement. Import `PromptGroup` from `./suggest`.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ui): pure helpers for the chat thread`.

---

### Task 8: Chat-style `AskPanel`

**Files:**
- Modify: `frontend/src/components/AskPanel.tsx` (same `Props` and `QA` export, so `App.tsx` does not change)
- Modify: `frontend/src/styles.css` (replace the `.ask-form`, `.thread`, `.qa` rules with chat rules; keep the other panel styles)

**Interfaces:**
- Consumes: `oldestFirst`, `PHASES`, `phaseAt`, `followUps` (Task 7); existing `EvidenceChip`, `suggest`, `isKnown`, `clock`.
- Produces: `AskPanel` with unchanged props `{ qas, asking, forgotten, mode, onAsk, onCite, onWhy }`.

Behaviour (matches the approved chat mockup): thread of bubbles, user questions on the right in the accent color, answers on the left; thread oldest first and scrolled to the bottom when `qas` or `asking` changes (instant, not smooth, when `prefersReducedMotion()`); while `asking`, a steps list shows `PHASES` with earlier ones ticked, driven by a timer from when `asking` became true and cleared when it ends; the composer is pinned at the bottom (pill input plus round send button, Enter submits, disabled while asking or under 3 characters). Each answer bubble keeps the existing status chip, `uncertainty_note`, citation chips (`onCite`) and "Why? Show the evidence" (`onWhy`), and the "Checked and corrected" chip. The existing graph focus on citation stays in `App.tsx`. After the latest answer, show up to 3 `followUps(asked, groups)` pills (hidden while asking). Empty state: heading "What do you want to understand?", the first four prompts across `groups` as starter buttons. Keep the replay-mode note and the `NotRecorded` and nearby-suggestion behaviour, restyled as bubbles. At 640 px and below the panel fills the width with 16 px gutters and no horizontal scroll. The panel stays inside the existing `side` aside and tab; it is not moved.

- [ ] **Step 1:** Implement the component and CSS.
- [ ] **Step 2:** Run `cd frontend && npm run check`. Expected: PASS.
- [ ] **Step 3:** Rebuild and exercise: `docker compose up --build -d`; open the Atlas page, Ask tab; ask a question in live mode; confirm steps show then resolve, the answer appears as a bubble, citations still focus the graph, follow-ups work, light and dark both read well, and 375 px width has no horizontal scroll.
- [ ] **Step 4:** Commit: `feat(ui): chat-style Ask panel`.

---

### Task 9: Docs and end-to-end check (run last, after Task 12)

**Files:**
- Modify: `docs/LOCAL_SETUP.md` (new section "Adding your own memories": what is supported, how camera and mic permissions work, why `https` is needed on a phone, needs live mode, how consent questions work, and the `public` profile steps from Task 12)
- Modify: `README.md` (one line linking to that section)

- [ ] **Step 1:** Write the docs section.
- [ ] **Step 2:** With `docker compose up --build -d` and live mode, upload a real photo (with EXIF), a short two-person recording and a text note, then capture a photo, a voice note and a 10-second video with the camera and mic on the laptop (localhost is a secure context). Answer the questions. Expected: each appears in the Atlas as new claims with provenance, `Raw media kept` stays 0 B, and declining a consent answer stores nothing.
- [ ] **Step 3:** Run `cd backend && python -m pytest -q` and `cd frontend && npm run check`. Expected: PASS.
- [ ] **Step 4:** Run `git log --format='%an <%ae> | %cn <%ce>' | sort -u` and `git log --format=%B | grep -i 'co-authored' || echo clean`. Expected: only `saiteja195` and `clean`.
- [ ] **Step 5:** Commit: `docs: adding your own memories`. Open a PR from `feature/upload-and-chat` (the PR body gets no attribution line).

---

### Task 10: Browser media converters (pure where possible)

Run after Task 6. Needed by Tasks 6 and 11.

**Files:**
- Create: `frontend/src/utils/wav.ts`
- Create: `frontend/src/utils/wav.test.ts`
- Create: `frontend/src/utils/media.ts` (DOM-dependent glue, not unit tested)

**Interfaces:**
- Produces in `wav.ts` (pure):
  - `downmixToMono(channels: Float32Array[]): Float32Array`
  - `resampleLinear(samples: Float32Array, fromRate: number, toRate: number): Float32Array`
  - `encodeWav16(samples: Float32Array, sampleRate: number): Uint8Array` (44-byte PCM header, mono, 16-bit little endian, clipping to [-1, 1])
  - `frameOffsets(durationMs: number, count: number): number[]` (evenly spaced inside the clip, never 0 and never the end; for `count` 1 the midpoint)
- Produces in `media.ts`:
  - `async toWav16k(blob: Blob): Promise<Uint8Array>` (decodes with `AudioContext.decodeAudioData`, then `downmixToMono`, `resampleLinear` to 16000, `encodeWav16`; throws a readable `Error` if the browser cannot decode the format)
  - `async extractVideo(blob: Blob, maxFrames = 4): Promise<{ frames: Blob[]; offsetsMs: number[]; audio: Uint8Array | null; durationMs: number }>` (plays the blob in an off-screen `<video>`, seeks to `frameOffsets`, draws each to a canvas scaled so the long side is at most 1280 px, exports JPEG at quality 0.85; audio via `toWav16k` on the same blob, or `null` if the track cannot be decoded)
  - `toBase64(data: Blob | Uint8Array): Promise<string>`

- [ ] **Step 1: Write failing tests** `wav.test.ts`: `encodeWav16_header_is_valid_mono_16bit` (assert the bytes `RIFF`, `WAVE`, format 1, channels 1, rate 16000, bits 16, data length = samples * 2), `encodeWav16_clips_out_of_range`, `downmixToMono_averages_channels`, `resampleLinear_halves_length_for_double_rate`, `resampleLinear_same_rate_is_identity`, `frameOffsets_are_inside_clip_and_sorted`, `frameOffsets_single_is_midpoint`.
- [ ] **Step 2:** Run `cd frontend && npx vitest run src/utils/wav.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `wav.ts`, then `media.ts`.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ui): browser-side WAV encoding and video frame extraction`.

---

### Task 11: Camera and microphone capture UI

Run after Task 10.

**Files:**
- Create: `frontend/src/components/CaptureButtons.tsx`
- Create: `frontend/src/utils/capture.ts`
- Create: `frontend/src/utils/capture.test.ts`
- Modify: `frontend/src/components/AddMemory.tsx` (mount `CaptureButtons`; feed its result into the same state as a picked file)
- Modify: `frontend/src/styles.css` (`.capture-*` rules)

**Interfaces:**
- Produces in `capture.ts` (pure):
  - `type CaptureKind = "photo" | "voice" | "video"`
  - `captureSupport(env: { isSecureContext: boolean; hasMediaDevices: boolean; hasMediaRecorder: boolean }): { ok: true } | { ok: false; reason: "insecure" | "no-devices" | "no-recorder"; message: string }` (the insecure message says camera and microphone need an https page or localhost and names the current protocol-agnostic fix: "open this site over https")
  - `describeMediaError(name: string, kind: CaptureKind): string` mapping `NotAllowedError` (permission denied: how to re-enable it in browser site settings), `NotFoundError` (no camera or mic found), `NotReadableError` (in use by another app), `OverconstrainedError`/`AbortError`/other (generic retry text) to plain sentences
  - `MAX_SECONDS: Record<"voice" | "video", number>` = voice 600, video 60
  - `pickRecorderMime(isSupported: (m: string) => boolean, kind: "voice" | "video"): string | undefined` (first supported of voice `audio/webm;codecs=opus`, `audio/mp4`, `audio/webm`; video `video/webm;codecs=vp9,opus`, `video/webm`, `video/mp4`)
- Produces: `CaptureButtons({ disabled, onCaptured }: { disabled: boolean; onCaptured: (c: { kind: CaptureKind; blob: Blob; name: string }) => void })`

Behaviour: three buttons (Take photo, Record voice, Record video). If `captureSupport` is not ok, they render disabled with the `message` under them, and the file picker (with `capture` hints: `accept="image/*" capture="environment"` for photo, `accept="video/*" capture` for video) remains the way to add media. Pressing a button calls `getUserMedia` for that kind only (photo and video: `{ video: { facingMode: "environment" }, audio: kind === "video" }`; voice: `{ audio: true }`) and opens an inline capture surface: live `<video>` preview (muted, `playsInline`) for photo and video, a level indicator and elapsed time for voice. Photo: a Capture button draws the current frame to a canvas and exports JPEG; a Flip camera control toggles `facingMode`. Voice and video: Start/Stop with a visible timer, auto-stop at `MAX_SECONDS`, using `MediaRecorder` with `pickRecorderMime`. Every path (stop, cancel, error, unmount, dialog close) stops all tracks. After capture the surface shows a preview (image, `<audio controls>`, or `<video controls>`) with Retake and Use this. Permission errors show `describeMediaError` text inline with a Try again button, never an `alert`.

- [ ] **Step 1: Write failing tests** `capture.test.ts`: `captureSupport_insecure_context_explains_https`, `captureSupport_ok_when_all_present`, `captureSupport_no_devices`, `describeMediaError_denied_mentions_site_settings`, `describeMediaError_not_found_names_the_device_kind`, `describeMediaError_unknown_is_generic`, `pickRecorderMime_prefers_first_supported`, `pickRecorderMime_returns_undefined_when_none`, `MAX_SECONDS_values`.
- [ ] **Step 2:** Run `npx vitest run src/utils/capture.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement `capture.ts`, `CaptureButtons.tsx`, the `AddMemory` integration and CSS.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Rebuild (`docker compose up --build -d`) and test on the laptop at `http://localhost:8080`: allow then deny the permission prompt for each of photo, voice and video; confirm the camera indicator turns off after capture, after cancel and after closing the dialog. Confirm that when opened over plain `http` from another host the buttons are disabled with the https explanation.
- [ ] **Step 6:** Commit: `feat(ui): take photos and record voice and video from the device`.

---

### Task 12: Public HTTPS profile for the VM

Run after Task 11.

**Files:**
- Create: `deploy/Caddyfile`
- Modify: `compose.yaml` (new `proxy` service in profile `public`; `web` keeps its localhost port only in the default profile)
- Modify: `.env.example` (document `PUBLIC_HOST`, `BASIC_AUTH_USER`, `BASIC_AUTH_HASH`)
- Create: `docs/DEPLOY.md`

**Interfaces:**
- Produces: `docker compose --profile public up -d --build` serves `https://$PUBLIC_HOST` (a DuckDNS name pointing at the VM) with an automatic Let's Encrypt certificate, gated by HTTP basic auth on every path, proxying to `web:80`. Ports 80 and 443 are published by `proxy` only; `web` publishes no host port when `proxy` runs.

Requirements for `Caddyfile`: site address `{$PUBLIC_HOST}`; `basicauth` with `{$BASIC_AUTH_USER}` and `{$BASIC_AUTH_HASH}` applied to all paths; `request_body { max_size 250MB }`; `reverse_proxy web:80`; `header` sets `Strict-Transport-Security`, `X-Content-Type-Options nosniff` and `Permissions-Policy "camera=(self), microphone=(self)"`. `docs/DEPLOY.md` covers: point the DuckDNS name at the VM IP, open ports 80/443, generate the hash with `docker run --rm caddy caddy hash-password`, set `MEMORYATLAS_LLM_MODE=live`, `MODEL_API_KEY` and a strong `MEMORYATLAS_SECRET`, start, and the warning that `/demo/*` endpoints exist and are protected only by the basic auth.

- [ ] **Step 1:** Write the files. Keep the existing `web` `ports:` line on `127.0.0.1` for the default profile; use a compose override pattern so the `public` profile does not publish it (for example, move `ports` to a separate `web-local` override or document `docker compose -f compose.yaml -f deploy/compose.public.yaml`). Pick the override-file approach.
- [ ] **Step 2:** Validate: `docker compose -f compose.yaml -f deploy/compose.public.yaml --profile public config` exits 0 with dummy env values; the default `docker compose config` is unchanged and still lists only `127.0.0.1:8080`.
- [ ] **Step 3:** If a Caddy image can run locally, start it with `PUBLIC_HOST=localhost` and check `curl -k -o /dev/null -w "%{http_code}" https://localhost` returns 401 without credentials and 200 with them.
- [ ] **Step 4:** Commit: `docs: opt-in public HTTPS deployment behind basic auth`.


## Execution order

1, 2, 3, 4, 5, 6, 10, 11, 7, 8, 12, 9. Task numbers are labels, not order.
