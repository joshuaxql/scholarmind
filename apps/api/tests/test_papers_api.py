from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from scholarmind.core.config import Environment, Settings
from scholarmind.db.models import Paper
from scholarmind.db.session import Database
from scholarmind.main import create_app
from scholarmind.services.papers import PaperService


class FailingDispatcher:
    async def enqueue(self, job_id: object, request_id: str | None = None) -> str:
        raise ConnectionError("queue offline")

    async def close(self) -> None:
        return None


class RecordingDispatcher:
    def __init__(self) -> None:
        self.job_ids: list[object] = []

    async def enqueue(self, job_id: object, request_id: str | None = None) -> str:
        self.job_ids.append(job_id)
        return f"recovered:{job_id}"

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_get_list_is_idempotent_and_propagates_request_id(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    headers = {"x-request-id": "contract-test-01"}
    first = await client.post("/api/v1/papers", json={"arxiv": "2501.06713"}, headers=headers)
    second = await client.post("/api/v1/papers", json={"arxiv": "https://arxiv.org/abs/2501.06713"})

    assert first.status_code == 202
    assert first.headers["x-request-id"] == "contract-test-01"
    assert first.json()["created"] is True
    assert second.status_code == 202
    assert second.json()["created"] is False
    assert second.json()["paper"]["id"] == first.json()["paper"]["id"]

    paper_id = first.json()["paper"]["id"]
    detail = await client.get(f"/api/v1/papers/{paper_id}")
    collection = await client.get("/api/v1/papers?limit=10&offset=0")
    assert detail.status_code == 200
    assert detail.json()["latest_job"]["progress"] == 0
    assert collection.json()["total"] == 1
    assert len(app.state.job_dispatcher.enqueued) == 2
    assert app.state.job_dispatcher.enqueued[0][0] == app.state.job_dispatcher.enqueued[1][0]
    assert app.state.job_dispatcher.enqueued[0][1] == "contract-test-01"


@pytest.mark.asyncio
async def test_repeated_submission_repairs_failed_queue_handoff(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    app.state.job_dispatcher = FailingDispatcher()
    failed = await client.post("/api/v1/papers", json={"arxiv": "2502.00002"})
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "queue_unavailable"

    dispatcher = RecordingDispatcher()
    app.state.job_dispatcher = dispatcher
    recovered = await client.post("/api/v1/papers", json={"arxiv": "2502.00002"})
    assert recovered.status_code == 202
    assert recovered.json()["created"] is False
    assert len(dispatcher.job_ids) == 1

    app.state.job_dispatcher = FailingDispatcher()
    failed_retry_handoff = await client.post("/api/v1/papers", json={"arxiv": "2502.00003"})
    assert failed_retry_handoff.status_code == 503
    papers = (await client.get("/api/v1/papers?limit=10")).json()["items"]
    queued_id = next(item["id"] for item in papers if item["arxiv_id"] == "2502.00003")
    app.state.job_dispatcher = dispatcher
    retried = await client.post(f"/api/v1/papers/{queued_id}/retry")
    assert retried.status_code == 202
    assert retried.json()["created"] is False
    assert len(dispatcher.job_ids) == 2


@pytest.mark.asyncio
async def test_api_returns_stable_validation_and_not_found_errors(
    client: httpx.AsyncClient,
) -> None:
    invalid = await client.post("/api/v1/papers", json={"arxiv": "http://evil.example/a"})
    missing = await client.get("/api/v1/papers/00000000-0000-0000-0000-000000000001")

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_arxiv_identifier"
    assert invalid.json()["error"]["request_id"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource_not_found"
    assert missing.headers["x-content-type-options"] == "nosniff"
    assert missing.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_concurrent_paper_creation_has_one_database_row(tmp_path: Path) -> None:
    settings = Settings(
        environment=Environment.TEST,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'concurrent.sqlite'}",
    )
    database = Database(settings)
    await database.create_schema()

    async def create() -> str:
        async with database.session_factory() as session:
            result = await PaperService(session).create("owner", "2501.06713")
            return str(result.paper.id)

    ids = await asyncio.gather(create(), create())
    async with database.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Paper))
    await database.close()
    assert ids[0] == ids[1]
    assert count == 1


@pytest.mark.asyncio
async def test_bearer_authentication_is_enforced(tmp_path: Path) -> None:
    token = "test-token-with-at-least-thirty-two-characters"
    settings = Settings(
        environment=Environment.TEST,
        auth_required=True,
        api_bearer_token=token,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'auth.sqlite'}",
        local_storage_path=tmp_path / "objects",
    )
    application = create_app(settings)
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application, raise_app_exceptions=False),
            base_url="http://test",
        ) as api_client,
    ):
        rejected = await api_client.get("/api/v1/papers")
        accepted = await api_client.get(
            "/api/v1/papers", headers={"authorization": f"Bearer {token}"}
        )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "invalid_credentials"
    assert accepted.status_code == 200
