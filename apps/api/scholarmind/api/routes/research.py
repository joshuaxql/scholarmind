from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from scholarmind.api.schemas import (
    ArxivPaperResponse,
    ResearchCollectionResponse,
    ResearchReportResponse,
    ResearchSearchRequest,
    ResearchSearchResponse,
    ResearchTokenEvent,
)
from scholarmind.api.streaming import EventSink, keep_alive, operation_events
from scholarmind.core.security import Principal, get_current_principal
from scholarmind.db.models import ResearchSearch
from scholarmind.domain.errors import DomainError
from scholarmind.services.research import ResearchService

router = APIRouter(prefix="/research", tags=["research"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
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


@router.post("/search/stream")
async def stream_research_search(
    payload: ResearchSearchRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> StreamingResponse:
    async def search(emit: EventSink) -> object:
        async def token(text: str) -> None:
            await emit("token", ResearchTokenEvent(text=text, stage="planning").model_dump())

        async def searching(terms: list[str]) -> None:
            await emit("meta", {"stage": "searching", "terms": terms})

        result, cached = await _service(request).search(
            principal.subject,
            payload.topic,
            payload.categories,
            payload.published_from,
            payload.published_to,
            payload.sort,
            payload.limit,
            on_token=token,
            on_searching=searching,
        )
        return {"search": _response(result, cached=cached).model_dump(mode="json")}

    return _stream(search, {"stage": "planning"})


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

    async def generate(emit: EventSink) -> object:
        async def token(text: str) -> None:
            await emit("token", ResearchTokenEvent(text=text, stage="analyzing").model_dump())

        report = await service.analyze(principal.subject, search_id, on_token=token)
        return {"report": report.model_dump(mode="json"), "stage": "complete"}

    return _stream(generate, {"search_id": str(search_id), "stage": "analyzing"})


def _stream(
    operation: Callable[[EventSink], Awaitable[object]],
    initial: object,
    *,
    timeout: float = 600.0,
) -> StreamingResponse:
    return StreamingResponse(
        keep_alive(operation_events(operation, initial, duration=timeout)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
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
