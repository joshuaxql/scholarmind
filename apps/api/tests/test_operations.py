from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from scholarmind.core.config import Environment, Settings
from scholarmind.db.models import Paper, PaperChunk
from scholarmind.domain.papers import PaperStatus
from scholarmind.main import create_app
from scholarmind.services.papers import PaperService
from scholarmind.services.retention import delete_expired_papers


class DeletionIndex:
    def __init__(self) -> None:
        self.deleted: list[UUID] = []

    async def delete_paper(self, paper_id: UUID) -> None:
        self.deleted.append(paper_id)

    async def index(self, paper_id: UUID, namespace: str, chunks: list[object]) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_health_metrics_and_security_headers(client: httpx.AsyncClient) -> None:
    ready = await client.get("/health/ready", headers={"x-request-id": "ops-check"})
    metrics = await client.get("/metrics")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {
        "database": "ok",
        "storage": "ok",
        "retrieval": "ok",
    }
    assert ready.headers["x-request-id"] == "ops-check"
    assert "scholarmind_http_requests_total" in metrics.text
    assert "scholarmind_ingestion_jobs_total" in metrics.text
    assert ready.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_single_process_production_readiness_does_not_require_redis(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        auth_required=True,
        api_bearer_token="a-production-token-that-is-at-least-32-characters",
        cors_origins=["https://papers.example"],
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'production.db'}",
        local_storage_path=tmp_path / "objects",
        queue_mode="inline",
    )
    production_app = create_app(settings)
    async with (
        production_app.router.lifespan_context(production_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=production_app),
            base_url="http://test",
        ) as production_client,
    ):
        ready = await production_client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {
        "database": "ok",
        "storage": "ok",
        "retrieval": "ok",
    }


@pytest.mark.asyncio
async def test_retention_deletes_objects_vectors_and_cascading_rows(app: FastAPI) -> None:
    database = app.state.database
    storage = app.state.object_store
    async with database.session_factory() as session:
        created = await PaperService(session).create("local-user", "2501.06713")
        paper = created.paper
        paper.status = PaperStatus.READY
        paper.created_at = datetime.now(UTC) - timedelta(days=100)
        paper.pdf_object_key = f"papers/{paper.id}/source.pdf"
        paper.markdown_object_key = f"papers/{paper.id}/document.md"
        session.add(
            PaperChunk(
                paper_id=paper.id,
                ordinal=0,
                text="old",
                token_count=1,
                content_sha256="e" * 64,
            )
        )
        await session.commit()
        paper_id = paper.id

    await storage.put_bytes(f"papers/{paper_id}/source.pdf", b"pdf", "application/pdf")
    await storage.put_bytes(f"papers/{paper_id}/document.md", b"md", "text/markdown")
    index = DeletionIndex()
    deleted = await delete_expired_papers(
        database.session_factory,
        storage,
        index,  # type: ignore[arg-type]
        retention_days=90,
    )
    async with database.session_factory() as session:
        papers = await session.scalar(select(func.count()).select_from(Paper))
        chunks = await session.scalar(select(func.count()).select_from(PaperChunk))
    assert deleted == 1
    assert papers == 0 and chunks == 0
    assert index.deleted == [paper_id]
    assert storage.local_path(f"papers/{paper_id}/source.pdf") is None
