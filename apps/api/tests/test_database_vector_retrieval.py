from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from scholarmind.core.config import Settings
from scholarmind.db.models import PaperChunk
from scholarmind.db.session import Database
from scholarmind.services.indexing import DatabaseIndexWriter
from scholarmind.services.papers import PaperService
from scholarmind.services.pdf_parser import ParsedChunk
from scholarmind.services.retrieval import DatabaseRetriever


class ControlledEmbedding:
    dimension = 3
    identifier = "test-embedding:v1"

    def __init__(self, *, fail_query: bool = False) -> None:
        self.fail_query = fail_query

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        if self.fail_query:
            raise RuntimeError("provider unavailable")
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        if "feline" in lowered or "cat" in lowered:
            return [1.0, 0.0, 0.0]
        if "engine" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def parsed_chunk(ordinal: int, text: str, page: int) -> ParsedChunk:
    return ParsedChunk(
        ordinal=ordinal,
        text=text,
        page_number=page,
        section="Findings",
        token_count=max(1, len(text) // 4),
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


@pytest.mark.asyncio
async def test_database_writer_persists_embeddings_and_semantic_retrieval_is_scoped(
    tmp_path: Path,
) -> None:
    database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'vectors.db'}"))
    await database.create_schema()
    feline = parsed_chunk(0, "Felines sleep for much of the observational period.", 4)
    engine = parsed_chunk(1, "The engine reaches peak torque at low speed.", 7)
    async with database.session_factory() as session:
        first = await PaperService(session).create("owner", "2501.06713")
        second = await PaperService(session).create("owner", "2201.08239")
        session.add_all(
            [
                PaperChunk(
                    paper_id=first.paper.id,
                    ordinal=chunk.ordinal,
                    text=chunk.text,
                    page_number=chunk.page_number,
                    section=chunk.section,
                    token_count=chunk.token_count,
                    content_sha256=chunk.content_sha256,
                )
                for chunk in [feline, engine]
            ]
            + [
                PaperChunk(
                    paper_id=second.paper.id,
                    ordinal=0,
                    text="A cat appears only in the other paper.",
                    page_number=99,
                    token_count=8,
                    content_sha256="f" * 64,
                )
            ]
        )
        await session.commit()
        first_id = first.paper.id
        first_namespace = first.paper.retrieval_namespace or ""

    embeddings = ControlledEmbedding()
    writer = DatabaseIndexWriter(database.session_factory, embeddings)
    await writer.index(first_id, first_namespace, [feline, engine])

    async with database.session_factory() as session:
        stored = list(
            (
                await session.scalars(
                    select(PaperChunk)
                    .where(PaperChunk.paper_id == first_id)
                    .order_by(PaperChunk.ordinal)
                )
            ).all()
        )
        results = await DatabaseRetriever(embeddings).retrieve(
            session,
            first_id,
            first_namespace,
            "What do cats do?",
            2,
        )
    await database.close()

    assert all(chunk.embedding_model == embeddings.identifier for chunk in stored)
    assert stored[0].embedding == [1.0, 0.0, 0.0]
    assert results[0].page_number == 4
    assert all(result.page_number != 99 for result in results)


@pytest.mark.asyncio
async def test_database_retriever_falls_back_to_lexical_when_embedding_api_fails(
    tmp_path: Path,
) -> None:
    database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'fallback.db'}"))
    await database.create_schema()
    embeddings = ControlledEmbedding(fail_query=True)
    async with database.session_factory() as session:
        created = await PaperService(session).create("owner", "2501.06713")
        session.add(
            PaperChunk(
                paper_id=created.paper.id,
                ordinal=0,
                text="Bounded noise guarantees spectral convergence.",
                page_number=5,
                token_count=8,
                content_sha256="a" * 64,
                embedding=[1.0, 0.0, 0.0],
                embedding_model=embeddings.identifier,
            )
        )
        await session.commit()
        results = await DatabaseRetriever(embeddings).retrieve(
            session,
            created.paper.id,
            created.paper.retrieval_namespace or "",
            "spectral convergence",
            3,
        )
    await database.close()
    assert len(results) == 1
    assert results[0].page_number == 5
    assert results[0].score > 0
