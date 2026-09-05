from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scholarmind.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from scholarmind.domain.papers import JobStage, JobStatus, MessageRole, PaperStatus
from scholarmind.domain.research import ResearchStatus


class ResearchSearch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_searches"
    __table_args__ = (
        Index("ix_research_owner_created", "owner_id", "created_at"),
        Index("ix_research_owner_request", "owner_id", "request_key"),
    )

    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    query_expression: Mapped[str] = mapped_column(Text, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[ResearchStatus] = mapped_column(
        Enum(ResearchStatus, native_enum=False, length=32),
        default=ResearchStatus.SEARCHED,
        nullable=False,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(1000))


class Paper(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("owner_id", "arxiv_id", name="uq_papers_owner_arxiv"),
        Index("ix_papers_owner_status", "owner_id", "status"),
    )

    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False)
    base_arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False)
    history_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    arxiv_version: Mapped[int | None] = mapped_column(Integer)
    abstract_url: Mapped[str] = mapped_column(String(512), nullable=False)
    pdf_url: Mapped[str] = mapped_column(String(512), nullable=False)

    title: Mapped[str | None] = mapped_column(String(1000))
    authors: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[PaperStatus] = mapped_column(
        Enum(PaperStatus, native_enum=False, length=32),
        default=PaperStatus.QUEUED,
        nullable=False,
        index=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    pdf_object_key: Mapped[str | None] = mapped_column(String(512))
    markdown_object_key: Mapped[str | None] = mapped_column(String(512))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(64))
    retrieval_namespace: Mapped[str | None] = mapped_column(String(128), unique=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="IngestionJob.created_at"
    )
    chunks: Mapped[list[PaperChunk]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("ix_jobs_paper_created", "paper_id", "created_at"),)

    paper_id: Mapped[UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=32), default=JobStatus.QUEUED, nullable=False
    )
    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, native_enum=False, length=32), default=JobStage.QUEUED, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    queue_job_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    paper: Mapped[Paper] = relationship(back_populates="jobs")


class PaperChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_chunks"
    __table_args__ = (
        UniqueConstraint("paper_id", "ordinal", name="uq_chunks_paper_ordinal"),
        Index("ix_chunks_paper_page", "paper_id", "page_number"),
    )

    paper_id: Mapped[UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String(500))

    paper: Mapped[Paper] = relationship(back_populates="chunks")


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_paper", "owner_id", "paper_id"),)

    paper_id: Mapped[UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(300))

    paper: Mapped[Paper] = relationship(back_populates="conversations")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False, length=16), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
