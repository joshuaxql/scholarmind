from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scholarmind.core.metrics import RETENTION_DELETIONS
from scholarmind.db.models import Paper
from scholarmind.domain.papers import PaperStatus
from scholarmind.services.indexing import IndexWriter
from scholarmind.services.storage import ObjectStore

logger = structlog.get_logger(__name__)


async def delete_expired_papers(
    sessions: async_sessionmaker[AsyncSession],
    storage: ObjectStore,
    index_writer: IndexWriter,
    retention_days: int,
    *,
    batch_size: int = 100,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with sessions() as session:
        papers = list(
            (
                await session.scalars(
                    select(Paper)
                    .where(
                        Paper.created_at < cutoff,
                        Paper.status.in_([PaperStatus.READY, PaperStatus.FAILED]),
                    )
                    .order_by(Paper.created_at)
                    .limit(batch_size)
                )
            ).all()
        )

    deleted = 0
    for paper in papers:
        try:
            if paper.pdf_object_key:
                await storage.delete(paper.pdf_object_key)
            if paper.markdown_object_key:
                await storage.delete(paper.markdown_object_key)
            await index_writer.delete_paper(paper.id)
            async with sessions() as session, session.begin():
                await session.execute(delete(Paper).where(Paper.id == paper.id))
            deleted += 1
            RETENTION_DELETIONS.labels("deleted").inc()
            logger.info("retention_paper_deleted", paper_id=str(paper.id))
        except Exception as exc:
            RETENTION_DELETIONS.labels("failed").inc()
            logger.exception(
                "retention_delete_failed",
                paper_id=str(paper.id),
                error_type=type(exc).__name__,
            )
    logger.info("retention_batch_completed", deleted=deleted, selected=len(papers))
    return deleted
