from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from time import monotonic
from xml.etree.ElementTree import Element

import httpx
import structlog
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from scholarmind.core.config import Settings
from scholarmind.domain.arxiv import parse_arxiv_identifier
from scholarmind.domain.errors import DomainError
from scholarmind.domain.research import ResearchSort

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_SEARCH_ENDPOINT = "https://export.arxiv.org/api/query"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
logger = structlog.get_logger(__name__)
_SORT_FIELDS = {
    ResearchSort.RELEVANCE: "relevance",
    ResearchSort.SUBMITTED_DATE: "submittedDate",
    ResearchSort.UPDATED_DATE: "lastUpdatedDate",
}


@dataclass(frozen=True, slots=True)
class ArxivSearchPaper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime
    updated_at: datetime
    categories: list[str]
    primary_category: str | None
    abstract_url: str
    pdf_url: str


class ArxivSearchClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        min_interval_seconds: float,
        *,
        max_attempts: int = 3,
        attempt_timeout_seconds: float = 20.0,
        total_timeout_seconds: float = 65.0,
    ) -> None:
        self.client = client
        self.min_interval_seconds = min_interval_seconds
        self.max_attempts = max_attempts
        self.attempt_timeout_seconds = attempt_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def search(
        self,
        query_expression: str,
        sort: ResearchSort,
        limit: int,
    ) -> list[ArxivSearchPaper]:
        params: dict[str, str | int] = {
            "search_query": query_expression,
            "start": 0,
            "max_results": limit,
            "sortBy": _SORT_FIELDS[sort],
            "sortOrder": "descending",
        }
        deadline = monotonic() + self.total_timeout_seconds
        try:
            # Include queueing, backoff and every attempt in one bounded budget.
            async with asyncio.timeout(self.total_timeout_seconds), self._request_lock:
                content = await self._fetch_with_retries(params, deadline)
        except TimeoutError as exc:
            logger.warning("arxiv_search_budget_exhausted")
            raise _unavailable("arXiv search timed out; please retry shortly") from exc

        try:
            return _parse_feed(content)
        except (ElementTree.ParseError, DefusedXmlException, ValueError, DomainError) as exc:
            raise DomainError(
                code="invalid_arxiv_response",
                message="arXiv returned an invalid search response",
                status_code=502,
            ) from exc

    async def _fetch_with_retries(self, params: dict[str, str | int], deadline: float) -> bytes:
        for attempt in range(1, self.max_attempts + 1):
            delay = max(0.0, self._next_request_at - monotonic())
            if delay >= deadline - monotonic():
                raise _unavailable("arXiv requested a longer pause; please retry later")
            if delay:
                await asyncio.sleep(delay)
            retry_after = 0.0
            upstream_status: int | None = None
            try:
                async with asyncio.timeout(self.attempt_timeout_seconds):
                    async with self.client.stream(
                        "GET", _SEARCH_ENDPOINT, params=params
                    ) as response:
                        response.raise_for_status()
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                                raise DomainError(
                                    code="arxiv_response_too_large",
                                    message="The arXiv search response exceeded the safety limit",
                                    status_code=502,
                                )
                            content.extend(chunk)
                        return bytes(content)
            except httpx.HTTPStatusError as exc:
                upstream_status = exc.response.status_code
                if upstream_status not in {408, 429} and upstream_status < 500:
                    raise DomainError(
                        code="arxiv_search_failed",
                        message="arXiv rejected the search request",
                        status_code=502,
                    ) from exc
                retry_after = _retry_after_seconds(exc.response.headers.get("Retry-After"))
                error_type = type(exc).__name__
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                TimeoutError,
            ) as exc:
                error_type = type(exc).__name__
            except httpx.HTTPError as exc:
                raise DomainError(
                    code="arxiv_search_failed",
                    message="The arXiv response could not be read",
                    status_code=502,
                ) from exc
            finally:
                # Failed requests count toward the request interval, too.
                self._next_request_at = monotonic() + self.min_interval_seconds

            backoff = max(self.min_interval_seconds, 3.0) * 2 ** (attempt - 1)
            self._next_request_at = monotonic() + max(backoff, retry_after)
            logger.warning(
                "arxiv_search_attempt_failed",
                attempt=attempt,
                max_attempts=self.max_attempts,
                error_type=error_type,
                upstream_status=upstream_status,
            )
        raise _unavailable("arXiv is temporarily unavailable after retries; please retry later")

    async def close(self) -> None:
        await self.client.aclose()


def build_arxiv_search_client(settings: Settings) -> ArxivSearchClient:
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=settings.download_connect_timeout_seconds,
            read=settings.download_read_timeout_seconds,
            write=30.0,
            pool=10.0,
        ),
        follow_redirects=False,
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        headers={
            "User-Agent": settings.arxiv_user_agent,
            "Accept": "application/atom+xml",
        },
    )
    return ArxivSearchClient(
        client,
        settings.arxiv_search_min_interval_seconds,
        max_attempts=settings.arxiv_search_max_attempts,
        attempt_timeout_seconds=settings.arxiv_search_attempt_timeout_seconds,
        total_timeout_seconds=settings.arxiv_search_total_timeout_seconds,
    )


def _unavailable(message: str) -> DomainError:
    return DomainError(code="arxiv_temporarily_unavailable", message=message, status_code=503)


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        seconds = float(value)
    except ValueError:
        try:
            timestamp = parsedate_to_datetime(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            seconds = (timestamp - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return max(0.0, seconds) if isfinite(seconds) else 0.0


def build_query_expression(
    terms: list[str],
    categories: list[str],
    published_from: str | None,
    published_to: str | None,
) -> str:
    safe_terms = [_safe_term(term) for term in terms]
    safe_terms = list(dict.fromkeys(term for term in safe_terms if term))
    if not safe_terms:
        raise DomainError(
            code="invalid_research_topic",
            message="The topic did not contain searchable terms",
            status_code=422,
        )
    term_query = " OR ".join(f'all:"{term}"' for term in safe_terms[:5])
    parts = [f"({term_query})"]
    if categories:
        category_query = " OR ".join(f"cat:{category}" for category in categories)
        parts.append(f"({category_query})")
    if published_from or published_to:
        start = (published_from or "1991-01-01").replace("-", "") + "0000"
        end = (published_to or "2999-12-31").replace("-", "") + "2359"
        parts.append(f"submittedDate:[{start} TO {end}]")
    return " AND ".join(parts)


def _safe_term(value: str) -> str:
    normalized = " ".join(value.replace('"', " ").replace("\\", " ").split())
    return normalized[:120]


def _parse_feed(content: bytes) -> list[ArxivSearchPaper]:
    root = ElementTree.fromstring(content)
    if root.tag != f"{_ATOM}feed":
        raise ValueError("Expected an Atom feed")
    papers: list[ArxivSearchPaper] = []
    seen: set[str] = set()
    for entry in root.findall(f"{_ATOM}entry"):
        identifier = parse_arxiv_identifier(_required_text(entry, f"{_ATOM}id"))
        if identifier.base_id in seen:
            continue
        seen.add(identifier.base_id)
        title = _normalized_text(entry.findtext(f"{_ATOM}title"))
        abstract = _normalized_text(entry.findtext(f"{_ATOM}summary"))
        published = _parse_datetime(_required_text(entry, f"{_ATOM}published"))
        updated = _parse_datetime(_required_text(entry, f"{_ATOM}updated"))
        authors = [
            _normalized_text(author.findtext(f"{_ATOM}name"))
            for author in entry.findall(f"{_ATOM}author")
        ]
        categories = list(
            dict.fromkeys(
                category.attrib.get("term", "").strip()
                for category in entry.findall(f"{_ATOM}category")
                if category.attrib.get("term", "").strip()
            )
        )
        primary_element = entry.find(f"{_ARXIV}primary_category")
        primary = primary_element.attrib.get("term") if primary_element is not None else None
        papers.append(
            ArxivSearchPaper(
                arxiv_id=identifier.canonical,
                title=title or identifier.canonical,
                authors=[author for author in authors if author],
                abstract=abstract,
                published_at=published,
                updated_at=updated,
                categories=categories,
                primary_category=primary,
                abstract_url=identifier.abstract_url,
                pdf_url=identifier.pdf_url,
            )
        )
    return papers


def _required_text(element: Element, path: str) -> str:
    value = _normalized_text(element.findtext(path))
    if not value:
        raise ValueError(f"Missing required Atom field: {path}")
    return value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalized_text(value: str | None) -> str:
    return " ".join((value or "").split())
