from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from scholarmind.db.models import ChatMessage, Conversation
from scholarmind.domain.errors import ConflictError, DomainError, NotFoundError
from scholarmind.domain.papers import MessageRole, PaperStatus
from scholarmind.repositories.conversations import ConversationRepository
from scholarmind.services.llm import LLMGateway
from scholarmind.services.papers import PaperService
from scholarmind.services.retrieval import RetrievedChunk, Retriever


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: str
    chunk_id: UUID
    page_number: int | None
    section: str | None
    score: float
    excerpt: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "chunk_id": str(self.chunk_id),
            "page_number": self.page_number,
            "section": self.section,
            "score": self.score,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True, slots=True)
class PreparedChat:
    conversation_id: UUID
    question: str
    context: str
    citations: list[Citation]
    history: list[tuple[str, str]]
    started_at: float


class ChatService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        retriever: Retriever,
        llm: LLMGateway,
        max_context_characters: int,
    ) -> None:
        self.sessions = sessions
        self.retriever = retriever
        self.llm = llm
        self.max_context_characters = max_context_characters

    async def prepare(
        self,
        owner_id: str,
        paper_id: UUID,
        question: str,
        conversation_id: UUID | None,
    ) -> PreparedChat:
        started_at = perf_counter()
        async with self.sessions() as session:
            paper = await PaperService(session).get(paper_id, owner_id)
            if paper.status != PaperStatus.READY:
                raise ConflictError(
                    "paper_not_ready",
                    "The paper must finish indexing before it can be queried",
                    status=paper.status.value,
                )
            namespace = paper.retrieval_namespace or f"paper-{paper.id.hex}"
            repository = ConversationRepository(session)
            if conversation_id is None:
                conversation = Conversation(
                    paper_id=paper.id,
                    owner_id=owner_id,
                    title=question.strip()[:100],
                )
                repository.add(conversation)
                await session.flush()
                history: list[tuple[str, str]] = []
            else:
                loaded_conversation = await repository.get(conversation_id, paper.id, owner_id)
                if loaded_conversation is None:
                    raise NotFoundError("conversation", str(conversation_id))
                conversation = loaded_conversation
                history = [
                    (message.role.value, message.content) for message in conversation.messages[-8:]
                ]

            chunks = await self.retriever.retrieve(
                session,
                paper.id,
                namespace,
                question,
                limit=10,
            )
            if not chunks:
                raise DomainError(
                    code="no_retrieval_context",
                    message="No searchable text is available for this paper",
                    status_code=422,
                )
            context, citations = _build_context(chunks, self.max_context_characters)
            session.add(
                ChatMessage(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content=question,
                )
            )
            conversation.updated_at = datetime.now(UTC)
            await session.commit()
            return PreparedChat(
                conversation_id=conversation.id,
                question=question,
                context=context,
                citations=citations,
                history=history,
                started_at=started_at,
            )

    async def save_assistant(self, prepared: PreparedChat, content: str) -> None:
        if not content.strip():
            return
        latency_ms = (perf_counter() - prepared.started_at) * 1000
        async with self.sessions() as session:
            conversation = await session.get(Conversation, prepared.conversation_id)
            if conversation is None:
                return
            session.add(
                ChatMessage(
                    conversation_id=prepared.conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=content,
                    citations=[citation.to_dict() for citation in prepared.citations],
                    latency_ms=latency_ms,
                )
            )
            conversation.updated_at = datetime.now(UTC)
            try:
                await session.commit()
            except (IntegrityError, StaleDataError):
                await session.rollback()
                # Another tab may delete a conversation while its answer is streaming.
                if await session.get(Conversation, prepared.conversation_id) is not None:
                    raise

    async def list_conversations(
        self,
        owner_id: str,
        paper_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Conversation], int]:
        async with self.sessions() as session:
            await PaperService(session).get(paper_id, owner_id)
            conversations, total = await ConversationRepository(session).list(
                paper_id,
                owner_id,
                limit,
                offset,
            )
            for conversation in conversations:
                session.expunge(conversation)
            return conversations, total

    async def get_conversation(
        self,
        owner_id: str,
        paper_id: UUID,
        conversation_id: UUID,
    ) -> Conversation:
        async with self.sessions() as session:
            conversation = await ConversationRepository(session).get(
                conversation_id,
                paper_id,
                owner_id,
            )
            if conversation is None:
                raise NotFoundError("conversation", str(conversation_id))
            session.expunge(conversation)
            return conversation

    async def delete_conversation(
        self, owner_id: str, paper_id: UUID, conversation_id: UUID
    ) -> None:
        async with self.sessions() as session:
            await PaperService(session).get(paper_id, owner_id)
            repository = ConversationRepository(session)
            conversation = await repository.get(conversation_id, paper_id, owner_id)
            if conversation is None:
                raise NotFoundError("conversation", str(conversation_id))
            await repository.delete(conversation)
            await session.commit()


def _build_context(
    chunks: list[RetrievedChunk],
    budget: int,
) -> tuple[str, list[Citation]]:
    blocks: list[str] = []
    citations: list[Citation] = []
    used = 0
    for chunk in chunks:
        source_id = f"S{len(citations) + 1}"
        location = f"page {chunk.page_number}" if chunk.page_number else "page unknown"
        if chunk.section:
            location += f", {chunk.section}"
        prefix = f"[{source_id}] ({location})\n"
        remaining = budget - used - len(prefix)
        if remaining < 200:
            break
        text = chunk.text[:remaining]
        block = prefix + text
        blocks.append(block)
        used += len(block) + 2
        citations.append(
            Citation(
                source_id=source_id,
                chunk_id=chunk.chunk_id,
                page_number=chunk.page_number,
                section=chunk.section,
                score=round(chunk.score, 4),
                excerpt=" ".join(text.split())[:320],
            )
        )
    return "\n\n".join(blocks), citations
