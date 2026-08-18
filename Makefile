ifeq ($(OS),Windows_NT)
ROOT_PYTHON ?= .venv/Scripts/python.exe
PYTHON ?= ../../.venv/Scripts/python.exe
else
ROOT_PYTHON ?= .venv/bin/python
PYTHON ?= ../../.venv/bin/python
endif

.PHONY: api-dev api-test api-lint contracts-check web-dev web-build web-lint web-typecheck web-test

api-dev:
	$(ROOT_PYTHON) -m uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8000 --env-file .env

api-test:
	cd apps/api && $(PYTHON) -m pytest

api-lint:
	cd apps/api && $(PYTHON) -m ruff check .

contracts-check:
	$(ROOT_PYTHON) scripts/generate_openapi_snapshot.py --check
	$(ROOT_PYTHON) scripts/generate_ts_client.py --check

web-dev:
	npm run dev:web

web-build:
	npm run build:web

web-lint:
	npm run lint:web

web-typecheck:
	npm run typecheck:web

web-test:
	npm run test:web
