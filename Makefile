.PHONY: setup dev test api web check-web eval docker-up docker-down docker-logs docker-eval

setup:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
	cd frontend && npm install

api:
	cd backend && . .venv/bin/activate && { [ ! -f ../.env ] || { set -a; . ../.env; set +a; }; } && uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 api web

test: check-web
	cd backend && . .venv/bin/activate && python -m pytest -q

# Type-check and unit-test the web UI (fast; no browser needed).
check-web:
	cd frontend && npm run check

# MemoryAtlas vs. the retrieval baseline on the staged day. Needs MODEL_API_KEY; takes about an hour.
# Usage: make eval LABEL=my-run
eval:
	cd backend && . .venv/bin/activate && { [ ! -f ../.env ] || { set -a; . ../.env; set +a; }; } && python scripts/run_eval.py --label $(LABEL) --runs 3

# --- Docker: the whole app as separate services (see docs/DOCKER.md) --------------------------------
docker-up:
	docker compose up --build -d
	@echo "MemoryAtlas is starting at http://localhost:$${WEB_PORT:-8080}  (docker compose logs -f to watch)"

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# Needs MODEL_API_KEY in .env or the environment. Results land in ./eval/results/<EVAL_LABEL>.
docker-eval:
	HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose --profile eval run --rm eval
