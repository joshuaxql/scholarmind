from __future__ import annotations

from time import perf_counter
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from scholarmind.db.models import ChatMessage, Conversation, Paper, ResearchSearch
from scholarmind.domain.papers import MessageRole
from scholarmind.services.chat import ChatService, PreparedChat
from scholarmind.services.papers import PaperService


async def seed(app: FastAPI, owner: str = "local-user") -> tuple[UUID, UUID, UUID, UUID]:
    async with app.state.database.session_factory() as session:
        first = await PaperService(session).create(owner, "1706.03762")
        second = await PaperService(session).create(owner, "2501.06713")
        conversation = Conversation(paper_id=first.paper.id, owner_id=owner, title="Delete me")
        conversation.messages = [
            ChatMessage(role=MessageRole.USER, content="Question"),
            ChatMessage(role=MessageRole.ASSISTANT, content="Answer"),
        ]
        search = ResearchSearch(
            owner_id=owner,
            topic="History test",
            request_key="a" * 64,
            query_expression='all:"test"',
            filters={},
            results=[],
        )
        session.add_all([conversation, search])
        await session.commit()
        return first.paper.id, second.paper.id, conversation.id, search.id


@pytest.mark.asyncio
async def test_deleting_conversation_removes_messages_but_preserves_paper(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id, _, conversation_id, _ = await seed(app)
    path = f"/api/v1/papers/{paper_id}/conversations/{conversation_id}"
    response = await client.delete(path)
    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(path)).status_code == 404
    collection = (await client.get(f"/api/v1/papers/{paper_id}/conversations")).json()
    assert collection["items"] == []
    assert collection["total"] == 0
    async with app.state.database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ChatMessage)) == 0
        assert await session.get(Paper, paper_id) is not None


@pytest.mark.asyncio
async def test_deleting_research_removes_it_from_list_and_direct_access(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    _, _, _, search_id = await seed(app)
    path = f"/api/v1/research/{search_id}"
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(path)).status_code == 404
    assert (await client.post(f"{path}/analyze/stream")).status_code == 404
    assert (await client.get("/api/v1/research")).json()["total"] == 0
    async with app.state.database.session_factory() as session:
        assert await session.get(ResearchSearch, search_id) is None


@pytest.mark.asyncio
async def test_removing_recent_paper_preserves_content_and_resubmission_restores_history(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id, other_id, conversation_id, _ = await seed(app)
    path = f"/api/v1/papers/{paper_id}"
    assert (await client.delete(f"{path}/history")).status_code == 204
    assert (await client.delete(f"{path}/history")).status_code == 204
    listed = (await client.get("/api/v1/papers")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == str(other_id)
    assert (await client.get(path)).status_code == 200
    assert (await client.get(f"{path}/conversations/{conversation_id}")).status_code == 200
    restored = await client.post("/api/v1/papers", json={"arxiv": "1706.03762"})
    assert restored.json()["paper"]["id"] == str(paper_id)
    assert restored.json()["created"] is False
    assert (await client.get("/api/v1/papers")).json()["total"] == 2


@pytest.mark.parametrize("kind", ["research", "conversation", "paper_history"])
@pytest.mark.asyncio
async def test_deletion_cannot_target_another_owner(
    kind: str, app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id, _, conversation_id, search_id = await seed(app, "another-owner")
    paths = {
        "research": f"/api/v1/research/{search_id}",
        "conversation": f"/api/v1/papers/{paper_id}/conversations/{conversation_id}",
        "paper_history": f"/api/v1/papers/{paper_id}/history",
    }
    assert (await client.delete(paths[kind])).status_code == 404
    async with app.state.database.session_factory() as session:
        assert await session.get(Conversation, conversation_id) is not None
        assert await session.get(ResearchSearch, search_id) is not None
        paper = await session.get(Paper, paper_id)
        assert paper is not None and not paper.history_hidden


@pytest.mark.asyncio
async def test_conversation_deletion_checks_paper_id(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id, other_id, conversation_id, _ = await seed(app)
    assert (
        await client.delete(f"/api/v1/papers/{other_id}/conversations/{conversation_id}")
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/papers/{paper_id}/conversations/{conversation_id}")
    ).status_code == 200


@pytest.mark.asyncio
async def test_late_stream_answer_does_not_recreate_deleted_conversation(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    paper_id, _, conversation_id, _ = await seed(app)
    await client.delete(f"/api/v1/papers/{paper_id}/conversations/{conversation_id}")
    service = ChatService(
        app.state.database.session_factory, app.state.retriever, app.state.llm_gateway, 4000
    )
    await service.save_assistant(
        PreparedChat(conversation_id, "Question", "Context", [], [], perf_counter()), "Late answer"
    )
    async with app.state.database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ChatMessage)) == 0
