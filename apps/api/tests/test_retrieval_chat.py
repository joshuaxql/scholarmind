from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from scholarmind.db.models import PaperChunk
from scholarmind.domain.papers import PaperStatus
from scholarmind.services.embeddings import LocalHashEmbedding
from scholarmind.services.papers import PaperService
from scholarmind.services.retrieval import DatabaseRetriever, QdrantRetriever, _paper_filter


@pytest.mark.asyncio
async def test_database_retrieval_is_strictly_paper_scoped(app: FastAPI) -> None:
    sessions = app.state.database.session_factory
    async with sessions() as session:
        first = await PaperService(session).create("local-user", "2501.06713")
        second = await PaperService(session).create("local-user", "2201.08239")
        first.paper.status = PaperStatus.READY
        second.paper.status = PaperStatus.READY
        session.add_all(
            [
                PaperChunk(
                    paper_id=first.paper.id,
                    ordinal=0,
                    text="Alpha theorem proves spectral convergence.",
                    page_number=3,
                    section="Theorem",
                    token_count=7,
                    content_sha256="a" * 64,
                ),
                PaperChunk(
                    paper_id=second.paper.id,
                    ordinal=0,
                    text="Beta corpus evaluates conversational agents.",
                    page_number=8,
                    section="Results",
                    token_count=7,
                    content_sha256="b" * 64,
                ),
            ]
        )
        await session.commit()
        results = await DatabaseRetriever().retrieve(
            session,
            first.paper.id,
            first.paper.retrieval_namespace or "",
            "spectral convergence",
            5,
        )
    assert len(results) == 1
    assert "Alpha theorem" in results[0].text
    assert "Beta corpus" not in results[0].text
    assert results[0].page_number == 3


@pytest.mark.asyncio
async def test_streaming_chat_contract_persists_cited_conversation(
    client: httpx.AsyncClient,
    app: FastAPI,
) -> None:
    async with app.state.database.session_factory() as session:
        created = await PaperService(session).create("local-user", "2501.06713")
        created.paper.status = PaperStatus.READY
        session.add(
            PaperChunk(
                paper_id=created.paper.id,
                ordinal=0,
                text="The method converges because the objective is strongly convex.",
                page_number=4,
                section="Proof",
                token_count=12,
                content_sha256="c" * 64,
            )
        )
        await session.commit()
        paper_id = created.paper.id

    response = await client.post(
        f"/api/v1/papers/{paper_id}/chat/stream",
        json={"query": "Why does the method converge?"},
        headers={"accept": "text/event-stream"},
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    meta = next(data for event, data in events if event == "meta")
    tokens = [data["text"] for event, data in events if event == "token"]
    assert meta["citations"][0]["page_number"] == 4
    assert tokens and "strongly convex" in "".join(tokens)
    assert events[-1][0] == "done"

    conversation = await client.get(
        f"/api/v1/papers/{paper_id}/conversations/{meta['conversation_id']}"
    )
    assert conversation.status_code == 200
    assert [message["role"] for message in conversation.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation.json()["messages"][1]["citations"][0]["source_id"] == "S1"

    history = await client.get(f"/api/v1/papers/{paper_id}/conversations")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == meta["conversation_id"]
    assert history.json()["items"][0]["title"] == "Why does the method converge?"
    assert len(history.json()["items"][0]["messages"]) == 2


@pytest.mark.asyncio
async def test_qdrant_query_filter_contains_paper_and_namespace() -> None:
    paper_id = uuid4()
    query_filter = _paper_filter(paper_id, f"paper-{paper_id.hex}")
    conditions = {condition.key: condition.match.value for condition in query_filter.must or []}
    assert conditions == {
        "paper_id": str(paper_id),
        "namespace": f"paper-{paper_id.hex}",
    }


@pytest.mark.asyncio
async def test_qdrant_failure_falls_back_to_scoped_database(app: FastAPI) -> None:
    class BrokenQdrant:
        async def query_points(self, **kwargs: object) -> object:
            raise RuntimeError("offline")

        async def close(self) -> None:
            return None

        async def get_collections(self) -> object:
            return SimpleNamespace(collections=[])

    async with app.state.database.session_factory() as session:
        created = await PaperService(session).create("local-user", "2502.00001")
        created.paper.status = PaperStatus.READY
        session.add(
            PaperChunk(
                paper_id=created.paper.id,
                ordinal=0,
                text="Fallback evidence lives in PostgreSQL.",
                page_number=2,
                token_count=7,
                content_sha256="d" * 64,
            )
        )
        await session.commit()
        retriever = QdrantRetriever(
            BrokenQdrant(),  # type: ignore[arg-type]
            "chunks",
            LocalHashEmbedding(64),
            DatabaseRetriever(),
        )
        results = await retriever.retrieve(
            session,
            created.paper.id,
            created.paper.retrieval_namespace or "",
            "fallback evidence",
            3,
        )
    assert results[0].page_number == 2


def _parse_sse(raw: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in raw.strip().replace("\r\n", "\n").split("\n\n"):
        event = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data += line.removeprefix("data:").strip()
        events.append((event, json.loads(data)))
    return events
