from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from scholarmind.core.config import Settings
from scholarmind.db.models import IngestionJob, Paper, PaperChunk
from scholarmind.db.session import Database
from scholarmind.domain.papers import JobStage, JobStatus, PaperStatus
from scholarmind.services.arxiv_client import ArxivMetadata, DownloadedPaper
from scholarmind.services.ingestion_errors import IngestionError
from scholarmind.services.papers import PaperService
from scholarmind.services.pdf_parser import ParsedChunk, ParsedPaper
from scholarmind.services.storage import LocalObjectStore
from scholarmind.workers.jobs import IngestionPipeline


class FakeArxiv:
    async def fetch_metadata(self, identifier: object) -> ArxivMetadata:
        return ArxivMetadata("A test paper", ["Ada Lovelace"], "Abstract", datetime.now(UTC))

    async def download_pdf(self, identifier: object, destination: Path) -> DownloadedPaper:
        content = b"%PDF-test"
        await asyncio.to_thread(destination.write_bytes, content)
        return DownloadedPaper(destination, hashlib.sha256(content).hexdigest(), len(content))


class FakeParser:
    async def parse(self, path: Path) -> ParsedPaper:
        text = "The spectral method converges under bounded noise."
        return ParsedPaper(
            markdown=f"## Page 1\n\n{text}\n",
            chunks=[
                ParsedChunk(
                    ordinal=0,
                    text=text,
                    page_number=1,
                    section="Theorem",
                    token_count=12,
                    content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                )
            ],
            page_count=1,
        )


class FakeIndex:
    def __init__(self, error: IngestionError | None = None) -> None:
        self.error = error
        self.indexed: list[UUID] = []

    async def index(self, paper_id: UUID, namespace: str, chunks: list[ParsedChunk]) -> None:
        assert namespace == f"paper-{paper_id.hex}"
        if self.error:
            raise self.error
        self.indexed.append(paper_id)

    async def delete_paper(self, paper_id: UUID) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_ingestion_only_marks_ready_after_index_success(tmp_path: Path) -> None:
    database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))
    await database.create_schema()
    async with database.session_factory() as session:
        created = await PaperService(session).create("owner", "2501.06713")
        job_id = created.job.id
        paper_id = created.paper.id

    storage = LocalObjectStore(tmp_path / "objects")
    await storage.ensure_ready()
    index = FakeIndex()
    await IngestionPipeline(
        database.session_factory, FakeArxiv(), FakeParser(), storage, index
    ).run(job_id, 1)

    async with database.session_factory() as session:
        paper = (await session.scalars(select(Paper))).one()
        job = (await session.scalars(select(IngestionJob))).one()
        chunks = list((await session.scalars(select(PaperChunk))).all())
    await database.close()
    assert paper.status == PaperStatus.READY
    assert job.status == JobStatus.SUCCEEDED
    assert job.stage == JobStage.COMPLETE
    assert len(chunks) == 1 and chunks[0].page_number == 1
    assert index.indexed == [paper_id]
    assert storage.local_path(f"papers/{paper_id}/source.pdf") is not None


@pytest.mark.asyncio
async def test_retryable_index_failure_never_creates_false_ready_state(tmp_path: Path) -> None:
    database = Database(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'failed.sqlite'}"))
    await database.create_schema()
    async with database.session_factory() as session:
        created = await PaperService(session).create("owner", "2501.06713", max_attempts=3)
        job_id = created.job.id

    storage = LocalObjectStore(tmp_path / "objects")
    await storage.ensure_ready()
    failure = IngestionError("vector_unavailable", "Vector store unavailable", retryable=True)
    pipeline = IngestionPipeline(
        database.session_factory, FakeArxiv(), FakeParser(), storage, FakeIndex(failure)
    )
    with pytest.raises(IngestionError, match="Vector store unavailable"):
        await pipeline.run(job_id, 1)

    async with database.session_factory() as session:
        paper = (await session.scalars(select(Paper))).one()
        job = (await session.scalars(select(IngestionJob))).one()
    await database.close()
    assert paper.status == PaperStatus.QUEUED
    assert job.status == JobStatus.RETRYING
    assert job.error_code == "vector_unavailable"
