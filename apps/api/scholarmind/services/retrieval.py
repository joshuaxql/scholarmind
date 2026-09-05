from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID

import httpx
import structlog
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scholarmind.core.config import Settings
from scholarmind.core.metrics import RETRIEVAL_FALLBACKS
from scholarmind.db.models import PaperChunk
from scholarmind.services.embeddings import (
    EmbeddingProvider,
    build_embedding_provider,
    lexical_terms,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    text: str
    page_number: int | None
    section: str | None
    score: float


class Retriever(Protocol):
    async def retrieve(
        self,
        session: AsyncSession,
        paper_id: UUID,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]: ...

    async def healthcheck(self) -> None: ...

    async def close(self) -> None: ...


class DatabaseRetriever:
    def __init__(self, embeddings: EmbeddingProvider | None = None) -> None:
        self.embeddings = embeddings

    async def retrieve(
        self,
        session: AsyncSession,
        paper_id: UUID,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        del namespace
        chunks = list(
            (
                await session.scalars(
                    select(PaperChunk)
                    .where(PaperChunk.paper_id == paper_id)
                    .order_by(PaperChunk.ordinal)
                )
            ).all()
        )
        query_vector = await self._query_vector(chunks, query)
        scored: list[RetrievedChunk] = []
        for chunk in chunks:
            lexical = min(1.0, _lexical_score(query, chunk.text, chunk.section))
            vector_score = None
            if (
                query_vector is not None
                and chunk.embedding is not None
                and self.embeddings is not None
                and chunk.embedding_model == self.embeddings.identifier
            ):
                vector_score = _cosine_similarity(query_vector, chunk.embedding)
            score = lexical if vector_score is None else 0.75 * vector_score + 0.25 * lexical
            scored.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    score=score,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        relevant = [item for item in scored if item.score > 0]
        return (relevant or scored)[:limit]

    async def _query_vector(self, chunks: list[PaperChunk], query: str) -> list[float] | None:
        if self.embeddings is None or not any(
            chunk.embedding is not None and chunk.embedding_model == self.embeddings.identifier
            for chunk in chunks
        ):
            return None
        try:
            vector = await self.embeddings.embed_query(query)
            if not vector or not all(math.isfinite(value) for value in vector):
                raise ValueError("invalid query embedding")
            return vector
        except Exception as exc:
            reason = f"database_embedding_{type(exc).__name__}"
            RETRIEVAL_FALLBACKS.labels(reason).inc()
            logger.warning("database_embedding_retrieval_fallback", error_type=type(exc).__name__)
            return None

    async def healthcheck(self) -> None:
        return None

    async def close(self) -> None:
        return None


class QdrantRetriever:
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection: str,
        embeddings: EmbeddingProvider,
        fallback: DatabaseRetriever,
    ) -> None:
        self.client = client
        self.collection = collection
        self.embeddings = embeddings
        self.fallback = fallback

    async def retrieve(
        self,
        session: AsyncSession,
        paper_id: UUID,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        try:
            vector = await self.embeddings.embed_query(query)
            result = await self.client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=_paper_filter(paper_id, namespace),
                limit=max(limit * 2, 10),
                with_payload=True,
                with_vectors=False,
            )
            chunks: list[RetrievedChunk] = []
            for point in result.points:
                payload = cast(dict[str, Any], point.payload or {})
                text = str(payload.get("text", ""))
                if (
                    not text
                    or payload.get("paper_id") != str(paper_id)
                    or payload.get("namespace") != namespace
                ):
                    continue
                vector_score = max(0.0, min(1.0, float(point.score)))
                lexical = min(
                    1.0,
                    _lexical_score(query, text, _optional_str(payload.get("section"))),
                )
                chunks.append(
                    RetrievedChunk(
                        chunk_id=UUID(str(payload["chunk_id"])),
                        text=text,
                        page_number=_optional_int(payload.get("page_number")),
                        section=_optional_str(payload.get("section")),
                        score=0.75 * vector_score + 0.25 * lexical,
                    )
                )
            chunks.sort(key=lambda item: item.score, reverse=True)
            if chunks:
                return chunks[:limit]
            RETRIEVAL_FALLBACKS.labels("empty_result").inc()
        except Exception as exc:
            reason = type(exc).__name__
            RETRIEVAL_FALLBACKS.labels(reason).inc()
            logger.warning("qdrant_retrieval_fallback", error_type=reason)
        return await self.fallback.retrieve(session, paper_id, namespace, query, limit)

    async def healthcheck(self) -> None:
        await self.client.get_collections()

    async def close(self) -> None:
        await self.client.close()


def build_retriever(settings: Settings, http_client: httpx.AsyncClient) -> Retriever:
    embeddings = build_embedding_provider(settings, http_client)
    if settings.retrieval_backend == "database":
        return DatabaseRetriever(embeddings)
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key, timeout=15)
    return QdrantRetriever(
        client,
        settings.qdrant_collection,
        embeddings,
        DatabaseRetriever(),
    )


def _paper_filter(paper_id: UUID, namespace: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="paper_id",
                match=models.MatchValue(value=str(paper_id)),
            ),
            models.FieldCondition(
                key="namespace",
                match=models.MatchValue(value=namespace),
            ),
        ]
    )


def _lexical_score(query: str, text: str, section: str | None) -> float:
    query_terms = set(lexical_terms(query))
    if not query_terms:
        return 0.0
    text_terms = lexical_terms(text)
    frequencies = {term: text_terms.count(term) for term in query_terms}
    matched = sum(1 for value in frequencies.values() if value)
    coverage = matched / len(query_terms)
    frequency = sum(math.log1p(value) for value in frequencies.values()) / len(query_terms)
    section_matches = section and any(term in section.casefold() for term in query_terms)
    section_bonus = 0.15 if section_matches else 0.0
    phrase_bonus = 0.2 if query.casefold() in text.casefold() else 0.0
    return coverage + 0.2 * frequency + section_bonus + phrase_bonus


def _cosine_similarity(first: list[float], second: list[float]) -> float | None:
    if len(first) != len(second) or not first:
        return None
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0 or second_norm == 0:
        return None
    similarity = sum(left * right for left, right in zip(first, second, strict=True)) / (
        first_norm * second_norm
    )
    return max(0.0, min(1.0, similarity))


def _optional_str(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


def _optional_int(value: object) -> int | None:
    try:
        return int(cast(Any, value)) if value is not None else None
    except (TypeError, ValueError):
        return None
