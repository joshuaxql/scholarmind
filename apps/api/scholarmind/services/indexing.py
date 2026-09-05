from __future__ import annotations

import asyncio
import math
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scholarmind.core.config import Settings
from scholarmind.db.models import PaperChunk
from scholarmind.services.embeddings import EmbeddingProvider, build_embedding_provider
from scholarmind.services.ingestion_errors import IngestionError
from scholarmind.services.pdf_parser import ParsedChunk


class IndexWriter(Protocol):
    async def index(self, paper_id: UUID, namespace: str, chunks: list[ParsedChunk]) -> None: ...

    async def delete_paper(self, paper_id: UUID) -> None: ...

    async def close(self) -> None: ...


class DatabaseIndexWriter:
    """Persist embeddings beside chunks for an all-local SQLite/PostgreSQL setup."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        embeddings: EmbeddingProvider,
    ) -> None:
        self.sessions = sessions
        self.embeddings = embeddings

    async def index(self, paper_id: UUID, namespace: str, chunks: list[ParsedChunk]) -> None:
        del namespace
        vectors = await self.embeddings.embed_documents([chunk.text for chunk in chunks])
        _validate_vectors(vectors, len(chunks))
        async with self.sessions() as session, session.begin():
            stored = list(
                (
                    await session.scalars(
                        select(PaperChunk)
                        .where(PaperChunk.paper_id == paper_id)
                        .order_by(PaperChunk.ordinal)
                    )
                ).all()
            )
            by_ordinal = {chunk.ordinal: chunk for chunk in stored}
            if len(by_ordinal) != len(chunks):
                raise _chunk_mismatch()
            for parsed, vector in zip(chunks, vectors, strict=True):
                stored_chunk = by_ordinal.get(parsed.ordinal)
                if stored_chunk is None or stored_chunk.content_sha256 != parsed.content_sha256:
                    raise _chunk_mismatch()
                stored_chunk.embedding = vector
                stored_chunk.embedding_model = self.embeddings.identifier

    async def delete_paper(self, paper_id: UUID) -> None:
        # Relational cascade deletion owns database chunks and their vectors.
        del paper_id

    async def close(self) -> None:
        return None


class QdrantIndexWriter:
    def __init__(
        self,
        client: AsyncQdrantClient,
        collection: str,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.client = client
        self.collection = collection
        self.embeddings = embeddings
        self._ready_dimension: int | None = None
        self._lock = asyncio.Lock()

    async def index(self, paper_id: UUID, namespace: str, chunks: list[ParsedChunk]) -> None:
        vectors = await self.embeddings.embed_documents([chunk.text for chunk in chunks])
        dimension = _validate_vectors(vectors, len(chunks))
        await self._ensure_collection(dimension)
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="paper_id",
                            match=models.MatchValue(value=str(paper_id)),
                        )
                    ]
                )
            ),
            wait=True,
        )
        for start in range(0, len(chunks), 128):
            batch = chunks[start : start + 128]
            batch_vectors = vectors[start : start + 128]
            await self.client.upsert(
                collection_name=self.collection,
                wait=True,
                points=[
                    models.PointStruct(
                        id=uuid5(
                            NAMESPACE_URL,
                            f"scholarmind:{paper_id}:{chunk.ordinal}:{chunk.content_sha256}",
                        ),
                        vector=vector,
                        payload={
                            "paper_id": str(paper_id),
                            "namespace": namespace,
                            "chunk_id": str(
                                uuid5(NAMESPACE_URL, f"scholarmind-db:{paper_id}:{chunk.ordinal}")
                            ),
                            "ordinal": chunk.ordinal,
                            "text": chunk.text,
                            "page_number": chunk.page_number,
                            "section": chunk.section,
                            "content_sha256": chunk.content_sha256,
                            "embedding_model": self.embeddings.identifier,
                        },
                    )
                    for chunk, vector in zip(batch, batch_vectors, strict=True)
                ],
            )

    async def delete_paper(self, paper_id: UUID) -> None:
        if not await self.client.collection_exists(self.collection):
            return
        await self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="paper_id",
                            match=models.MatchValue(value=str(paper_id)),
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def close(self) -> None:
        await self.client.close()

    async def _ensure_collection(self, dimension: int) -> None:
        if self._ready_dimension is not None:
            if self._ready_dimension != dimension:
                raise _dimension_mismatch(self._ready_dimension, dimension)
            return
        async with self._lock:
            if self._ready_dimension is not None:
                if self._ready_dimension != dimension:
                    raise _dimension_mismatch(self._ready_dimension, dimension)
                return
            if not await self.client.collection_exists(self.collection):
                await self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=dimension,
                        distance=models.Distance.COSINE,
                    ),
                )
            else:
                information = await self.client.get_collection(self.collection)
                configured = _qdrant_vector_dimension(information.config.params.vectors)
                if configured is not None and configured != dimension:
                    raise _dimension_mismatch(configured, dimension)
            self._ready_dimension = dimension


def build_index_writer(
    settings: Settings,
    http_client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> IndexWriter:
    embeddings = build_embedding_provider(settings, http_client)
    if settings.retrieval_backend == "database":
        return DatabaseIndexWriter(sessions, embeddings)
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=api_key, timeout=30)
    return QdrantIndexWriter(client, settings.qdrant_collection, embeddings)


def _validate_vectors(vectors: list[list[float]], expected_count: int) -> int:
    if expected_count <= 0 or len(vectors) != expected_count:
        raise IngestionError(
            "invalid_embedding_response",
            "The embedding service returned an invalid number of vectors",
        )
    dimensions = {len(vector) for vector in vectors}
    if len(dimensions) != 1 or not all(
        vector and all(math.isfinite(value) for value in vector) for vector in vectors
    ):
        raise IngestionError(
            "invalid_embedding_response",
            "The embedding service returned invalid vectors",
        )
    return dimensions.pop()


def _qdrant_vector_dimension(configuration: Any) -> int | None:
    if isinstance(configuration, models.VectorParams):
        return configuration.size
    return None


def _dimension_mismatch(configured: int, received: int) -> IngestionError:
    return IngestionError(
        "embedding_dimension_mismatch",
        f"The vector index expects dimension {configured}, but the provider returned {received}",
    )


def _chunk_mismatch() -> IngestionError:
    return IngestionError(
        "chunk_index_mismatch",
        "Persisted paper chunks did not match the embedding batch",
    )
