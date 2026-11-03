# Profiles and onboarding: design

Status: draft for approval. Project 1 of 3 (2: dashboard and shared assistant, 3: Atlas refresh).
Depends on `feature/upload-and-chat` (the Add memory flow); merge that first, or branch from it.

## Intent

MemoryAtlas is single-user: one global database, one hard-coded owner (`me`), no login. That cannot
be shown to hackathon reviewers or shared with friends, who must each see only their own memories and
validate the consent and forgetting claims on their own data. This project adds **profiles** (a name and a
passcode, each with a fully private Atlas) and a guided **onboarding** that creates a profile, asks how the
person wants to use the app, takes consent, and gets their first memory in.

## Goals

- Anyone can sign up with a name and passcode, and sign in again later. Their data is invisible to others.
- Two pre-built **demo profiles** whose credentials are published in the README: one built from the
  scripted staged day, one from the owner's real photos. Both resettable by the visitor.
- Onboarding: profile, goals ("how will you use it"), consent in plain words, first memory, then the dashboard.
- The chosen goals are saved so Project 2 can personalise dashboard cards and suggested questions.
- A person can delete their profile and everything in it.
- Safe to run on a public VM (replaces the shared basic-auth gate).

## Non-goals

- No email, password reset, OAuth or roles. A forgotten passcode means a new profile (said plainly in the UI).
- No change to the dashboard, Atlas or chat layouts (Projects 2 and 3). This project only adds the sign-in,
  onboarding, settings and profile menu screens, and a signed-in gate.
- No change to the compiler, recall investigator or consent/revocation logic. They run unchanged, once per profile.
- No sharing of memories between profiles.

## Anti-goals

- One profile ever reading or affecting another's data, through any endpoint, the chat, exports or caches.
- A demo profile holding real personal data of people who did not agree, or real location data.
- The shared demo profiles being corrupted for the next reviewer.
- Passcodes, session tokens or revocation tokens in logs, URLs or the repo's history.

## Constraints

- `CLAUDE.md`: code, not prompts, decides storage, visibility and deletion. Profile isolation is enforced in
  the request layer and the file layout, never by asking a model.
- No new heavy dependencies. Hash passcodes with the standard library (`hashlib.scrypt`).
- Commits only as `saiteja195`, no trailers. Conventional commits, scope from `CONTRIBUTING.md` (add `profiles`).
- Existing tests keep passing. The existing single-owner code paths are reused per profile, not rewritten.

## Design

### Data layout

- A small **registry** database (`<data>/profiles.db`): `profiles(profile_id, name, name_key, salt, passcode_hash,
  goals_json, created_at, demo_kind NULL|'staged'|'real', failed_count, locked_until)` and
  `sessions(token_hash, profile_id, created_at, expires_at)`. `name_key` is the lowercased, trimmed name and is unique.
- Each profile has its **own SQLite file and cache directory**: `<data>/profiles/<profile_id>/memoryatlas.db`
  and `.../llmcache`. `profile_id` is a random 12-character hex id, never the name.
- Passcodes: at least 6 characters; `scrypt` with a per-profile random salt; compared in constant time.

### Request layer

`create_app` stops building one global connection, engine and runners. A `ProfileRuntime` bundles what
exists today (connection, `MemoryEngine`, `DemoRunner`, `RecallService`, `RevocationEngine`, `DraftStore`) for
one profile, created lazily and cached by `profile_id`. A FastAPI dependency reads the session cookie,
resolves it to a profile and returns that profile's runtime; **every** existing route (`/graph`, `/recall/ask`,
`/capture/*`, `/consent/*`, `/demo/*`, `/export`, `/privacy/media`, `/claims/*`, `/receipts/*`) takes it and uses
it instead of the closure variables. Unauthenticated calls get 401. `/health` stays public. The expiry sweep
runs per profile (on that profile's requests) and at startup for all profiles.

### Auth

- `POST /auth/signup {name, passcode, goals?}`, `POST /auth/signin`, `POST /auth/signout`, `GET /auth/me`,
  `DELETE /auth/me` (requires the passcode again; removes the profile row, its database and cache).
- Session: 32-byte random token in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` when the request is https),
  stored only as a hash, 30-day expiry.
- Abuse limits: 5 wrong passcodes lock that profile for 15 minutes; per-IP limits on sign-up (5/hour) and
  sign-in (20/10 min); a cap of 500 profiles; names 2 to 40 characters.
- Errors never reveal whether a name exists: wrong name and wrong passcode give the same message.

### Onboarding (first visit, five steps)

1. **Profile:** name and passcode (or "Sign in" if returning), with the "no reset" note.
2. **Goals:** pick any of *Remember my day, Trips, Work meetings, Family and friends, Just trying it*, then up to
   three short follow-ups chosen by the goals (for example "Which meetings matter most?"). Saved as `goals_json`.
3. **Consent:** plain-language statements the person must tick (what Muse reads, that only text is kept, that others
   in a memory must agree, that anything can be forgotten). The acceptance is stored with a timestamp.
4. **First memory:** the existing Add memory dialog, plus a **Try the sample day** button that loads the scripted day
   into this profile for anyone with nothing to upload.
5. **Dashboard.**
Skipping step 4 is allowed. Settings (new page) lets the person edit goals, see the consent statement, sign out,
**reset the demo data** (demo profiles only) or **delete the profile**.

### Demo profiles

- Two rows with `demo_kind` set, created by `backend/scripts/seed_profiles.py` from `fixtures/profiles/`:
  `staged` (the existing "A Day You Forgot" script) and `real` (built from the owner's photos).
- Each ships as a **text-only snapshot** (`fixtures/profiles/<kind>.db`) built once by running the content through
  the real pipeline with live Muse. Raw photos are never committed; only the derived text and claims.
- **Reset** copies the snapshot over the profile's database and clears its sessions' drafts and caches. It is only
  available to demo profiles and only affects the signed-in demo profile.
- Credentials (name and passcode) come from environment variables at seed time and are published in the README by
  the owner. Sign-in works the same as any profile.
- Real-photo content rules (owner's responsibility, checked by the seed script's report): no faces of people who did
  not agree, no home or work address, EXIF GPS stripped before processing. The script prints each stored claim for
  the owner to review before the snapshot is committed.

### Deployment

The public override drops the shared basic-auth gate: Caddy keeps HTTPS and security headers, and the app's own
sign-in protects data. Auth rate limits keep the open sign-up from being a free abuse target. `docs/DEPLOY.md` is updated.

### Frontend (this project only)

New: `AuthGate` (sign in or sign up), `Onboarding` (5 steps), `Settings`, a profile menu in the header (name,
Settings, Sign out). `App` renders `AuthGate` until `GET /auth/me` succeeds. Dashboard and Atlas are untouched.

## Decisions I made (please check)

- **P1.** One SQLite file per profile plus a registry DB, rather than a `profile_id` column in every table. Isolation
  becomes a file boundary, and the existing code and tests stay as they are.
- **P2.** Cookie sessions, 30 days. No JWT.
- **P3.** Minimum passcode length 6, no complexity rules. Lockout after 5 failures for 15 minutes.
- **P4.** Capped at 500 profiles; sign-up limited to 5 per hour per IP.
- **P5.** Goals and consent are stored in the registry (`goals_json`, `consent_at`), not in the memory database,
  so resetting a demo profile does not undo them.
- **P6.** Demo profiles are snapshots restored by file copy, not re-ingested live on every reset.
- **P7.** `DELETE /auth/me` requires the passcode, and is the only way to remove a profile.

## Open for the builder

- Exact JSON for onboarding follow-up questions per goal (a small static table in code).
- The file-copy reset must be safe while a runtime for that profile is cached (close and re-open its connection).

## Needs the owner

- Names and passcodes for the two demo profiles (published in the README).
- The real photos (and any audio or video) for the `real` demo profile, plus a note of who is in them and whether
  they agreed.

## Verification

- Backend: isolation tests (two profiles, same `/graph` call, different data; profile A's session cannot read
  or modify profile B through any route, including `/export` and `/claims/{id}/provenance` with B's ids); auth tests
  (hashing, lockout, rate limits, identical error for unknown name and wrong passcode, session expiry, delete);
  demo reset restores the snapshot and does not touch other profiles.
- Frontend: `npm run check`; a real-browser run (Playwright, as for the e2e) that signs up, onboards, adds a memory,
  signs out, signs in as a second profile and sees none of the first profile's memories.
- Manual: the two demo profiles load with their content and reset correctly on the public VM.
