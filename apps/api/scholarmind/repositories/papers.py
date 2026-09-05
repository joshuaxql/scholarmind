from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from scholarmind.db.models import IngestionJob, Paper


class PaperRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, paper_id: UUID, owner_id: str, *, lock: bool = False) -> Paper | None:
        statement = (
            select(Paper)
            .where(Paper.id == paper_id, Paper.owner_id == owner_id)
            .options(selectinload(Paper.jobs))
        )
        if lock:
            statement = statement.with_for_update()
        return cast(Paper | None, await self.session.scalar(statement))

    async def get_by_arxiv(self, arxiv_id: str, owner_id: str) -> Paper | None:
        return cast(
            Paper | None,
            await self.session.scalar(
                select(Paper)
                .where(Paper.arxiv_id == arxiv_id, Paper.owner_id == owner_id)
                .options(selectinload(Paper.jobs))
            ),
        )

    async def list(self, owner_id: str, limit: int, offset: int) -> tuple[list[Paper], int]:
        conditions = (Paper.owner_id == owner_id, Paper.history_hidden.is_(False))
        items = list(
            (
                await self.session.scalars(
                    select(Paper)
                    .where(*conditions)
                    .options(selectinload(Paper.jobs))
                    .order_by(Paper.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(select(func.count()).select_from(Paper).where(*conditions))
            or 0
        )
        return items, total

    async def latest_job(self, paper_id: UUID) -> IngestionJob | None:
        return cast(
            IngestionJob | None,
            await self.session.scalar(
                select(IngestionJob)
                .where(IngestionJob.paper_id == paper_id)
                .order_by(IngestionJob.created_at.desc())
                .limit(1)
            ),
        )

    def add(self, paper: Paper) -> None:
        self.session.add(paper)
