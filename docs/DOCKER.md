# Running MemoryAtlas with Docker

The whole app as separate services on one private Docker network. No API key is needed: by default the
backend replays the recorded Muse Spark responses that are committed to the repo.

```bash
docker compose up --build        # or: make docker-up
```

Then open **http://localhost:8080**. Stop with `docker compose down` (your data stays) or
`docker compose down -v` (also deletes the data volume).

## The services

| Service | Image | What it does | Reachable from |
|---|---|---|---|
| `web` | nginx 1.27 (built UI) | Serves the static UI and proxies `/api/*` to the backend, exactly as the Vite dev server does | host, on `127.0.0.1:8080` only |
| `backend` | Python 3.12 + FastAPI + SQLite | The memory engine and API. Runs as an unprivileged user (uid 10001) | `web`, on the `memoryatlas` network (port 8000, **not** published to the host) |
| `eval` | the backend image | Optional (`--profile eval`): runs the evaluation against the live model | outbound only |

Both main services are on the `memoryatlas` bridge network and find each other by service name
(`http://backend:8000`). `web` waits until the backend's health check passes before it starts.

There is deliberately no database service: the memory map is one SQLite file (see `docs/HANDOFF.md`), kept in
the `data` volume at `/data/memoryatlas.db`, next to the model-response cache. A restart or `down`/`up` keeps it.

## Settings

Put them in a `.env` file next to `compose.yaml` (copy `.env.example`) or export them. Compose reads `.env`
automatically.

| Variable | Default | Meaning |
|---|---|---|
| `MEMORYATLAS_LLM_MODE` | `replay` | `replay` = recorded responses, offline. `live` = call the Meta Model API (needs the key) |
| `MODEL_API_KEY` | empty | Meta Model API key. Never commit it; it is not baked into any image |
| `MEMORYATLAS_SECRET` | `dev-only-secret` | Keys the HMAC of consent revocation tokens. **Change it for anything that is not a demo** |
| `WEB_PORT` | `8080` | Host port for the UI |

Live mode: `MEMORYATLAS_LLM_MODE=live MODEL_API_KEY=... docker compose up -d`.

## Run the evaluation in a container

```bash
export MODEL_API_KEY=...
make docker-eval                 # about an hour; writes eval/results/docker-run/
# or: HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose --profile eval run --rm eval
```

Set `HOST_UID`/`HOST_GID` (the make target does) so the result files on your machine belong to you; without
them the container runs as uid 10001 and cannot write to a folder you own.

## Security notes

- Only the UI port is published, and only on `127.0.0.1`. The demo endpoints (`/api/demo/*`) hand out
  revocation tokens so the demo can act as "Alex scans the QR code"; they must not face a network. To expose
  the app beyond your machine, put a real front end with authentication in front and remove the demo routes.
- The backend container drops all Linux capabilities and cannot gain privileges. Raw photos and audio are never
  stored, in the container or the volume: the database keeps text only (the header shows "Raw media kept: 0 B").
- Forgetting works inside the container the same way: a withdrawal deletes rows, clears the model-response cache
  in the volume, and runs the leak checks, including a scan of the database file.

## Useful commands

```bash
docker compose logs -f backend             # watch the API
docker compose exec backend sh             # a shell in the backend container
# Re-recording fixtures (scripts/*_demo.py) is done from a normal checkout, not in the container:
# the image's fixtures/ is read-only seed data.
docker compose build --no-cache            # rebuild from scratch
```

## Verified

Built and run on 2 November 2026 with Docker 29.9 and Compose 5.6: both images build, the stack comes up healthy,
the UI, the SPA fallback (including the simulated phone page) and `/api` through nginx all respond, the backend
is unreachable from the host, `web` reaches `backend` by name, data survives a restart and `down`/`up` and is
removed by `down -v`, and the full browser walkthrough (`frontend/e2e/walkthrough.cjs`, with accessibility
audits) passes against `http://localhost:8080`. Not verified: Apple-silicon (arm64) builds, and `docker build`
behind a proxy that re-signs TLS needs that proxy's CA added to the build.
