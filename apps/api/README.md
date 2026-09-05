# ScholarMind API

FastAPI backend for secure arXiv ingestion, local database vector retrieval, and paper-scoped grounded chat over OpenAI-compatible APIs.

## Run from repository root

```bash
python scripts/setup.py
# configure .env
python scripts/start.py --api-only --reload
```

The launcher applies Alembic migrations first. Defaults require no additional local services: SQLite, inline jobs, local object storage, database retrieval, local hash embeddings, and a local grounded gateway.

Configure remote models in the root `.env`:

```dotenv
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=...
LLM_MODEL=...

EMBEDDING_BASE_URL=https://provider.example/v1
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=...
```

ScholarMind appends `/chat/completions` and `/embeddings` to the corresponding API roots.

## Commands

```bash
.venv/bin/python -m alembic -c apps/api/alembic.ini upgrade head
.venv/bin/python -m uvicorn scholarmind.main:app --app-dir apps/api --reload

cd apps/api
../../.venv/bin/ruff check scholarmind tests
../../.venv/bin/ruff format --check scholarmind tests
../../.venv/bin/mypy scholarmind
../../.venv/bin/pytest
```

On Windows, use `.venv\Scripts\python.exe`. See the root [README](../../README.md) and [architecture](../../docs/architecture.md) for configuration, API contracts, and invariants.
