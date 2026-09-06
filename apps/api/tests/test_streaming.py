from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from test_research import StubArxivSearch

from scholarmind.api import streaming
from scholarmind.core.config import Settings
from scholarmind.services.llm_stream import stream_completion
from scholarmind.services.research import ResearchService
from scholarmind.services.research_analysis import LocalResearchAnalyzer, OpenAIResearchAnalyzer


def frame(text: str) -> bytes:
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n").encode()


def configured() -> Settings:
    return Settings(llm_base_url="https://model.example/v1", llm_api_key="test", llm_model="test")


async def test_terms_reach_callback_before_provider_finishes() -> None:
    first = asyncio.Event()
    release = asyncio.Event()
    received: list[str] = []

    class GatedStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield frame('{"terms":["embodied')
            await release.wait()
            yield frame(' intelligence"]}')
            yield b"data: [DONE]\n\n"

    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, stream=GatedStream())

    async def token(text: str) -> None:
        received.append(text)
        first.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        analyzer = OpenAIResearchAnalyzer(client, configured())
        task = asyncio.create_task(analyzer.plan_terms("具身智能", on_token=token))
        try:
            await asyncio.wait_for(first.wait(), 1)
            assert received == ['{"terms":["embodied']
            assert not task.done()
            release.set()
            assert await task == ["embodied intelligence"]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("ending", [b"", b'data: {"choices":[{"finish_reason":"length"}]}\n\n'])
async def test_provider_truncation_is_not_success(ending: bytes) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=frame("Partial answer") + ending)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = stream_completion(client, "https://model.example", "test", {})
        assert await anext(tokens) == "Partial answer"
        with pytest.raises(RuntimeError):
            await anext(tokens)


async def test_provider_reasoning_is_not_forwarded() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                b'data: {"choices":[{"delta":{"reasoning_content":"private reasoning"}}]}\n\n'
                + frame("Answer")
                + b"data: [DONE]\n\n"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert [
            t async for t in stream_completion(client, "https://model.example", "test", {})
        ] == ["Answer"]


async def test_heartbeat_and_close_cancel_the_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(streaming, "HEARTBEAT_SECONDS", 0.01)
    cancelled = asyncio.Event()

    async def operation(emit: streaming.EventSink) -> object:
        try:
            await emit("token", {"text": "visible"})
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    events = streaming.keep_alive(streaming.operation_events(operation, {"stage": "analyzing"}))
    assert b"event: meta" in await anext(events)
    assert b"visible" in await anext(events)
    assert await anext(events) == b": keep-alive\n\n"
    assert not cancelled.is_set()
    await events.aclose()
    assert cancelled.is_set()


async def test_generation_deadline_emits_error_instead_of_done() -> None:
    async def operation(emit: streaming.EventSink) -> object:
        await asyncio.Event().wait()

    events = [event async for event in streaming.operation_events(operation, {}, duration=0.01)]
    assert b"generation_timeout" in events[-1]
    assert all(b"event: done" not in event for event in events)


@pytest.mark.parametrize("valid", [True, False])
async def test_report_tokens_precede_validated_completion(
    app: FastAPI,
    client: httpx.AsyncClient,
    valid: bool,
) -> None:
    app.state.arxiv_search_client = StubArxivSearch()
    created = await client.post("/api/v1/research/search/stream", json={"topic": "retrieval"})
    blocks = created.text.split("\n\n")
    done = next(b for b in blocks if b.startswith("event: done"))
    search = json.loads(done.split("data: ")[1])["search"]
    report = await LocalResearchAnalyzer().analyze("retrieval", "retrieval", search["results"])
    payload: dict[str, Any] = report.model_dump()
    if not valid:
        payload["themes"][0]["paper_ids"] = ["P999"]
    content = json.dumps(payload)

    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200, content=frame(content[:80]) + frame(content[80:]) + b"data: [DONE]\n\n"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as provider:
        app.state.research_analyzer = OpenAIResearchAnalyzer(provider, configured())
        response = await client.post(f"/api/v1/research/{search['id']}/analyze/stream")
    text = response.text
    assert text.index("event: meta") < text.index("event: token")
    stored = (await client.get(f"/api/v1/research/{search['id']}")).json()
    if valid:
        assert text.index("event: token") < text.index("event: done")
        assert stored["status"] == "complete"
        assert stored["report"]["overview"] == report.overview
    else:
        assert "event: error" in text and "event: done" not in text
        assert stored["status"] == "failed" and stored["report"] is None


async def test_cancelled_report_can_be_retried(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.arxiv_search_client = StubArxivSearch()
    search = (await client.post("/api/v1/research/search", json={"topic": "retrieval"})).json()
    started = asyncio.Event()

    class WaitingAnalyzer(LocalResearchAnalyzer):
        async def analyze(self, *args: Any, **kwargs: Any) -> Any:
            started.set()
            await asyncio.Event().wait()

    service = ResearchService(
        app.state.database.session_factory, app.state.arxiv_search_client, WaitingAnalyzer(), 0
    )
    task = asyncio.create_task(service.analyze("local-user", UUID(search["id"])))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = await service.get("local-user", UUID(search["id"]))
    assert stored.status.value == "failed" and stored.report is None
    service.analyzer = LocalResearchAnalyzer()
    await service.analyze("local-user", stored.id)
    assert (await service.get("local-user", stored.id)).status.value == "complete"


async def test_report_exhausted_budget_has_actionable_error() -> None:
    from scholarmind.domain.errors import DomainError

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=(b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n')
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(DomainError) as caught:
            await OpenAIResearchAnalyzer(client, configured()).plan_terms("多模态")
    assert caught.value.code == "model_output_limit"
    assert "LLM_MAX_OUTPUT_TOKENS" in caught.value.message
