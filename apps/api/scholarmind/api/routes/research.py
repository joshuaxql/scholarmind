from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import orjson
import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from scholarmind.api.schemas import (
    ArxivPaperResponse,
    ResearchCollectionResponse,
    ResearchReportResponse,
    ResearchSearchRequest,
    ResearchSearchResponse,
)
from scholarmind.core.security import Principal, get_current_principal
from scholarmind.db.models import ResearchSearch
from scholarmind.domain.errors import DomainError
from scholarmind.services.research import ResearchService

router = APIRouter(prefix="/research", tags=["research"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
logger = structlog.get_logger(__name__)
_SEARCH_REQUEST_TIMEOUT_SECONDS = 110.0


@router.post("/search", response_model=ResearchSearchResponse)
async def search_research(
    payload: ResearchSearchRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> ResearchSearchResponse:
    try:
        # Leave time to return a structured error before the BFF's 130s deadline.
        async with asyncio.timeout(_SEARCH_REQUEST_TIMEOUT_SECONDS):
            search, cached = await _service(request).search(
                principal.subject,
                payload.topic,
                payload.categories,
                payload.published_from,
                payload.published_to,
                payload.sort,
                payload.limit,
            )
    except TimeoutError as exc:
        raise DomainError(
            code="research_search_timeout",
            message="Topic preparation or arXiv search timed out; please retry shortly",
            status_code=504,
        ) from exc
    return _response(search, cached=cached)


@router.get("", response_model=ResearchCollectionResponse)
async def list_research(
    request: Request,
    principal: CurrentPrincipal,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ResearchCollectionResponse:
    items, total = await _service(request).list(principal.subject, limit, offset)
    return ResearchCollectionResponse(
        items=[_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{search_id}", response_model=ResearchSearchResponse)
async def get_research(
    search_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> ResearchSearchResponse:
    search = await _service(request).get(principal.subject, search_id)
    return _response(search)


@router.delete("/{search_id}", status_code=204)
async def delete_research(
    search_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _service(request).delete(principal.subject, search_id)
    return Response(status_code=204)


@router.post("/{search_id}/analyze/stream")
async def analyze_research(
    search_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> StreamingResponse:
    service = _service(request)
    await service.get(principal.subject, search_id)

    async def events() -> AsyncIterator[bytes]:
        yield _event("meta", {"search_id": str(search_id), "stage": "analyzing"})
        try:
            report = await service.analyze(principal.subject, search_id)
            if not await request.is_disconnected():
                yield _event(
                    "done",
                    {"report": report.model_dump(mode="json"), "stage": "complete"},
                )
        except asyncio.CancelledError:
            raise
        except DomainError as exc:
            logger.warning(
                "research_analysis_failed",
                search_id=str(search_id),
                error_code=exc.code,
            )
            yield _event("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:
            logger.exception(
                "research_analysis_failed",
                search_id=str(search_id),
                error_type=type(exc).__name__,
            )
            yield _event(
                "error",
                {
                    "code": "research_analysis_failed",
                    "message": "The research report could not be generated",
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _service(request: Request) -> ResearchService:
    settings = request.app.state.settings
    return ResearchService(
        request.app.state.database.session_factory,
        request.app.state.arxiv_search_client,
        request.app.state.research_analyzer,
        settings.research_cache_ttl_seconds,
    )


def _response(search: ResearchSearch, *, cached: bool = False) -> ResearchSearchResponse:
    return ResearchSearchResponse(
        id=search.id,
        topic=search.topic,
        query_expression=search.query_expression,
        filters=search.filters,
        results=[ArxivPaperResponse.model_validate(item) for item in search.results],
        report=(
            ResearchReportResponse.model_validate(search.report)
            if search.report is not None
            else None
        ),
        status=search.status,
        error_code=search.error_code,
        error_message=search.error_message,
        created_at=search.created_at,
        updated_at=search.updated_at,
        cached=cached,
    )


def _event(name: str, data: object) -> bytes:
    return b"event: " + name.encode() + b"\ndata: " + orjson.dumps(data) + b"\n\n"
