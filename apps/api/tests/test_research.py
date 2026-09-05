from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from scholarmind.domain.research import ResearchSort
from scholarmind.services.arxiv_search import (
    ArxivSearchClient,
    ArxivSearchPaper,
    build_query_expression,
)


class StubArxivSearch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ResearchSort, int]] = []

    async def search(
        self,
        query_expression: str,
        sort: ResearchSort,
        limit: int,
    ) -> list[ArxivSearchPaper]:
        self.calls.append((query_expression, sort, limit))
        return [
            ArxivSearchPaper(
                arxiv_id="2501.06713v1",
                title="Grounded Retrieval Systems",
                authors=["Ada Researcher", "Lin Scholar"],
                abstract="We study retrieval systems and identify evaluation limitations.",
                published_at=datetime(2025, 1, 12, tzinfo=UTC),
                updated_at=datetime(2025, 1, 13, tzinfo=UTC),
                categories=["cs.AI", "cs.CL"],
                primary_category="cs.AI",
                abstract_url="https://arxiv.org/abs/2501.06713v1",
                pdf_url="https://arxiv.org/pdf/2501.06713v1.pdf",
            )
        ]


def test_build_query_expression_escapes_terms_and_applies_filters() -> None:
    expression = build_query_expression(
        ['retrieval "augmented" generation'],
        ["cs.AI", "cs.CL"],
        "2024-01-01",
        "2025-01-31",
    )

    assert expression == (
        '(all:"retrieval augmented generation") AND (cat:cs.AI OR cat:cs.CL) '
        "AND submittedDate:[202401010000 TO 202501312359]"
    )


@pytest.mark.asyncio
async def test_arxiv_search_client_parses_atom_feed() -> None:
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2501.06713v2</id>
        <updated>2025-01-14T00:00:00Z</updated>
        <published>2025-01-12T00:00:00Z</published>
        <title>  A grounded   paper </title>
        <summary> Evidence from abstracts. </summary>
        <author><name>Ada Researcher</name></author>
        <category term="cs.AI" />
        <arxiv:primary_category term="cs.AI" />
      </entry>
    </feed>"""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "export.arxiv.org"
        assert request.url.params["sortBy"] == "relevance"
        return httpx.Response(200, content=feed)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        papers = await ArxivSearchClient(client, min_interval_seconds=0).search(
            'all:"grounded paper"',
            ResearchSort.RELEVANCE,
            10,
        )

    assert len(papers) == 1
    assert papers[0].arxiv_id == "2501.06713v2"
    assert papers[0].title == "A grounded paper"
    assert papers[0].primary_category == "cs.AI"


@pytest.mark.asyncio
async def test_research_api_searches_caches_and_analyzes(
    app: FastAPI,
    client: httpx.AsyncClient,
) -> None:
    arxiv = StubArxivSearch()
    app.state.arxiv_search_client = arxiv
    payload = {
        "topic": "retrieval augmented generation",
        "categories": ["cs.AI"],
        "published_from": "2024-01-01",
        "published_to": None,
        "sort": "relevance",
        "limit": 10,
    }

    created = await client.post("/api/v1/research/search", json=payload)
    assert created.status_code == 200
    body = created.json()
    assert body["cached"] is False
    assert body["results"][0]["source_id"] == "P1"
    assert body["results"][0]["arxiv_id"] == "2501.06713v1"
    assert "cat:cs.AI" in body["query_expression"]

    cached = await client.post("/api/v1/research/search", json=payload)
    assert cached.status_code == 200
    assert cached.json()["cached"] is True
    assert len(arxiv.calls) == 1

    analyzed = await client.post(
        f"/api/v1/research/{body['id']}/analyze/stream",
        headers={"Accept": "text/event-stream"},
    )
    assert analyzed.status_code == 200
    assert "event: meta" in analyzed.text
    assert "event: done" in analyzed.text
    assert '"report"' in analyzed.text

    loaded = await client.get(f"/api/v1/research/{body['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["status"] == "complete"
    assert loaded.json()["report"]["bottlenecks"][0]["paper_ids"] == ["P1"]
