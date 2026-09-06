from __future__ import annotations

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from scholarmind.api.dependencies import get_session
from scholarmind.api.schemas import (
    JobResponse,
    PaperCollectionResponse,
    PaperCreateRequest,
    PaperCreateResponse,
    PaperResponse,
    PaperSummaryRequest,
    PaperSummaryResponse,
)
from scholarmind.core.security import Principal, get_current_principal
from scholarmind.db.models import IngestionJob, Paper, PaperSummary
from scholarmind.domain.errors import ConflictError, DomainError, NotFoundError
from scholarmind.domain.papers import JobStatus, PaperStatus
from scholarmind.repositories.papers import PaperRepository
from scholarmind.services.paper_summary import PaperSummaryService
from scholarmind.services.papers import PaperCreation, PaperService

router = APIRouter(prefix="/papers", tags=["papers"])
Session = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
logger = structlog.get_logger(__name__)


@router.post("", response_model=PaperCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_paper(
    payload: PaperCreateRequest,
    request: Request,
    session: Session,
    principal: CurrentPrincipal,
) -> PaperCreateResponse:
    creation = await PaperService(session).create(
        principal.subject,
        payload.arxiv,
        request.app.state.settings.ingestion_max_attempts,
    )
    should_enqueue = creation.created or (
        creation.paper.status == PaperStatus.QUEUED and creation.job.status == JobStatus.QUEUED
    )
    if should_enqueue:
        await _enqueue(request, session, creation)
    return _creation_response(creation)


@router.get("", response_model=PaperCollectionResponse)
async def list_papers(
    session: Session,
    principal: CurrentPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaperCollectionResponse:
    papers, total = await PaperRepository(session).list(principal.subject, limit, offset)
    return PaperCollectionResponse(
        items=[_paper_response(paper, _latest_job(paper)) for paper in papers],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(
    paper_id: UUID,
    session: Session,
    principal: CurrentPrincipal,
) -> PaperResponse:
    paper = await PaperService(session).get(paper_id, principal.subject)
    return _paper_response(paper, _latest_job(paper))


@router.delete("/{paper_id}/history", status_code=204)
async def remove_paper_history(
    paper_id: UUID,
    session: Session,
    principal: CurrentPrincipal,
) -> Response:
    await PaperService(session).remove_from_history(paper_id, principal.subject)
    return Response(status_code=204)


@router.get("/{paper_id}/pdf", response_class=Response)
async def get_paper_pdf(
    paper_id: UUID,
    request: Request,
    session: Session,
    principal: CurrentPrincipal,
) -> Response:
    paper = await PaperService(session).get(paper_id, principal.subject)
    if not paper.pdf_object_key:
        raise ConflictError(
            "paper_pdf_not_ready",
            "The paper PDF is not available yet",
            status=paper.status.value,
        )
    local_path = request.app.state.object_store.local_path(paper.pdf_object_key)
    if local_path is not None:
        return FileResponse(
            local_path,
            media_type="application/pdf",
            filename=f"{paper.arxiv_id.replace('/', '-')}.pdf",
            content_disposition_type="inline",
        )
    signed_url = await request.app.state.object_store.presigned_get_url(paper.pdf_object_key)
    if signed_url is None:
        raise NotFoundError("paper PDF", str(paper_id))
    return RedirectResponse(signed_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/{paper_id}/jobs/latest", response_model=JobResponse)
async def get_latest_job(
    paper_id: UUID,
    session: Session,
    principal: CurrentPrincipal,
) -> JobResponse:
    paper = await PaperService(session).get(paper_id, principal.subject)
    job = _latest_job(paper)
    if job is None:
        raise NotFoundError("ingestion job", str(paper_id))
    return JobResponse.model_validate(job)


@router.get("/{paper_id}/summary", response_model=PaperSummaryResponse)
async def get_paper_summary(
    paper_id: UUID,
    request: Request,
    session: Session,
    principal: CurrentPrincipal,
) -> PaperSummaryResponse:
    await PaperService(session).get(paper_id, principal.subject)
    summary = await _summary_service(request, session).get(paper_id, principal.subject)
    return _summary_response(paper_id, summary)


@router.post("/{paper_id}/summary", response_model=PaperSummaryResponse)
async def generate_paper_summary(
    paper_id: UUID,
    payload: PaperSummaryRequest,
    request: Request,
    session: Session,
    principal: CurrentPrincipal,
) -> PaperSummaryResponse:
    service = _summary_service(request, session)
    summary = await service.generate(
        paper_id,
        principal.subject,
        payload.language,
        refresh=payload.refresh,
    )
    return _summary_response(paper_id, summary)


@router.post(
    "/{paper_id}/retry", response_model=PaperCreateResponse, status_code=status.HTTP_202_ACCEPTED
)
async def retry_paper(
    paper_id: UUID,
    request: Request,
    session: Session,
    principal: CurrentPrincipal,
) -> PaperCreateResponse:
    creation = await PaperService(session).retry(
        paper_id,
        principal.subject,
        request.app.state.settings.ingestion_max_attempts,
    )
    await _enqueue(request, session, creation)
    return _creation_response(creation)


async def _enqueue(
    request: Request,
    session: AsyncSession,
    creation: PaperCreation,
) -> None:
    try:
        queue_id = await request.app.state.job_dispatcher.enqueue(
            creation.job.id,
            request.state.request_id,
        )
    except Exception as exc:
        logger.exception(
            "ingestion_enqueue_failed",
            job_id=str(creation.job.id),
            paper_id=str(creation.paper.id),
            error_type=type(exc).__name__,
        )
        raise DomainError(
            code="queue_unavailable",
            message="The paper was saved but could not be queued; submitting it again is safe",
            status_code=503,
        ) from exc
    creation.job.queue_job_id = queue_id
    await session.commit()


def _creation_response(creation: PaperCreation) -> PaperCreateResponse:
    return PaperCreateResponse(
        paper=_paper_response(creation.paper, creation.job),
        created=creation.created,
    )


def _paper_response(paper: Paper, latest_job: IngestionJob | None) -> PaperResponse:
    data = PaperResponse.model_validate(paper)
    return data.model_copy(
        update={"latest_job": JobResponse.model_validate(latest_job) if latest_job else None}
    )


def _latest_job(paper: Paper) -> IngestionJob | None:
    return max(paper.jobs, key=lambda item: item.created_at) if paper.jobs else None


def _summary_service(request: Request, session: AsyncSession) -> PaperSummaryService:
    return PaperSummaryService(
        session,
        request.app.state.briefing_analyzer,
        request.app.state.settings.summary_max_context_characters,
    )


def _summary_response(paper_id: UUID, summary: PaperSummary | None) -> PaperSummaryResponse:
    if summary is None:
        return PaperSummaryResponse(paper_id=paper_id, status="pending", language=None)
    return PaperSummaryResponse(
        paper_id=summary.paper_id,
        status=summary.status.value,
        language=summary.language,
        content=summary.content,
        error_code=summary.error_code,
        error_message=summary.error_message,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )
