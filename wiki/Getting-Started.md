# Getting Started

You do **not** need an API key to run, test or demo MemoryAtlas: by default it replays recorded Muse Spark responses committed to the repository.

## Try it without installing

A hosted copy runs at **<https://memoryatlas.209-145-49-232.sslip.io>** with a live Muse model. The README lists demo profiles anyone can sign in to (they hold only demo content, and **Settings > Reset demo data** restores them), or create your own private profile.

## Run it locally

Needs Python 3.11+, Node.js 18+, `make` and `git`.

```bash
git clone https://github.com/saiteja195/MemoryAtlas.git
cd MemoryAtlas
make setup
```

```bash
make test
```

```bash
make dev
```

Open the address `make dev` prints (the Vite dev server proxies `/api` to the backend on port 8000).

## Run it with Docker

Separate `backend` and `web` (nginx) services on one Docker network. No local Python or Node needed.

```bash
docker compose up --build
```

Then open <http://localhost:8080>. Only the UI is published, on `127.0.0.1`. The SQLite file lives in a named volume, so `down` and `up` keep your data.

## Live mode (adding your own memories)

Adding a photo, voice recording, video or note needs a model key.

```bash
export MODEL_API_KEY=...        # never commit it
export MEMORYATLAS_LLM_MODE=live
make dev
```

With Docker: `MEMORYATLAS_LLM_MODE=live MODEL_API_KEY=... docker compose up -d`.

## A first five minutes

1. Sign in to a demo profile, or create one and choose **Try the sample day**, then **Play the day**.
2. Ask **"Which restaurant did Alex recommend when we met near the office?"** and open the evidence: the answer joins a conversation, a calendar entry and a storefront photo.
3. Ask **"Where is my wallet?"**, then press **Upload live photo · 17:45** and ask again. The answer changes, the old sighting is kept as history.
4. Open the **Consent** tab, withdraw Alex's consent, and read the receipt: what was removed, what stayed and why, and seven green checks.
5. Ask the same questions again. The conversation facts are gone; "I met Alex at 12:30" and the awning colour survive.

## Public deployment with HTTPS

Phones only allow the camera on `https://`. `docs/DEPLOY.md` describes a VM with Docker, a free DuckDNS name and Caddy, which obtains the certificate automatically. Keep `MEMORYATLAS_AUTH` on (the default) on a public VM.

## More

- [Configuration](Configuration) for every setting
- [`docs/LOCAL_SETUP.md`](https://github.com/saiteja195/MemoryAtlas/blob/main/docs/LOCAL_SETUP.md), [`docs/DOCKER.md`](https://github.com/saiteja195/MemoryAtlas/blob/main/docs/DOCKER.md) and [`docs/DEPLOY.md`](https://github.com/saiteja195/MemoryAtlas/blob/main/docs/DEPLOY.md) for the full guides
