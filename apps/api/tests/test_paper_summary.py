from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from scholarmind.db.models import PaperChunk, PaperSummary
from scholarmind.domain.papers import PaperStatus
from scholarmind.services.papers import PaperService


async def seed_ready_paper(app: FastAPI, arxiv: str = "2501.06713") -> UUID:
    async with app.state.database.session_factory() as session:
        creation = await PaperService(session).create("local-user", arxiv)
        creation.paper.status = PaperStatus.READY
        creation.paper.title = "A Study of Attention"
        creation.paper.abstract = (
            "Attention mechanisms dominate modern architectures. We study their limits. "
            "We find scaling helps until saturation. We discuss failure modes. We close with "
            "open questions."
        )
        session.add(
            PaperChunk(
                paper_id=creation.paper.id,
                ordinal=0,
                text="We propose a new attention variant and prove convergence.",
                page_number=1,
                section="Introduction",
                token_count=10,
                content_sha256="a" * 64,
            )
        )
        await session.commit()
        return creation.paper.id


@pytest.mark.asyncio
async def test_summary_is_pending_before_generation(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id = await seed_ready_paper(app)
    response = await client.get(f"/api/v1/papers/{paper_id}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["content"] is None


@pytest.mark.asyncio
async def test_generate_summary_persists_and_serves_cached_briefing(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id = await seed_ready_paper(app)
    created = await client.post(f"/api/v1/papers/{paper_id}/summary", json={"language": "en"})
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "ready"
    assert body["language"] == "en"
    assert "Attention mechanisms" in body["content"]["tldr"]
    assert body["error_code"] is None

    fetched = await client.get(f"/api/v1/papers/{paper_id}/summary")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == body["content"]

    async with app.state.database.session_factory() as session:
        summaries = list(await session.scalars(select(PaperSummary)))
        assert len(summaries) == 1


@pytest.mark.asyncio
async def test_generate_summary_rejects_paper_not_ready(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async with app.state.database.session_factory() as session:
        creation = await PaperService(session).create("local-user", "2201.08239")
        await session.commit()
        paper_id = creation.paper.id
    response = await client.post(f"/api/v1/papers/{paper_id}/summary", json={"language": "en"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "paper_not_ready"


@pytest.mark.asyncio
async def test_summary_requires_paper_ownership(app: FastAPI, client: httpx.AsyncClient) -> None:
    paper_id = await seed_ready_paper(app)
    missing = await client.get(f"/api/v1/papers/{uuid4()}/summary")
    assert missing.status_code == 404
    # Unowned paper id must not leak summaries even if it exists.
    response = await client.post(f"/api/v1/papers/{paper_id}/summary", json={"language": "zh"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_failure_is_persisted_without_faking_success(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id = await seed_ready_paper(app, arxiv="1706.03762")

    class FailingAnalyzer:
        async def summarize(self, title, abstract, context, language):
            raise RuntimeError("model offline")

    app.state.briefing_analyzer = FailingAnalyzer()
    response = await client.post(f"/api/v1/papers/{paper_id}/summary", json={"language": "en"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "briefing_generation_failed"

    stored = await client.get(f"/api/v1/papers/{paper_id}/summary")
    assert stored.status_code == 200
    assert stored.json()["status"] == "failed"
    assert stored.json()["content"] is None
    assert stored.json()["error_code"] == "briefing_generation_failed"


@pytest.mark.asyncio
async def test_refresh_regenerates_and_changes_language(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id = await seed_ready_paper(app, arxiv="2401.04088")
    first = await client.post(f"/api/v1/papers/{paper_id}/summary", json={"language": "en"})
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/papers/{paper_id}/summary", json={"language": "zh", "refresh": True}
    )
    assert second.status_code == 200
    assert second.json()["language"] == "zh"
    assert "配置语言模型" in second.json()["content"]["methodology"]
