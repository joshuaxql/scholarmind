from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from scholarmind import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    version: str = __version__
    checks: dict[str, str] = Field(default_factory=dict)


@router.get("/health/live", response_model=HealthResponse, include_in_schema=False)
async def live() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse, include_in_schema=False)
async def ready(request: Request, response: Response) -> HealthResponse:
    settings = request.app.state.settings
    dependencies: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("database", request.app.state.database.ping),
        ("storage", request.app.state.object_store.healthcheck),
        ("retrieval", request.app.state.retriever.healthcheck),
    ]
    if settings.queue_mode == "arq":
        dependencies.append(("redis", request.app.state.rate_limiter.ping))

    results = await asyncio.gather(*[_check(name, check) for name, check in dependencies])
    checks = dict(results)
    if any(value != "ok" for value in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", checks=checks)
    return HealthResponse(checks=checks)


async def _check(
    name: str,
    operation: Callable[[], Awaitable[None]],
) -> tuple[str, str]:
    try:
        async with asyncio.timeout(3):
            await operation()
        return name, "ok"
    except Exception:  # readiness deliberately suppresses internal dependency details
        return name, "unavailable"
