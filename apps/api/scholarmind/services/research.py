from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scholarmind.db.models import ResearchSearch
from scholarmind.domain.errors import ConflictError, DomainError, NotFoundError
from scholarmind.domain.research import ResearchSort, ResearchStatus
from scholarmind.services.arxiv_search import ArxivSearchClient, build_query_expression
from scholarmind.services.research_analysis import ResearchAnalyzer, ResearchReport


class ResearchService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        arxiv: ArxivSearchClient,
        analyzer: ResearchAnalyzer,
        cache_ttl_seconds: int,
    ) -> None:
        self.sessions = sessions
        self.arxiv = arxiv
        self.analyzer = analyzer
        self.cache_ttl_seconds = cache_ttl_seconds

    async def search(
        self,
        owner_id: str,
        topic: str,
        categories: list[str],
        published_from: date | None,
        published_to: date | None,
        sort: ResearchSort,
        limit: int,
    ) -> tuple[ResearchSearch, bool]:
        request_key = _request_key(
            topic,
            categories,
            published_from,
            published_to,
            sort,
            limit,
        )
        cached = await self._cached(owner_id, request_key)
        if cached is not None:
            return cached, True

        terms = await self.analyzer.plan_terms(topic)
        query_expression = build_query_expression(
            terms,
            categories,
            published_from.isoformat() if published_from else None,
            published_to.isoformat() if published_to else None,
        )
        papers = await self.arxiv.search(query_expression, sort, limit)
        if not papers:
            raise DomainError(
                code="no_research_results",
                message="No arXiv papers matched this topic and filter set",
                status_code=404,
            )
        results = [
            {
                "source_id": f"P{index}",
                "arxiv_id": paper.arxiv_id,
                "title": paper.title,
                "authors": paper.authors,
                "abstract": paper.abstract,
                "published_at": paper.published_at.isoformat(),
                "updated_at": paper.updated_at.isoformat(),
                "categories": paper.categories,
                "primary_category": paper.primary_category,
                "abstract_url": paper.abstract_url,
                "pdf_url": paper.pdf_url,
            }
            for index, paper in enumerate(papers, start=1)
        ]
        filters: dict[str, Any] = {
            "categories": categories,
            "published_from": published_from.isoformat() if published_from else None,
            "published_to": published_to.isoformat() if published_to else None,
            "sort": sort.value,
            "limit": limit,
            "terms": terms,
        }
        search = ResearchSearch(
            owner_id=owner_id,
            topic=topic,
            request_key=request_key,
            query_expression=query_expression,
            filters=filters,
            results=results,
            status=ResearchStatus.SEARCHED,
        )
        async with self.sessions() as session:
            session.add(search)
            await session.commit()
            await session.refresh(search)
        return search, False

    async def get(self, owner_id: str, search_id: UUID) -> ResearchSearch:
        async with self.sessions() as session:
            search = await _owned_search(session, owner_id, search_id)
            if search is None:
                raise NotFoundError("research search", str(search_id))
            session.expunge(search)
            return search

    async def list(
        self,
        owner_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[ResearchSearch], int]:
        async with self.sessions() as session:
            items = list(
                (
                    await session.scalars(
                        select(ResearchSearch)
                        .where(ResearchSearch.owner_id == owner_id)
                        .order_by(ResearchSearch.created_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
            total = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ResearchSearch)
                    .where(ResearchSearch.owner_id == owner_id)
                )
                or 0
            )
            for item in items:
                session.expunge(item)
            return items, total

    async def delete(self, owner_id: str, search_id: UUID) -> None:
        async with self.sessions() as session:
            search = await _owned_search(session, owner_id, search_id)
            if search is None:
                raise NotFoundError("research search", str(search_id))
            await session.delete(search)
            await session.commit()

    async def analyze(self, owner_id: str, search_id: UUID) -> ResearchReport:
        async with self.sessions() as session:
            search = await _owned_search(session, owner_id, search_id)
            if search is None:
                raise NotFoundError("research search", str(search_id))
            if search.status == ResearchStatus.COMPLETE and search.report:
                return ResearchReport.model_validate(search.report)
            if search.status == ResearchStatus.ANALYZING:
                raise ConflictError(
                    "research_analysis_in_progress",
                    "This research report is already being generated",
                )
            search.status = ResearchStatus.ANALYZING
            search.error_code = None
            search.error_message = None
            topic = search.topic
            query_expression = search.query_expression
            papers = search.results
            await session.commit()

        try:
            report = await self.analyzer.analyze(topic, query_expression, papers)
        except Exception as exc:
            await self._record_analysis_failure(owner_id, search_id, exc)
            raise

        async with self.sessions() as session:
            search = await _owned_search(session, owner_id, search_id)
            if search is None:
                raise NotFoundError("research search", str(search_id))
            search.report = report.model_dump(mode="json")
            search.status = ResearchStatus.COMPLETE
            search.error_code = None
            search.error_message = None
            await session.commit()
        return report

    async def _cached(self, owner_id: str, request_key: str) -> ResearchSearch | None:
        if self.cache_ttl_seconds == 0:
            return None
        cutoff = datetime.now(UTC) - timedelta(seconds=self.cache_ttl_seconds)
        async with self.sessions() as session:
            search = cast(
                ResearchSearch | None,
                await session.scalar(
                    select(ResearchSearch)
                    .where(
                        ResearchSearch.owner_id == owner_id,
                        ResearchSearch.request_key == request_key,
                        ResearchSearch.created_at >= cutoff,
                        ResearchSearch.status.in_(
                            [ResearchStatus.SEARCHED, ResearchStatus.COMPLETE]
                        ),
                    )
                    .order_by(ResearchSearch.created_at.desc())
                    .limit(1)
                ),
            )
            if search is not None:
                session.expunge(search)
            return search

    async def _record_analysis_failure(
        self,
        owner_id: str,
        search_id: UUID,
        error: Exception,
    ) -> None:
        async with self.sessions() as session:
            search = await _owned_search(session, owner_id, search_id)
            if search is None:
                return
            search.status = ResearchStatus.FAILED
            search.error_code = (
                error.code if isinstance(error, DomainError) else "research_analysis_failed"
            )
            search.error_message = str(error)[:1000]
            await session.commit()


def _request_key(
    topic: str,
    categories: list[str],
    published_from: date | None,
    published_to: date | None,
    sort: ResearchSort,
    limit: int,
) -> str:
    payload = {
        "topic": topic.casefold(),
        "categories": sorted(categories),
        "published_from": published_from.isoformat() if published_from else None,
        "published_to": published_to.isoformat() if published_to else None,
        "sort": sort.value,
        "limit": limit,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


async def _owned_search(
    session: AsyncSession,
    owner_id: str,
    search_id: UUID,
) -> ResearchSearch | None:
    return cast(
        ResearchSearch | None,
        await session.scalar(
            select(ResearchSearch).where(
                ResearchSearch.id == search_id,
                ResearchSearch.owner_id == owner_id,
            )
        ),
    )
