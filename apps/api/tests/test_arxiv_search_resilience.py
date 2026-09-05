from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from fastapi import FastAPI

from scholarmind.api.routes import research as research_routes
from scholarmind.domain.errors import DomainError
from scholarmind.domain.research import ResearchSort
from scholarmind.services import arxiv_search
from scholarmind.services.arxiv_search import ArxivSearchClient, _retry_after_seconds
from scholarmind.services.research_analysis import LocalResearchAnalyzer

FEED = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/1706.03762v1</id><title>Attention Is All You Need</title>
<summary>A model based on attention.</summary>
<published>2017-06-12T00:00:00Z</published><updated>2017-06-12T00:00:00Z</updated>
</entry></feed>"""


@pytest.fixture
def backoff_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    clock = 100.0
    delays: list[float] = []
    original_sleep = asyncio.sleep

    async def sleep(seconds: float) -> None:
        nonlocal clock
        delays.append(seconds)
        clock += seconds
        await original_sleep(0)

    monkeypatch.setattr(arxiv_search, "monotonic", lambda: clock)
    monkeypatch.setattr(arxiv_search.asyncio, "sleep", sleep)
    yield delays


@pytest.mark.parametrize("failure", [408, 429, 503, "timeout", "connection", "protocol"])
async def test_transient_failure_recovers_without_changing_query(
    failure: int | str, backoff_clock: list[float]
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("temporary timeout", request=request)
            if failure == "connection":
                raise httpx.ConnectError("temporary connection failure", request=request)
            if failure == "protocol":
                raise httpx.RemoteProtocolError("disconnected", request=request)
            assert isinstance(failure, int)
            return httpx.Response(failure)
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        papers = await ArxivSearchClient(client, 3).search(
            '(all:"attention") AND cat:cs.CL', ResearchSort.RELEVANCE, 5
        )
    assert papers[0].arxiv_id == "1706.03762v1"
    assert len(requests) == 2
    assert requests[0].url == requests[1].url
    assert requests[0].url.host == "export.arxiv.org"
    assert backoff_clock == [3.0]


async def test_retry_exhaustion_is_bounded_and_does_not_leak_upstream_body(
    backoff_clock: list[float],
) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, text="private upstream diagnostics")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DomainError) as caught:
            await ArxivSearchClient(client, 3).search("all:attention", ResearchSort.RELEVANCE, 5)
    assert attempts == 3
    assert backoff_clock == [3.0, 6.0]
    assert caught.value.status_code == 503
    assert caught.value.code == "arxiv_temporarily_unavailable"
    assert "private" not in caught.value.message


@pytest.mark.parametrize("status", [400, 403, 404, 302])
async def test_permanent_failure_or_redirect_is_not_retried(status: int) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, headers={"Location": "https://evil.example/feed"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DomainError) as caught:
            await ArxivSearchClient(client, 0).search("all:attention", ResearchSort.RELEVANCE, 5)
    assert attempts == 1
    assert caught.value.code == "arxiv_search_failed"


async def test_retry_after_is_respected(backoff_clock: list[float]) -> None:
    responses = iter(
        [httpx.Response(429, headers={"Retry-After": "10"}), httpx.Response(200, content=FEED)]
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: next(responses))
    ) as client:
        papers = await ArxivSearchClient(client, 3).search(
            "all:attention", ResearchSort.RELEVANCE, 5
        )
    assert papers
    assert backoff_clock == [10.0]


async def test_long_retry_after_does_not_wait_or_retry_early(backoff_clock: list[float]) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        arxiv = ArxivSearchClient(client, 3, total_timeout_seconds=10)
        for _ in range(2):
            with pytest.raises(DomainError, match="longer pause"):
                await arxiv.search("all:attention", ResearchSort.RELEVANCE, 5)
    assert attempts == 1
    assert not backoff_clock


@pytest.mark.parametrize("value", [None, "invalid", "-10", "nan", "inf"])
def test_invalid_retry_after_is_safe(value: str | None) -> None:
    assert _retry_after_seconds(value) == 0


def test_retry_after_http_date() -> None:
    value = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    assert 28 <= _retry_after_seconds(value) <= 30


async def test_total_budget_covers_queued_requests_and_releases_lock() -> None:
    blocked = True

    async def handler(request: httpx.Request) -> httpx.Response:
        if blocked:
            await asyncio.Event().wait()
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        arxiv = ArxivSearchClient(client, 0, total_timeout_seconds=0.03)
        results = await asyncio.gather(
            arxiv.search("all:attention", ResearchSort.RELEVANCE, 5),
            arxiv.search("all:attention", ResearchSort.RELEVANCE, 5),
            return_exceptions=True,
        )
        assert all(isinstance(result, DomainError) for result in results)
        blocked = False
        assert await arxiv.search("all:attention", ResearchSort.RELEVANCE, 5)


async def test_attempt_timeout_recovers_within_total_budget(backoff_clock: list[float]) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            await asyncio.Event().wait()
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        arxiv = ArxivSearchClient(client, 3, attempt_timeout_seconds=0.01)
        assert await arxiv.search("all:attention", ResearchSort.RELEVANCE, 5)
    assert attempts == 2
    assert backoff_clock == [3.0]


async def test_cancellation_does_not_retry_and_releases_lock() -> None:
    started = asyncio.Event()
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            await asyncio.Event().wait()
        return httpx.Response(200, content=FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        arxiv = ArxivSearchClient(client, 0)
        task = asyncio.create_task(arxiv.search("all:attention", ResearchSort.RELEVANCE, 5))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert attempts == 1
        assert await arxiv.search("all:attention", ResearchSort.RELEVANCE, 5)
    assert attempts == 2


@pytest.mark.parametrize("content", [b"not XML", b"<html>upstream error</html>"])
async def test_malformed_feed_does_not_trigger_repeated_requests(content: bytes) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DomainError) as caught:
            await ArxivSearchClient(client, 0).search("all:attention", ResearchSort.RELEVANCE, 5)
    assert caught.value.code == "invalid_arxiv_response"
    assert attempts == 1


async def test_streaming_size_limit_stops_reading_and_closes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(arxiv_search, "_MAX_RESPONSE_BYTES", 32)
    chunks_read = 0
    closed = False

    class LargeFeed(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal chunks_read
            for _ in range(10):
                chunks_read += 1
                yield b"x" * 20

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=LargeFeed()))
    ) as client:
        with pytest.raises(DomainError) as caught:
            await ArxivSearchClient(client, 0).search("all:attention", ResearchSort.RELEVANCE, 5)
    assert caught.value.code == "arxiv_response_too_large"
    assert chunks_read == 2
    assert closed


async def test_topic_preparation_has_a_deadline_before_bff_timeout(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SlowAnalyzer(LocalResearchAnalyzer):
        async def plan_terms(self, topic: str) -> list[str]:
            await asyncio.Event().wait()
            return [topic]

    monkeypatch.setattr(research_routes, "_SEARCH_REQUEST_TIMEOUT_SECONDS", 0.03)
    app.state.research_analyzer = SlowAnalyzer()
    response = await client.post("/api/v1/research/search", json={"topic": "attention", "limit": 5})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "research_search_timeout"
