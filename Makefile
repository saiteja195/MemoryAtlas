.PHONY: setup dev test api web check-web mobile-api

setup:
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
	cd frontend && npm install

api:
	cd backend && . .venv/bin/activate && { [ ! -f ../.env ] || { set -a; . ../.env; set +a; }; } && uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

# Explicit opt-in: set MEMORYATLAS_MOBILE_HOST=0.0.0.0 for a trusted LAN.
mobile-api:
	cd backend && . .venv/bin/activate && { [ ! -f ../.env ] || { set -a; . ../.env; set +a; }; } && uvicorn app.mobile_main:app --host $${MEMORYATLAS_MOBILE_HOST:-127.0.0.1} --port 8001

dev:
	$(MAKE) -j2 api web

test: check-web
	cd backend && . .venv/bin/activate && python -m pytest -q

# Type-check and unit-test the web UI (fast; no browser needed).
check-web:
	cd frontend && npm run check
