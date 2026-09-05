from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scholarmind.domain.papers import JobStage, JobStatus, MessageRole, PaperStatus
from scholarmind.domain.research import ResearchSort, ResearchStatus


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class EnvironmentFieldResponse(BaseModel):
    key: str
    group: str
    kind: str
    options: list[str]
    minimum: float | None
    maximum: float | None
    exclusive_minimum: bool
    sensitive: bool
    configured: bool
    value: str | None
    in_file: bool


class EnvironmentResponse(BaseModel):
    revision: str
    restart_required: bool
    fields: list[EnvironmentFieldResponse]


class EnvironmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    updates: dict[str, str] = Field(max_length=100)


class PaperCreateRequest(BaseModel):
    arxiv: str = Field(min_length=5, max_length=256, examples=["2501.06713"])


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: JobStatus
    stage: JobStage
    progress: int = Field(ge=0, le=100)
    attempt: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PaperResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    arxiv_id: str
    abstract_url: str
    title: str | None
    authors: list[str]
    abstract: str | None
    published_at: datetime | None
    status: PaperStatus
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    ready_at: datetime | None
    latest_job: JobResponse | None = None


class PaperCollectionResponse(BaseModel):
    items: list[PaperResponse]
    total: int
    limit: int
    offset: int


class PaperCreateResponse(BaseModel):
    paper: PaperResponse
    created: bool


class ResearchSearchRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    categories: list[str] = Field(default_factory=list, max_length=8)
    published_from: date | None = None
    published_to: date | None = None
    sort: ResearchSort = ResearchSort.RELEVANCE
    limit: int = Field(default=20, ge=5, le=50)

    @field_validator("topic")
    @classmethod
    def topic_must_not_be_blank(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Topic must not be blank")
        return normalized

    @field_validator("categories")
    @classmethod
    def categories_must_be_valid(cls, values: list[str]) -> list[str]:
        import re

        pattern = re.compile(r"^[A-Za-z-]+(?:\.[A-Za-z-]+)?$")
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(not pattern.fullmatch(value) for value in normalized):
            raise ValueError("Invalid arXiv category")
        return normalized

    @model_validator(mode="after")
    def dates_must_be_ordered(self) -> ResearchSearchRequest:
        if self.published_from and self.published_to and self.published_from > self.published_to:
            raise ValueError("published_from must not be after published_to")
        return self


class ArxivPaperResponse(BaseModel):
    source_id: str
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime
    updated_at: datetime
    categories: list[str]
    primary_category: str | None = None
    abstract_url: str
    pdf_url: str


class ResearchThemeResponse(BaseModel):
    name: str
    summary: str
    paper_ids: list[str]


class ResearchTimelineResponse(BaseModel):
    period: str
    development: str
    paper_ids: list[str]


class ResearchBottleneckResponse(BaseModel):
    title: str
    description: str
    evidence_type: str
    paper_ids: list[str]


class ResearchOpportunityResponse(BaseModel):
    title: str
    rationale: str
    paper_ids: list[str]


class ResearchReportResponse(BaseModel):
    overview: str
    methodology: str
    themes: list[ResearchThemeResponse]
    timeline: list[ResearchTimelineResponse]
    bottlenecks: list[ResearchBottleneckResponse]
    opportunities: list[ResearchOpportunityResponse]


class ResearchSearchResponse(BaseModel):
    id: UUID
    topic: str
    query_expression: str
    filters: dict[str, Any]
    results: list[ArxivPaperResponse]
    report: ResearchReportResponse | None = None
    status: ResearchStatus
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    cached: bool = False


class ResearchCollectionResponse(BaseModel):
    items: list[ResearchSearchResponse]
    total: int
    limit: int
    offset: int


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=50_000)
    conversation_id: UUID | None = None

    @field_validator("query")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value


class CitationResponse(BaseModel):
    source_id: str
    chunk_id: UUID
    page_number: int | None = None
    section: str | None = None
    score: float
    excerpt: str


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: MessageRole
    content: str
    citations: list[CitationResponse]
    latency_ms: float | None
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    paper_id: UUID
    title: str | None
    messages: list[ChatMessageResponse]
    created_at: datetime
    updated_at: datetime


class ConversationCollectionResponse(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int
