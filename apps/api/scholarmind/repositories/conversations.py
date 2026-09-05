from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from scholarmind.db.models import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self,
        conversation_id: UUID,
        paper_id: UUID,
        owner_id: str,
    ) -> Conversation | None:
        return cast(
            Conversation | None,
            await self.session.scalar(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.paper_id == paper_id,
                    Conversation.owner_id == owner_id,
                )
                .options(selectinload(Conversation.messages))
            ),
        )

    async def list(
        self,
        paper_id: UUID,
        owner_id: str,
        limit: int,
        offset: int,
    ) -> tuple[list[Conversation], int]:
        conditions = (
            Conversation.paper_id == paper_id,
            Conversation.owner_id == owner_id,
        )
        items = list(
            (
                await self.session.scalars(
                    select(Conversation)
                    .where(*conditions)
                    .options(selectinload(Conversation.messages))
                    .order_by(Conversation.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(Conversation).where(*conditions)
            )
            or 0
        )
        return items, total

    def add(self, conversation: Conversation) -> None:
        self.session.add(conversation)

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
