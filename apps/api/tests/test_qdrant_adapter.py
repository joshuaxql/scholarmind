from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient

from scholarmind.services.embeddings import LocalHashEmbedding
from scholarmind.services.indexing import QdrantIndexWriter
from scholarmind.services.pdf_parser import ParsedChunk
from scholarmind.services.retrieval import DatabaseRetriever, QdrantRetriever


def chunk(ordinal: int, text: str, page: int) -> ParsedChunk:
    return ParsedChunk(
        ordinal=ordinal,
        text=text,
        page_number=page,
        section="Results",
        token_count=max(1, len(text) // 4),
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_qdrant_index_query_isolation_and_deletion(app: FastAPI) -> None:
    client = AsyncQdrantClient(location=":memory:")
    embeddings = LocalHashEmbedding(64)
    writer = QdrantIndexWriter(client, "test_chunks", embeddings)
    first_id = uuid4()
    second_id = uuid4()
    first_namespace = f"paper-{first_id.hex}"
    second_namespace = f"paper-{second_id.hex}"
    await writer.index(
        first_id,
        first_namespace,
        [chunk(0, "alpha spectral convergence theorem", 3)],
    )
    await writer.index(
        second_id,
        second_namespace,
        [chunk(0, "beta dialogue benchmark results", 8)],
    )

    retriever = QdrantRetriever(client, "test_chunks", embeddings, DatabaseRetriever())
    async with app.state.database.session_factory() as session:
        results = await retriever.retrieve(
            session,
            first_id,
            first_namespace,
            "spectral convergence",
            limit=5,
        )
        assert len(results) == 1
        assert results[0].page_number == 3
        assert "beta" not in results[0].text

        await writer.delete_paper(first_id)
        deleted_results = await retriever.retrieve(
            session,
            first_id,
            first_namespace,
            "spectral convergence",
            limit=5,
        )
        assert deleted_results == []
    await retriever.close()
