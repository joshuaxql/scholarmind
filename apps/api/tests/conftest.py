from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from scholarmind.core.config import Environment, Settings
from scholarmind.main import create_app


class StubDispatcher:
    def __init__(self) -> None:
        self.enqueued: list[tuple[UUID, str | None]] = []

    async def enqueue(self, job_id: UUID, request_id: str | None = None) -> str:
        self.enqueued.append((job_id, request_id))
        return f"test:{job_id}"

    async def close(self) -> None:
        return None


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
        redis_url="redis://127.0.0.1:1/15",
        queue_mode="inline",
        storage_backend="local",
        local_storage_path=tmp_path / "objects",
        retrieval_backend="database",
        auth_required=False,
        auto_create_schema=True,
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
        embedding_base_url=None,
        embedding_api_key=None,
        embedding_model=None,
    )


@pytest_asyncio.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        application.state.job_dispatcher = StubDispatcher()
        yield application


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client
