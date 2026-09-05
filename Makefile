PYTHON ?= python
VENV_PYTHON := $(if $(wildcard .venv/Scripts/python.exe),$(CURDIR)/.venv/Scripts/python.exe,$(CURDIR)/.venv/bin/python)

.PHONY: setup start start-production dev-api dev-worker dev-web lint test build

setup:
	$(PYTHON) scripts/setup.py

start:
	$(PYTHON) scripts/start.py --reload

start-production:
	$(PYTHON) scripts/start.py --production

dev-api:
	$(VENV_PYTHON) -m uvicorn scholarmind.main:app --app-dir apps/api --reload --port 8000

dev-worker:
	$(VENV_PYTHON) -m arq scholarmind.workers.settings.WorkerSettings

dev-web:
	npm --prefix apps/web run dev

lint:
	cd apps/api && $(VENV_PYTHON) -m ruff check scholarmind tests alembic ../../scripts
	cd apps/api && $(VENV_PYTHON) -m ruff format --check scholarmind tests alembic ../../scripts
	cd apps/api && $(VENV_PYTHON) -m mypy scholarmind
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck

test:
	cd apps/api && $(VENV_PYTHON) -m pytest
	npm --prefix apps/web test

build:
	npm --prefix apps/web run build
