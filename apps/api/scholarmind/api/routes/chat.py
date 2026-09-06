from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Annotated
from uuid import UUID

import orjson
import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from scholarmind.api.schemas import (
    ChatRequest,
    ConversationCollectionResponse,
    ConversationResponse,
)
from scholarmind.api.streaming import keep_alive
from scholarmind.core.metrics import CHAT_DURATION, CHAT_GENERATIONS
from scholarmind.core.security import Principal, get_current_principal
from scholarmind.services.chat import ChatService
from scholarmind.services.llm_stream import ModelStreamError

router = APIRouter(prefix="/papers/{paper_id}", tags=["chat"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
logger = structlog.get_logger(__name__)


@router.post("/chat/stream")
async def stream_chat(
    paper_id: UUID,
    payload: ChatRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> StreamingResponse:
    settings = request.app.state.settings
    if len(payload.query) > settings.max_query_characters:
        from scholarmind.domain.errors import DomainError

        raise DomainError(
            code="query_too_long",
            message="The question exceeds the configured length limit",
            status_code=422,
        )
    service = _chat_service(request)
    prepared = await service.prepare(
        principal.subject,
        paper_id,
        payload.query.strip(),
        payload.conversation_id,
    )

    async def events() -> AsyncGenerator[bytes, None]:
        answer_parts: list[str] = []
        started_at = perf_counter()
        disconnected = False
        yield _event(
            "meta",
            {
                "conversation_id": str(prepared.conversation_id),
                "citations": [citation.to_dict() for citation in prepared.citations],
            },
        )
        try:
            async with asyncio.timeout(600):
                async for token in service.llm.stream(
                    prepared.question,
                    prepared.context,
                    prepared.history,
                ):
                    if await request.is_disconnected():
                        disconnected = True
                        break
                    answer_parts.append(token)
                    yield _event("token", {"text": token})
            answer = "".join(answer_parts)
            await service.save_assistant(prepared, answer)
            result = "cancelled" if disconnected else "succeeded"
            CHAT_GENERATIONS.labels(result).inc()
            CHAT_DURATION.observe(perf_counter() - started_at)
            if not disconnected:
                yield _event("done", {"characters": len(answer)})
        except asyncio.CancelledError:
            await service.save_assistant(prepared, "".join(answer_parts))
            CHAT_GENERATIONS.labels("cancelled").inc()
            CHAT_DURATION.observe(perf_counter() - started_at)
            raise
        except Exception as exc:
            logger.exception("chat_stream_failed", error_type=type(exc).__name__)
            await service.save_assistant(prepared, "".join(answer_parts))
            CHAT_GENERATIONS.labels("failed").inc()
            CHAT_DURATION.observe(perf_counter() - started_at)
            yield _event(
                "error",
                {
                    "code": exc.code if isinstance(exc, ModelStreamError) else "generation_failed",
                    "message": str(exc)
                    if isinstance(exc, ModelStreamError)
                    else "The answer could not be generated",
                },
            )

    return StreamingResponse(
        keep_alive(events()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/conversations", response_model=ConversationCollectionResponse)
async def list_conversations(
    paper_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationCollectionResponse:
    conversations, total = await _chat_service(request).list_conversations(
        principal.subject,
        paper_id,
        limit,
        offset,
    )
    return ConversationCollectionResponse(
        items=[ConversationResponse.model_validate(item) for item in conversations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    paper_id: UUID,
    conversation_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    conversation = await _chat_service(request).get_conversation(
        principal.subject,
        paper_id,
        conversation_id,
    )
    return ConversationResponse.model_validate(conversation)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    paper_id: UUID,
    conversation_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> Response:
    await _chat_service(request).delete_conversation(principal.subject, paper_id, conversation_id)
    return Response(status_code=204)


def _chat_service(request: Request) -> ChatService:
    settings = request.app.state.settings
    return ChatService(
        request.app.state.database.session_factory,
        request.app.state.retriever,
        request.app.state.llm_gateway,
        settings.max_context_characters,
    )


def _event(name: str, data: object) -> bytes:
    return b"event: " + name.encode() + b"\ndata: " + orjson.dumps(data) + b"\n\n"
