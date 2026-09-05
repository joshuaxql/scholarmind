from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import structlog
from arq import Retry
from botocore.exceptions import BotoCoreError, ClientError
from prometheus_client import start_http_server
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from scholarmind.core.config import Environment, Settings, get_settings
from scholarmind.core.logging import configure_logging
from scholarmind.core.metrics import (
    INGESTION_DURATION,
    INGESTION_JOBS,
    INGESTION_TRANSITIONS,
)
from scholarmind.db.models import IngestionJob, PaperChunk
from scholarmind.db.session import Database
from scholarmind.domain.arxiv import parse_arxiv_identifier
from scholarmind.domain.papers import JobStage, JobStatus, PaperStatus, progress_for_stage
from scholarmind.services.arxiv_client import ArxivClient, ArxivMetadata, build_http_client
from scholarmind.services.indexing import IndexWriter, build_index_writer
from scholarmind.services.ingestion_errors import IngestionError
from scholarmind.services.pdf_parser import PARSER_VERSION, ParsedPaper, PdfParser
from scholarmind.services.retention import delete_expired_papers
from scholarmind.services.storage import ObjectStore, build_object_store

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PaperSnapshot:
    id: UUID
    arxiv_id: str
    retrieval_namespace: str
    max_attempts: int


class IngestionPipeline:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        arxiv: ArxivClient,
        parser: PdfParser,
        storage: ObjectStore,
        index_writer: IndexWriter,
    ) -> None:
        self.sessions = sessions
        self.arxiv = arxiv
        self.parser = parser
        self.storage = storage
        self.index_writer = index_writer

    async def run(self, job_id: UUID, attempt: int) -> None:
        structlog.contextvars.bind_contextvars(job_id=str(job_id), attempt=attempt)
        snapshot = await self._claim(job_id, attempt)
        if snapshot is None:
            return
        structlog.contextvars.bind_contextvars(paper_id=str(snapshot.id))
        logger.info("ingestion_started")
        identifier = parse_arxiv_identifier(snapshot.arxiv_id)
        try:
            metadata = await self.arxiv.fetch_metadata(identifier)
            await self._advance(job_id, PaperStatus.DOWNLOADING, JobStage.DOWNLOAD)
            with tempfile.TemporaryDirectory(prefix="scholarmind-") as temporary_dir:
                pdf_path = Path(temporary_dir) / "paper.pdf"
                downloaded = await self.arxiv.download_pdf(identifier, pdf_path)
                await self._advance(job_id, PaperStatus.PARSING, JobStage.PARSE)
                parsed = await self.parser.parse(pdf_path)
                await self._advance(job_id, PaperStatus.PARSING, JobStage.STORE)
                pdf_key = f"papers/{snapshot.id}/source.pdf"
                markdown_key = f"papers/{snapshot.id}/document.md"
                await self.storage.put_file(pdf_key, downloaded.path, "application/pdf")
                await self.storage.put_bytes(
                    markdown_key,
                    parsed.markdown.encode("utf-8"),
                    "text/markdown; charset=utf-8",
                )
                await self._persist_parsed(
                    job_id,
                    downloaded.sha256,
                    pdf_key,
                    markdown_key,
                    metadata,
                    parsed,
                )
                await self.index_writer.index(
                    snapshot.id,
                    snapshot.retrieval_namespace,
                    parsed.chunks,
                )
            await self._complete(job_id)
        except Exception as exc:
            error = _normalize_error(exc)
            await self._record_failure(job_id, error, terminal=attempt >= snapshot.max_attempts)
            if not isinstance(exc, IngestionError):
                logger.exception(
                    "unexpected_ingestion_failure",
                    job_id=str(job_id),
                    error_type=type(exc).__name__,
                )
            raise error from exc

    async def _claim(self, job_id: UUID, attempt: int) -> PaperSnapshot | None:
        async with self.sessions() as session, session.begin():
            job = await _locked_job(session, job_id)
            if job is None:
                raise IngestionError("job_not_found", "The ingestion job no longer exists")
            if job.status == JobStatus.SUCCEEDED:
                return None
            if job.status == JobStatus.RUNNING and job.attempt >= attempt:
                logger.info("duplicate_ingestion_ignored", job_id=str(job_id), attempt=attempt)
                return None

            paper = job.paper
            job.status = JobStatus.RUNNING
            job.stage = JobStage.METADATA
            job.progress = progress_for_stage(JobStage.METADATA)
            job.attempt = max(attempt, job.attempt + 1)
            job.started_at = job.started_at or datetime.now(UTC)
            job.error_code = None
            job.error_message = None
            if paper.status == PaperStatus.FAILED:
                paper.status = PaperStatus.QUEUED
            paper.status = PaperStatus.DOWNLOADING
            INGESTION_TRANSITIONS.labels(JobStage.METADATA.value).inc()
            paper.error_code = None
            paper.error_message = None
            namespace = paper.retrieval_namespace or f"paper-{paper.id.hex}"
            paper.retrieval_namespace = namespace
            return PaperSnapshot(paper.id, paper.arxiv_id, namespace, job.max_attempts)

    async def _advance(
        self,
        job_id: UUID,
        paper_status: PaperStatus,
        stage: JobStage,
    ) -> None:
        async with self.sessions() as session, session.begin():
            job = await _locked_job(session, job_id)
            if job is None:
                raise IngestionError("job_not_found", "The ingestion job no longer exists")
            job.paper.status = paper_status
            job.stage = stage
            job.progress = progress_for_stage(stage)
            INGESTION_TRANSITIONS.labels(stage.value).inc()
            logger.info("ingestion_stage_changed", stage=stage.value, progress=job.progress)

    async def _persist_parsed(
        self,
        job_id: UUID,
        content_sha256: str,
        pdf_key: str,
        markdown_key: str,
        metadata: ArxivMetadata | None,
        parsed: ParsedPaper,
    ) -> None:
        async with self.sessions() as session, session.begin():
            job = await _locked_job(session, job_id)
            if job is None:
                raise IngestionError("job_not_found", "The ingestion job no longer exists")
            paper = job.paper
            await session.execute(delete(PaperChunk).where(PaperChunk.paper_id == paper.id))
            session.add_all(
                [
                    PaperChunk(
                        id=uuid5(NAMESPACE_URL, f"scholarmind-db:{paper.id}:{chunk.ordinal}"),
                        paper_id=paper.id,
                        ordinal=chunk.ordinal,
                        text=chunk.text,
                        page_number=chunk.page_number,
                        section=chunk.section,
                        token_count=chunk.token_count,
                        content_sha256=chunk.content_sha256,
                    )
                    for chunk in parsed.chunks
                ]
            )
            if metadata is not None:
                paper.title = metadata.title or paper.title
                paper.authors = metadata.authors
                paper.abstract = metadata.abstract or paper.abstract
                paper.published_at = metadata.published_at
            paper.pdf_object_key = pdf_key
            paper.markdown_object_key = markdown_key
            paper.content_sha256 = content_sha256
            paper.parser_version = PARSER_VERSION
            paper.status = PaperStatus.INDEXING
            job.stage = JobStage.INDEX
            job.progress = progress_for_stage(JobStage.INDEX)
            INGESTION_TRANSITIONS.labels(JobStage.INDEX.value).inc()
            logger.info(
                "ingestion_stage_changed",
                stage=JobStage.INDEX.value,
                progress=job.progress,
            )

    async def _complete(self, job_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            job = await _locked_job(session, job_id)
            if job is None:
                raise IngestionError("job_not_found", "The ingestion job no longer exists")
            job.status = JobStatus.SUCCEEDED
            job.stage = JobStage.COMPLETE
            job.progress = 100
            job.finished_at = now
            job.paper.status = PaperStatus.READY
            job.paper.indexed_at = now
            job.paper.ready_at = now
            job.paper.error_code = None
            job.paper.error_message = None
            elapsed = _elapsed_seconds(job.started_at, now)
            INGESTION_TRANSITIONS.labels(JobStage.COMPLETE.value).inc()
            INGESTION_JOBS.labels("succeeded", "none").inc()
            INGESTION_DURATION.observe(max(0.0, elapsed))
            logger.info("ingestion_completed", duration_seconds=round(elapsed, 3))

    async def _record_failure(
        self,
        job_id: UUID,
        error: IngestionError,
        *,
        terminal: bool,
    ) -> None:
        async with self.sessions() as session, session.begin():
            job = await _locked_job(session, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED if terminal or not error.retryable else JobStatus.RETRYING
            job.error_code = error.code
            job.error_message = error.message[:1000]
            job.finished_at = datetime.now(UTC) if job.status == JobStatus.FAILED else None
            job.paper.status = (
                PaperStatus.FAILED if job.status == JobStatus.FAILED else PaperStatus.QUEUED
            )
            job.paper.error_code = error.code
            job.paper.error_message = error.message[:1000]
            if job.status == JobStatus.FAILED:
                now = datetime.now(UTC)
                elapsed = _elapsed_seconds(job.started_at, now)
                INGESTION_JOBS.labels("failed", error.code).inc()
                INGESTION_DURATION.observe(max(0.0, elapsed))
                logger.error(
                    "ingestion_failed",
                    error_code=error.code,
                    retryable=error.retryable,
                    duration_seconds=round(elapsed, 3),
                )
            else:
                logger.warning(
                    "ingestion_retry_scheduled",
                    error_code=error.code,
                    retryable=error.retryable,
                )


async def ingest_paper(
    ctx: dict[str, Any],
    job_id: str,
    request_id: str | None = None,
) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(job_id=job_id, request_id=request_id or "worker")
    attempt = int(ctx.get("job_try", 1))
    pipeline = _pipeline_from_context(ctx)
    settings: Settings = ctx["settings"]
    try:
        await pipeline.run(UUID(job_id), attempt)
    except IngestionError as exc:
        if exc.retryable and attempt < settings.ingestion_max_attempts:
            raise Retry(defer=min(60, 2**attempt)) from exc
        raise
    finally:
        structlog.contextvars.clear_contextvars()


async def run_ingestion_job(
    job_id: UUID,
    settings: Settings,
    request_id: str | None = None,
) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(job_id=str(job_id), request_id=request_id or "inline")
    context = await create_worker_context(settings)
    try:
        pipeline = _pipeline_from_context(context)
        for attempt in range(1, settings.ingestion_max_attempts + 1):
            try:
                await pipeline.run(job_id, attempt)
                return
            except IngestionError as exc:
                if not exc.retryable or attempt == settings.ingestion_max_attempts:
                    return
                await asyncio.sleep(min(10, 2**attempt))
    finally:
        await close_worker_context(context)
        structlog.contextvars.clear_contextvars()


async def cleanup_expired_papers(ctx: dict[str, Any]) -> None:
    settings: Settings = ctx["settings"]
    database: Database = ctx["database"]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(job_id="retention")
    try:
        await delete_expired_papers(
            database.session_factory,
            ctx["storage"],
            ctx["index_writer"],
            settings.paper_retention_days,
        )
    finally:
        structlog.contextvars.clear_contextvars()


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(
        settings.log_level,
        json_logs=settings.environment == Environment.PRODUCTION,
    )
    context = await create_worker_context(settings)
    try:
        if settings.worker_metrics_port:
            server, thread = start_http_server(settings.worker_metrics_port)
            context["metrics_server"] = server
            context["metrics_thread"] = thread
    except Exception:
        await close_worker_context(context)
        raise
    ctx.update(context)
    logger.info(
        "worker_started",
        queue_mode=settings.queue_mode,
        metrics_port=settings.worker_metrics_port,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_worker_context(ctx)


async def create_worker_context(settings: Settings) -> dict[str, Any]:
    database = Database(settings)
    if settings.auto_create_schema:
        await database.create_schema()
    client = build_http_client(settings)
    storage = build_object_store(settings)
    await storage.ensure_ready()
    index_writer = build_index_writer(settings, client, database.session_factory)
    return {
        "settings": settings,
        "database": database,
        "http_client": client,
        "storage": storage,
        "index_writer": index_writer,
        "parser": PdfParser(max_pages=settings.max_pdf_pages),
    }


async def close_worker_context(ctx: dict[str, Any]) -> None:
    metrics_server: Any | None = ctx.get("metrics_server")
    index_writer: IndexWriter | None = ctx.get("index_writer")
    storage: ObjectStore | None = ctx.get("storage")
    client: httpx.AsyncClient | None = ctx.get("http_client")
    database: Database | None = ctx.get("database")
    if metrics_server:
        await asyncio.to_thread(metrics_server.shutdown)
        await asyncio.to_thread(metrics_server.server_close)
    if index_writer:
        await index_writer.close()
    if storage:
        await storage.close()
    if client:
        await client.aclose()
    if database:
        await database.close()


def _pipeline_from_context(ctx: dict[str, Any]) -> IngestionPipeline:
    settings: Settings = ctx["settings"]
    database: Database = ctx["database"]
    return IngestionPipeline(
        database.session_factory,
        ArxivClient(ctx["http_client"], settings),
        ctx["parser"],
        ctx["storage"],
        ctx["index_writer"],
    )


async def _locked_job(session: AsyncSession, job_id: UUID) -> IngestionJob | None:
    return cast(
        IngestionJob | None,
        await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.id == job_id)
            .options(joinedload(IngestionJob.paper))
            .with_for_update()
        ),
    )


def _elapsed_seconds(started_at: datetime | None, finished_at: datetime) -> float:
    if started_at is None:
        return 0.0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return max(0.0, (finished_at - started_at).total_seconds())


def _normalize_error(exc: Exception) -> IngestionError:
    if isinstance(exc, IngestionError):
        return exc
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, BotoCoreError, ClientError)):
        return IngestionError(
            "upstream_temporarily_unavailable",
            "A required upstream service is temporarily unavailable",
            retryable=True,
        )
    return IngestionError("ingestion_failed", "The paper could not be processed")
