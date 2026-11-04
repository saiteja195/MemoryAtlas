# API Reference

FastAPI, served at the root of the backend (the web service proxies it under `/api/`). Interactive docs are at `/docs` when running. With profiles on, every call except `/health` and the `/auth` sign-in routes needs a signed-in session cookie.

## Profiles

| Method and path | Purpose |
|---|---|
| `POST /auth/signup`, `/auth/signin`, `/auth/signout` | Create a profile, sign in, sign out |
| `GET /auth/me` | The signed-in profile and mode |
| `POST /auth/goals`, `POST /auth/consent` | Onboarding choices and acceptance |
| `DELETE /auth/me` | Delete the profile and its data (asks for the passcode) |

## Memory and recall

| Method and path | Purpose |
|---|---|
| `GET /health` | Mode and whether sign-in is on |
| `GET /graph` | Nodes and edges, with status and history |
| `POST /recall/ask`, `POST /recall/ask/start` | Ask a question. Returns `{status, answer, cited_claim_ids, ...}`; `/start` runs it as a background job |
| `GET /chat` | The assistant thread |
| `GET /claims/{id}/provenance` | The justification tree down to sources |
| `POST /claims/{id}/correct`, `/correct/start` | Replace or retract a claim; the old one is superseded, history kept |
| `GET /insights` | Dashboard: model usage and day coverage (counts only) |
| `GET /todos`, `POST /todos/{claim_id}` | Tracked promises and requests; set `open`, `done` or `dismissed` |

## Adding memories

| Method and path | Purpose |
|---|---|
| `POST /capture/preview`, `/capture/preview/start` | Read an upload and return a draft. `kind` is `frame`, `photos` (1 to 8, `frames_b64` + `photo_times`), `audio`, `video` or `note`. Stores nothing |
| `POST /capture/commit`, `/capture/commit/start` | Store a confirmed draft (the page uses `/start` and polls) |
| `GET /capture/commit/jobs/{id}` | Progress and result of a save |
| `POST /capture/track` | Opt-in object tracking in a video's frames (SAM 3.1) |
| `GET /jobs`, `GET/DELETE /jobs/{id}` | Background jobs |
| `POST /capture/{kind}` | Scripted capture used by the demo |

## Consent and forgetting

| Method and path | Purpose |
|---|---|
| `POST /consent/grants`, `GET /consent/grants` | Create and list grants |
| `POST /consent/grants/{id}/revoke` | Withdraw with the code `{"token": "..."}` |
| `POST /consent/grants/{id}/withdraw` | The owner withdraws their own consent (no code) |
| `POST /memories/{source_id}/delete` | Delete one saved memory and what rests only on it |
| `POST /consent/expire-due` | Forget what rested on lapsed grants (also runs automatically before each request) |
| `GET /receipts/{id}` | A forgetting receipt: counts and check results, no claim text |
| `GET /export` | A JSON export of the readable memory |
| `GET /privacy/media` | Raw media retained (always 0) |

## Demo control

| Method and path | Purpose |
|---|---|
| `GET /demo/status`, `POST /demo/reset` | State of the scripted day; reset it |
| `POST /demo/load-sample` | Fill an empty profile with the sample day |
| `POST /demo/advance`, `/demo/live/{event_id}` | Play the next scripted events, or the live photo |
| `GET /demo/grants`, `POST /demo/grants/{id}/expire` | **Demo only**: the codes a real person would hold, and let a grant lapse now |

## Conventions

- **Errors** are `{"detail": "..."}` with a plain message. `404` for a claim you cannot read, `409` when live mode is needed, `413` for too-large uploads, `415` for unreadable media, `422` for validation, `429` for rate limits, `503` when the model is unavailable.
- **Background jobs** return `202` with a `job_id`; poll the job for state, elapsed time and model calls started and finished.
- **Answer status** is `answered`, `partial` or `abstained`.
