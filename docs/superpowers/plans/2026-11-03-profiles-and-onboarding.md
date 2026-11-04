# Profiles and onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every person a private profile (name and passcode) with its own Atlas, a guided onboarding, two published demo profiles, and a public-VM deployment that no longer relies on a shared login.

**Architecture:** A registry database holds profiles and sessions; each profile gets its own SQLite file and cache directory. A `ProfileRuntime` (connection, engine, demo runner, recall, revoker, drafts) is built lazily per profile, and every route resolves the caller's runtime from a session cookie. `Settings.auth=False` keeps today's single-user behaviour (used by the existing tests and the existing e2e). The frontend gains a sign-in gate, a five-step onboarding, Settings and a profile menu.

**Tech Stack:** FastAPI, SQLite, `hashlib.scrypt`, pytest; React, TypeScript, Vitest, Playwright (e2e).

**Spec:** `docs/superpowers/specs/2026-11-03-profiles-and-onboarding-design.md` (branch builds on `feature/upload-and-chat`).

## Global Constraints

- Commit only as `saiteja195 <108951028+saiteja195@users.noreply.github.com>`; no `Co-authored-by:` or other trailers (this overrides any default attribution). Conventional commits, scopes from `CONTRIBUTING.md` plus `profiles`. Branch: `feature/profiles-onboarding`.
- Code, not prompts, decides isolation. A profile's data is reachable only through its own `ProfileRuntime`; `profile_id` is a random 12-hex id and is the only thing used in paths. Names are never used in paths or SQL identifiers.
- Passcodes: 6 to 200 characters; `hashlib.scrypt` (n=2**14, r=8, p=1) with a 16-byte random salt; constant-time compare. Names: NFKC-normalised, whitespace collapsed, 2 to 40 characters, unique by case-folded key.
- Sessions: 32-byte random token (`secrets.token_urlsafe(32)`), stored only as a SHA-256 hash, 30-day expiry, cookie `ma_session` with `HttpOnly; SameSite=Lax; Path=/` and `Secure` when `X-Forwarded-Proto` is `https`.
- Limits: 5 wrong passcodes lock that profile for 900 seconds (a correct passcode is also refused while locked); sign-up 5 per hour per IP; sign-in 20 per 600 seconds per IP; at most 500 profiles.
- Wrong name and wrong passcode return the same status and message, after the same amount of hashing work.
- No secrets (passcodes, session tokens, revocation tokens) in logs, URLs or committed files.
- `Settings.auth` defaults to on (`MEMORYATLAS_AUTH`, anything but `off`). Existing tests and the existing e2e run with `auth=False` / `MEMORYATLAS_AUTH=off` and must keep passing unchanged in behaviour.
- Do not edit the compiler, `recall/`, `privacy/` logic, the dashboard, Atlas, graph or chat components. Backend tests: `cd backend && .venv/bin/python -m pytest -q`. Frontend: `cd frontend && npm run check`.

## Review Focus

1. Profile A's session must not read or change profile B's data through any route using B's ids (`/claims/{id}/provenance`, `/claims/{id}/correct`, `/receipts/{id}`, `/consent/grants/{id}/revoke`, a draft id from `/capture/preview`, `/export`, `/graph`).
2. Unknown name and wrong passcode must be indistinguishable (status, body, and one scrypt computation each).
3. A locked profile must refuse even the right passcode until `locked_until`, and locking one profile must not affect another.
4. Resetting a demo profile while its runtime is cached and in use must not leave a stale connection or a half-copied file.
5. A cookie for a deleted or expired profile must get 401 and never recreate anything; deleting a profile must remove its database, WAL files and cache directory.

---

### Task 1: Passcodes, names and rate limiter

**Files:**
- Create: `backend/app/profiles/__init__.py` (empty), `backend/app/profiles/passcodes.py`, `backend/app/profiles/limits.py`
- Test: `backend/tests/test_profiles_basics.py`

**Interfaces:**
- Produces in `passcodes.py`:
  - `normalize_name(name: str) -> str` (NFKC, collapse whitespace, strip; raises `ValueError("name must be 2 to 40 characters")`)
  - `name_key(name: str) -> str` (`normalize_name(name).casefold()`)
  - `validate_passcode(passcode: str) -> None` (raises `ValueError("passcode must be 6 to 200 characters")`)
  - `hash_passcode(passcode: str) -> tuple[str, str]` returns `(salt_hex, hash_hex)`
  - `verify_passcode(passcode: str, salt_hex: str, hash_hex: str) -> bool`
  - `burn_hash(passcode: str) -> None` (one scrypt computation against a fixed salt, for unknown names)
- Produces in `limits.py`: `class RateLimiter(limit: int, window_s: float, clock: Callable[[], float] = time.monotonic)` with `allow(key: str) -> bool` (records the attempt only when allowed) and `retry_after(key: str) -> float`.

- [ ] **Step 1: Write failing tests** `test_profiles_basics.py`: `test_hash_then_verify_round_trips`, `test_verify_rejects_wrong_passcode`, `test_same_passcode_hashes_differently_each_time`, `test_name_is_normalised_and_keyed_case_insensitively` ("  Sai   Teja " and "SAI teja" give the same key; "Ｓai" NFKC folds), `test_name_length_bounds` (1 and 41 characters raise), `test_passcode_length_bounds` (5 and 201 raise, 6 and 200 pass), `test_rate_limiter_allows_up_to_limit_then_blocks`, `test_rate_limiter_window_expires` (fake clock), `test_rate_limiter_keys_are_independent`, `test_blocked_attempts_do_not_extend_the_window`.
- [ ] **Step 2:** Run `python -m pytest tests/test_profiles_basics.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement both modules (stdlib only).
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Commit `feat(profiles): passcode hashing, names and rate limiting`.

---

### Task 2: Registry

**Files:**
- Create: `backend/app/profiles/registry.py`
- Test: `backend/tests/test_profiles_registry.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `@dataclass(frozen=True) class Profile: profile_id: str; name: str; goals: list[str]; consent_at: str | None; demo_kind: str | None; created_at: str` with property `onboarded` (`consent_at is not None`).
  - Exceptions: `NameTaken`, `BadCredentials`, `Locked(retry_after: float)`, `TooManyProfiles`.
  - `class Registry(path: str, clock: Callable[[], float] = time.time, max_profiles: int = 500)` creating `profiles` and `sessions` tables (schema from the spec) when opened (`":memory:"` allowed for tests), with: `create(name, passcode, goals=None, demo_kind=None) -> Profile`, `authenticate(name, passcode) -> Profile`, `start_session(profile_id) -> str` (raw token), `profile_for_token(token: str) -> Profile | None`, `end_session(token: str) -> None`, `set_goals(profile_id, goals: list[str]) -> None`, `accept_consent(profile_id) -> None`, `delete(profile_id) -> None` (also deletes its sessions), `get(profile_id) -> Profile | None`, `count() -> int`.

- [ ] **Step 1: Write failing tests**: `test_create_and_authenticate`, `test_duplicate_name_differing_only_by_case_is_taken`, `test_unknown_name_and_wrong_passcode_raise_the_same_error` (same class, same message), `test_unknown_name_still_burns_a_hash` (monkeypatch `burn_hash` to count calls), `test_five_wrong_passcodes_lock_the_profile` (fake clock; sixth attempt with the right passcode raises `Locked` with `retry_after` near 900), `test_lock_expires`, `test_locking_one_profile_does_not_lock_another`, `test_success_resets_the_failure_count`, `test_session_token_is_stored_hashed` (the raw token is not in any column), `test_session_expires_after_30_days`, `test_end_session`, `test_delete_removes_profile_and_sessions`, `test_profile_cap` (`max_profiles=2`), `test_goals_and_consent_are_saved`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with `sqlite3` (check_same_thread=False plus a `threading.Lock` around writes). `profile_id = secrets.token_hex(6)`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat(profiles): registry with sessions and lockout`.

---

### Task 3: Per-profile runtime, and the API uses it (single-user parity)

**Files:**
- Create: `backend/app/profiles/runtime.py`
- Modify: `backend/app/api.py`, `backend/app/config.py` (add `auth: bool = os.getenv("MEMORYATLAS_AUTH", "on") != "off"` and `data_dir: str = os.getenv("MEMORYATLAS_DATA_DIR", "")`), `backend/app/demo.py` (`DemoRunner.__init__(..., seed: bool = True)`; when `seed` is False it never auto-resets), every existing test that calls `create_app(` (9 sites: `test_corrections.py`, `test_demo_day.py` x3, `test_expiry.py`, `test_recall.py`, `test_revocation.py`, `test_scaffold.py`, `test_upload_api.py`) to pass `auth=False` in its `Settings(...)`.
- Test: `backend/tests/test_runtime.py`

**Interfaces:**
- Produces in `runtime.py`:
  - `@dataclass class ProfileRuntime: profile_id: str; owner_name: str; conn: sqlite3.Connection; engine: MemoryEngine; demo: DemoRunner; recall: RecallService; revoker: RevocationEngine; drafts: DraftStore; llm: LLMClient; sweep_lock: threading.Lock; db_path: str | None; cache_dir: str` with `sweep() -> list[dict]` (same behaviour as today's closure; never raises).
  - `class Runtimes(settings: Settings, llm: LLMClient | None, root: str | None)` with `get(profile_id: str, owner_name: str, seed_demo: bool) -> ProfileRuntime` (builds once, then cached; database at `<root>/profiles/<profile_id>/memoryatlas.db`, cache at `<root>/profiles/<profile_id>/llmcache`; with `root=None` it uses `settings.db_path` as today), `evict(profile_id: str) -> None` (closes the connection and forgets it), `close_all() -> None`. `llm=None` builds one client per profile with `build_client(replace(settings, db_path=..., runtime_cache_dir=...))`; an injected `llm` is shared.
- `api.py`: a dependency `get_runtime(request) -> ProfileRuntime`. With `settings.auth` False it returns the single default runtime (built eagerly in `create_app`, seeded exactly as today, and exposed as `app.state.conn/engine/demo/drafts`). Every existing route takes `rt: ProfileRuntime = Depends(get_runtime)` and uses `rt.conn`, `rt.engine`, and so on instead of the closure variables; `/health` stays unauthenticated; the per-request sweep moves into `get_runtime` (`rt.sweep()`, skipped for `/health`). `/health` also returns `"auth": settings.auth`.
- Ruling to ledger: expiry is swept lazily when a profile's runtime is first built and on each of its requests, not for all profiles at startup (the privacy filter already refuses expired data; spec asked for startup sweep of all).

- [ ] **Step 1: Write failing tests** `test_runtime.py`: `test_runtimes_build_one_runtime_per_profile_and_cache_it`, `test_runtime_files_live_under_the_profile_id_directory`, `test_two_runtimes_have_separate_databases` (write a source via one, absent in the other), `test_evict_closes_the_connection` (using it afterwards raises `sqlite3.ProgrammingError`), `test_runtime_without_seed_has_no_grants`, `test_default_runtime_is_seeded_like_today` (auth False: `/demo/status` works with no cookie).
- [ ] **Step 2:** Run; Expected: FAIL.
- [ ] **Step 3:** Implement `runtime.py`; refactor `api.py` route by route; add `auth=False` to the nine test call sites.
- [ ] **Step 4:** Run the whole backend suite. Expected: all previous tests PASS unchanged, plus the new ones.
- [ ] **Step 5:** Commit `refactor(profiles): per-profile runtime behind the API, single-user mode unchanged`.

---

### Task 4: Auth routes and the signed-in gate

**Files:**
- Create: `backend/app/profiles/routes.py`
- Modify: `backend/app/api.py` (mount the router; in auth mode `get_runtime` resolves the cookie)
- Test: `backend/tests/test_profiles_api.py`

**Interfaces:**
- Consumes: `Registry`, `RateLimiter`, `Runtimes`.
- Produces (JSON): `POST /auth/signup {name, passcode, goals?: list[str]}` returns `{profile}` and sets the cookie (201); `POST /auth/signin {name, passcode}` returns `{profile}` and sets the cookie; `POST /auth/signout` (204, clears the cookie, ends the session); `GET /auth/me` returns `{auth: bool, profile: {profile_id, name, goals, onboarded, demo_kind}}` (401 when auth is on and not signed in; with auth off returns `{auth: false, profile: {profile_id: "local", name: "Local", goals: [], onboarded: true, demo_kind: null}}`); `POST /auth/goals {goals}`, `POST /auth/consent` (sets `consent_at`); `DELETE /auth/me {passcode}` (verifies the passcode, evicts the runtime, deletes the registry rows and the profile directory with `shutil.rmtree`, clears the cookie). Status codes: 422 invalid name or passcode, 409 name taken, 401 bad credentials (`{"detail": "Wrong name or passcode"}`), 423 locked (with `Retry-After`), 429 rate limited, 503 profile cap. Client IP is the first entry of `X-Forwarded-For` else `request.client.host`. All data routes in auth mode return 401 without a valid session cookie.
- `Profile.goals` accepted values: `remember_day`, `trips`, `work_meetings`, `family_friends`, `just_trying` (422 otherwise; at most 5).

- [ ] **Step 1: Write failing tests** `test_profiles_api.py` (two `TestClient`s over one app, `Settings(db_path=<tmp>/x.db, llm_mode="live", auth=True)`, `FakeLLM`): `test_data_routes_need_a_session` (parametrised over `/graph`, `/privacy/media`, `/consent/grants`, `/export`, `/demo/status`, `/recall/ask`: 401), `test_health_is_public`, `test_signup_signs_in_and_me_returns_the_profile`, `test_cookie_flags` (HttpOnly, SameSite=lax; Secure only with `X-Forwarded-Proto: https`), `test_session_survives_across_requests_and_signout_ends_it`, `test_signin_after_signout`, `test_unknown_name_and_wrong_passcode_look_identical` (Review Focus 2), `test_five_wrong_passcodes_return_423_even_for_the_right_one_then`, `test_locking_profile_a_does_not_lock_b`, `test_signup_and_signin_are_rate_limited_per_ip` (429 on the 6th sign-up with the same `X-Forwarded-For`; a different IP still works), `test_profile_cap_is_503`, `test_invalid_goals_are_422`, `test_delete_needs_the_passcode_and_removes_everything` (directory gone, cookie then gets 401, name can be reused; Review Focus 5), `test_expired_session_cookie_gets_401`, `test_isolation` (A adds a note via preview+commit; for B: `/graph` has no A nodes, `/export` has none of A's text, `/claims/<A claim id>/provenance` 404, `/claims/<A claim id>/correct` 404, `/receipts/<A receipt>` 404, `/consent/grants/<A grant>/revoke` 404 with A's token, committing A's draft id gives 404; Review Focus 1), `test_uploads_still_need_live_mode`.
- [ ] **Step 2:** Run; Expected: FAIL.
- [ ] **Step 3:** Implement `routes.py` and the cookie-resolving `get_runtime`. Owner display name for a new runtime is the profile's name; build it with `seed_demo=False`, and call the resolver's `ensure_owner(name)` once when its database has no owner entity.
- [ ] **Step 4:** Run the whole suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat(profiles): sign-up, sign-in, sessions and per-profile access`.

---

### Task 5: Sample day, demo profiles and reset

**Files:**
- Modify: `backend/app/api.py` (`/demo/load-sample`, `/demo/reset` rules), `backend/app/profiles/runtime.py` (`restore_snapshot`)
- Create: `backend/app/profiles/snapshots.py`
- Test: `backend/tests/test_profiles_demo.py`

**Interfaces:**
- Produces:
  - `snapshots.snapshot_path(kind: str) -> str` (`fixtures/profiles/<kind>.db` under the repo root) and `snapshots.restore(runtimes: Runtimes, profile: Profile) -> None` (evicts the runtime, deletes `memoryatlas.db`, `-wal` and `-shm`, copies the snapshot file in with `shutil.copyfile`, then lets the next `get` reopen it; raises `FileNotFoundError` if no snapshot).
  - `POST /demo/load-sample` (auth mode): 409 `"This profile already has memories"` unless the profile has no sources; otherwise `demo.reset()` then `demo.advance(50)`, returns `demo.status()`. (Auth off: same behaviour as `/demo/advance?steps=50`.)
  - `POST /demo/reset` in auth mode: for `demo_kind` profiles restores the snapshot (falling back to `demo.reset()` when `demo_kind == "staged"` and no snapshot exists) and returns `{"reset": true}`; for any other profile returns 403 `"Only demo profiles can be reset. Use Settings to delete your profile."`. Auth off: unchanged.
  - `/demo/advance`, `/demo/live/{id}`, `/demo/status`, `/demo/grants`, `/demo/grants/{id}/expire` work per profile as they do today.
- Resets are serialised per profile (hold `rt.sweep_lock` while evicting and restoring) and the cached runtime is evicted so no stale connection survives (Review Focus 4).

- [ ] **Step 1: Write failing tests** `test_profiles_demo.py`: `test_new_profile_has_no_grants_and_no_memories`, `test_load_sample_fills_an_empty_profile` (FakeLLM; claims > 0 afterwards), `test_load_sample_refuses_a_profile_with_memories` (409), `test_reset_is_forbidden_for_a_normal_profile` (403, data intact), `test_reset_restores_a_demo_profile_snapshot` (build a tiny snapshot in `tmp_path` by pointing `snapshot_path` at it with `monkeypatch`; after a visitor adds a note and resets, the snapshot content is back and the note is gone), `test_reset_of_one_demo_profile_does_not_touch_another`, `test_reset_after_the_runtime_was_cached_uses_a_fresh_connection`, `test_reset_missing_snapshot_for_real_kind_is_a_clear_error` (503 with a message naming the kind).
- [ ] **Step 2:** Run; Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat(profiles): sample day, demo profiles and safe reset`.

---

### Task 6: Seeding the two demo profiles

**Files:**
- Create: `backend/scripts/seed_profiles.py`, `fixtures/profiles/README.md`, `fixtures/profiles/real/manifest.example.yaml`
- Test: `backend/tests/test_seed_profiles.py`

**Interfaces:**
- Consumes: `Registry`, `Runtimes`, `build_preview`, `plan`/`commit` from `app/capture/commit.py`, `MediaError`.
- Produces: CLI `python scripts/seed_profiles.py staged|real --data-dir DIR [--media DIR]` reading `DEMO_STAGED_NAME`, `DEMO_STAGED_PASSCODE`, `DEMO_REAL_NAME`, `DEMO_REAL_PASSCODE` from the environment. It creates (or re-uses) the registry profile with `demo_kind`, builds the content through the real pipeline in live mode, prints every stored claim for review, and writes the text-only snapshot with `VACUUM INTO` to `fixtures/profiles/<kind>.db`. `staged`: `demo.reset()`, `advance(50)`, then plays the live-upload event. `real`: for each image or audio file in `--media` it strips GPS before use (builds the draft with `lat`/`lon` removed), applies the answers from `manifest.yaml` (`captured_at`, `where`, `owner_speaker`, per-person `name`/`consented`), refuses any file whose manifest entry is missing a required answer, and never copies the media anywhere. Pure helper `strip_gps(draft: Draft) -> Draft` and `load_manifest(path) -> dict` are the unit-tested parts.

- [ ] **Step 1: Write failing tests**: `test_strip_gps_clears_coordinates_only`, `test_manifest_requires_a_decision_for_every_file`, `test_manifest_rejects_unknown_keys`, `test_seed_staged_builds_a_snapshot_with_claims` (FakeLLM, tmp dir; snapshot opens with `db.connect` and has claims, no raw media columns set), `test_seed_never_writes_media_into_the_snapshot_directory`.
- [ ] **Step 2:** Run; Expected: FAIL.
- [ ] **Step 3:** Implement the script and helpers; add `fixtures/profiles/README.md` with the owner's checklist (no faces of people who did not agree, no home or work address, review printed claims before committing the snapshot).
- [ ] **Step 4:** Run the whole suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat(profiles): script that builds the two demo profile snapshots`.

---

### Task 7: Proxy, compose and deployment without the shared login

**Files:**
- Modify: `frontend/nginx.conf` (`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`, `proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;`, keep `client_max_body_size 100m`), `compose.yaml` (backend env `MEMORYATLAS_AUTH: ${MEMORYATLAS_AUTH:-on}`, `MEMORYATLAS_DATA_DIR: /data`), `deploy/Caddyfile` (remove `basic_auth`; keep TLS, headers, `request_body`), `deploy/compose.public.yaml` (drop the three basic-auth variables, keep `PUBLIC_HOST`), `.env.example`, `docs/DEPLOY.md`, `docs/DOCKER.md`
- Test: none new (configuration); verification below.

- [ ] **Step 1:** Make the edits. `docs/DEPLOY.md` must state: the app now protects data with profiles; open sign-up is rate limited; demo profile credentials are published on purpose and hold only demo content; how to seed them (`DEMO_*` variables, `seed_profiles.py`, committing the snapshots).
- [ ] **Step 2:** Validate: `docker compose config -q` and `PUBLIC_HOST=x.example.org docker compose -f compose.yaml -f deploy/compose.public.yaml config -q` both exit 0.
- [ ] **Step 3:** Run the stack with the public override on local ports (`PUBLIC_HTTP_PORT=8081 PUBLIC_HTTPS_PORT=8443 PUBLIC_HOST=localhost`). Expected: `curl -sk https://localhost:8443/api/health` returns 200 with `"auth": true`; `curl -sk https://localhost:8443/api/graph` returns 401; a sign-up through `https` returns a `Set-Cookie` containing `Secure`; two sign-ups from the same client IP beyond the limit return 429. Then restore the normal stack (never `down -v`).
- [ ] **Step 4:** Commit `feat(profiles): proxy headers and public deployment protected by profiles`.

---

### Task 8: Frontend session, API and pure onboarding helpers

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Create: `frontend/src/utils/onboarding.ts`, `frontend/src/utils/onboarding.test.ts`, `frontend/src/hooks/useSession.ts`

**Interfaces:**
- Produces in `types.ts`: `Goal = "remember_day" | "trips" | "work_meetings" | "family_friends" | "just_trying"`; `Me = { auth: boolean; profile: { profile_id: string; name: string; goals: Goal[]; onboarded: boolean; demo_kind: "staged" | "real" | null } }`.
- Produces in `client.ts`: `api.me()`, `api.signup({name, passcode, goals?})`, `api.signin({name, passcode})`, `api.signout()`, `api.setGoals(goals)`, `api.acceptConsent()`, `api.deleteMe(passcode)`, `api.loadSample()`, `api.resetDemo()`. A 401 from any call other than `signin`/`signup` is surfaced as `ApiError` with `status === 401` so the app can return to the gate.
- Produces in `onboarding.ts` (pure): `GOALS: { id: Goal; label: string; blurb: string }[]` (the five goals, with these labels: Remember my day, Trips, Work meetings, Family and friends, Just trying it); `followUps(goals: Goal[]): { id: string; question: string; options: string[] }[]` (static table, at most 3 questions in total, none for `just_trying` alone); `validateName(name: string): string | null` and `validatePasscode(passcode: string): string | null` (return the message to show, mirroring the backend rules); `CONSENT_STATEMENTS: string[]` (exactly these four: "Muse reads what I add.", "Only the text Muse reads is kept, never the photo, audio or video.", "Anyone else in a memory must agree to be in it.", "I can forget anything, and everything resting only on it goes too."); `nextStep(state: { signedIn: boolean; goalsSaved: boolean; consented: boolean }): "account" | "goals" | "consent" | "first-memory"`.
- Produces `useSession()`: `{ status: "loading" | "signedOut" | "signedIn"; me: Me | null; refresh(): Promise<void>; signOut(): Promise<void> }`; it treats `auth: false` as signed in.

- [ ] **Step 1: Write failing tests** `onboarding.test.ts`: `GOALS_has_five_entries_with_labels`, `validateName_rules` (1 and 41 characters, whitespace only, ok), `validatePasscode_rules` (5, 6, 201), `followUps_is_empty_for_just_trying_it_alone`, `followUps_never_exceeds_three`, `followUps_includes_a_meetings_question_for_work_meetings`, `CONSENT_STATEMENTS_are_the_four_agreed_sentences`, `nextStep_walks_account_goals_consent_first_memory`.
- [ ] **Step 2:** Run `npx vitest run src/utils/onboarding.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement types, client methods, helpers and the hook.
- [ ] **Step 4:** Run `npm run check`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(ui): session hook, auth API and onboarding helpers`.

---

### Task 9: Sign-in gate and onboarding screens

**Files:**
- Create: `frontend/src/components/AuthGate.tsx`, `frontend/src/components/Onboarding.tsx`
- Modify: `frontend/src/main.tsx` or `frontend/src/App.tsx` (render the gate before the app: loading shows a plain "Loading…" state; signed out shows `AuthGate`; signed in but not `onboarded` shows `Onboarding` from the step `nextStep` returns; otherwise the existing app), `frontend/src/styles.css` (`.auth-*`, `.onb-*` using existing tokens)

**Interfaces:**
- Consumes: Task 8 `api`, `useSession`, `onboarding.ts`; the existing `AddMemory` component (`open`, `mode`, `onClose`, `onSaved`).
- Produces: `AuthGate({ onSignedIn })` with two tabs, **Sign in** and **Create profile** (name, passcode, a plain "There is no passcode reset" note; inline errors from the API; locked and rate-limited messages show the wait). `Onboarding({ me, mode, onDone })`: a progress indicator of five steps; step 2 goals as selectable cards (multi-select) followed by the `followUps` questions (answers are shown and kept in component state only; they do not need saving in this project); step 3 shows `CONSENT_STATEMENTS` as four required checkboxes and an "I agree" button that calls `api.acceptConsent()`; step 4 offers **Add a memory** (opens `AddMemory`), **Try the sample day** (`api.loadSample()`, with progress and errors) and **Skip for now**; step 5 is the existing dashboard. In replay mode step 4 explains that adding needs live Muse and offers only the sample day and Skip. Every control is keyboard reachable with visible labels, errors use `role="alert"`, and the screens work at 375 px width.

- [ ] **Step 1:** Implement the components and wiring.
- [ ] **Step 2:** Run `cd frontend && npm run check`. Expected: PASS.
- [ ] **Step 3:** Covered by Task 11's browser run (sign up, onboard, sign out, second profile). Do a first pass now: start a backend with `MEMORYATLAS_AUTH=on MEMORYATLAS_LLM_MODE=replay` on a scratch data directory and the dev server, sign up in Chromium with Playwright and screenshot each step at 1280 px and 375 px; read the screenshots.
- [ ] **Step 4:** Commit `feat(ui): sign-in gate and five-step onboarding`.

---

### Task 10: Settings, profile menu and demo reset in the UI

**Files:**
- Create: `frontend/src/components/Settings.tsx`
- Modify: `frontend/src/components/Header.tsx` (profile menu: name, Settings, Sign out; new props `profileName: string | null`, `onSettings: () => void`, `onSignOut: () => void`, `canReset: boolean`), `frontend/src/App.tsx` (state for the Settings dialog; `canReset` is true when `auth` is false or the profile is a demo profile; the existing Reset buttons call `api.resetDemo()` for demo profiles and are hidden otherwise), `frontend/src/components/Dashboard.tsx` (hide its Reset button when `canReset` is false; no other change), `frontend/src/styles.css`

**Interfaces:**
- Produces: `Settings({ open, me, onClose, onChanged, onSignedOut })` as a `Dialog` with: goals (the same five cards, saves with `api.setGoals`); the consent statements (read only, with the acceptance date shown as "Agreed" when present); **Reset demo data** (only for demo profiles, with a confirm step); **Delete my profile** (asks for the passcode, explains it removes everything and cannot be undone, then `api.deleteMe`, then returns to the gate); **Sign out**.

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Run `cd frontend && npm run check`. Expected: PASS.
- [ ] **Step 3:** Commit `feat(ui): profile menu, settings, delete profile and demo reset`.

---

### Task 11: End-to-end isolation check in a browser, and docs

**Files:**
- Create: `frontend/e2e/profiles.cjs`
- Modify: `frontend/package.json` (script `"e2e:profiles": "node e2e/profiles.cjs"`), `frontend/e2e/walkthrough.cjs` header comment (run the backend with `MEMORYATLAS_AUTH=off`), `docs/LOCAL_SETUP.md` (Profiles section: sign-up, onboarding, demo profiles and where their credentials are published, `MEMORYATLAS_AUTH=off` for single-user development), `README.md` (two lines: demo profile credentials placeholder section and a link)

- [ ] **Step 1:** Write `e2e/profiles.cjs` (Playwright, replay mode, scratch data directory): sign up as Profile A and walk onboarding with "Try the sample day"; assert the dashboard shows content; sign out; sign up as Profile B and assert the dashboard shows none of A's content and `/api/graph` has no nodes; sign in as A again and assert A's content is back; wrong passcode shows the generic message; five wrong passcodes show the locked message; delete B with the passcode and assert signing in as B then fails; a second browser context cannot read A's graph without signing in (401).
- [ ] **Step 2:** Run it with `MEMORYATLAS_AUTH=on MEMORYATLAS_LLM_MODE=replay` backend and the dev server, plus the existing `npm run e2e` against a backend with `MEMORYATLAS_AUTH=off`. Expected: both print `All steps held`.
- [ ] **Step 3:** Run `cd backend && .venv/bin/python -m pytest -q` and `cd frontend && npm run check`. Expected: PASS.
- [ ] **Step 4:** Check authorship: `git log main..HEAD --format='%an <%ae> | %cn <%ce>' | sort -u` shows only `saiteja195`; `git log main..HEAD --format=%B | grep -i co-authored || echo clean` prints `clean`.
- [ ] **Step 5:** Commit `docs: profiles, demo profiles and the isolation e2e`.
