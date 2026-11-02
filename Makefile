.PHONY: setup dev test api web check-web eval

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
