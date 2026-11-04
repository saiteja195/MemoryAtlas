# Configuration

Settings are environment variables, read by `backend/app/config.py`. Put them in a `.env` file next to `compose.yaml` (copy `.env.example`) or export them. **Never commit a key.**

| Variable | Default | Meaning |
|---|---|---|
| `MEMORYATLAS_LLM_MODE` | `replay` | `replay`: recorded responses, offline. `record`: live and cache. `live`: call the Meta Model API |
| `MODEL_API_KEY` | empty | Meta Model API key; not baked into any image |
| `META_API_BASE_URL` | `https://api.meta.ai` | API base URL |
| `META_MODEL` | `muse-spark-1.3` | Text and vision model |
| `META_ASR_MODEL` | `muse-voice-transcribe-1.0` | Speech model |
| `META_SAM_MODEL` | `sam-3.1` | Object-tracking model |
| `MEMORYATLAS_SECRET` | `dev-only-secret` | Keys the HMAC of consent withdrawal codes. **Change it for anything that is not a demo** |
| `MEMORYATLAS_AUTH` | `on` | `on`: sign up with a name and passcode and get a private Atlas. `off`: one shared Atlas with no sign-in (development only) |
| `MEMORYATLAS_DB` | `memoryatlas.db` | Database path in single-user mode |
| `MEMORYATLAS_DATA_DIR` | next to the database | Where the profile registry and each profile's database live |
| `MEMORYATLAS_CACHE_DIR` | `fixtures/llm_cache` | Read-only seed of recorded responses |
| `MEMORYATLAS_RUNTIME_CACHE` | next to the database | Where the running app records responses; a forgetting purge cleans it |
| `MEMORYATLAS_DEMO_SCRIPT` | `fixtures/demo_day/script.yaml` | The scripted day |
| `WEB_PORT` | `8080` | Docker: host port for the UI (bound to `127.0.0.1`) |
| `PUBLIC_HOST` | – | Public deployment: the host name Caddy gets a certificate for |
| `EVAL_LABEL`, `EVAL_RUNS` | – | Docker evaluation run name and count |

## Modes and what works in each

| | replay | record | live |
|---|---|---|---|
| Scripted demo day and recorded questions | yes | yes | yes |
| Any new question or upload | no | yes | yes |
| Add your own memories | no | **no** (it would cache transcripts of people who may say no) | yes |

The UI always shows the active mode.

## Rate limits

Calls that spend model tokens are rate limited per profile and per network address, and opt-in object tracking is limited to five videos an hour. A limit returns HTTP 429 with a plain message.
