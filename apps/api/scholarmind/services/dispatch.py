from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from importlib import import_module
from typing import Any, Protocol, cast
from uuid import UUID

import structlog
from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.jobs import Job

from scholarmind.core.config import Settings

logger = structlog.get_logger(__name__)


class JobDispatcher(Protocol):
    async def enqueue(self, job_id: UUID, request_id: str | None = None) -> str: ...

    async def close(self) -> None: ...


class ArqJobDispatcher:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, job_id: UUID, request_id: str | None = None) -> str:
        queue_id = f"ingestion:{job_id}"
        queued: Job | None = await self._pool.enqueue_job(
            "ingest_paper", str(job_id), request_id, _job_id=queue_id
        )
        if queued is None:
            logger.info("ingestion_already_enqueued", job_id=str(job_id), queue_id=queue_id)
        return queue_id

    async def close(self) -> None:
        await self._pool.aclose()


class InlineJobDispatcher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, job_id: UUID, request_id: str | None = None) -> str:
        worker_module = import_module("scholarmind.workers.jobs")
        handler = cast(
            Callable[[UUID, Settings, str | None], Coroutine[Any, Any, None]],
            worker_module.run_ingestion_job,
        )
        coroutine = handler(job_id, self._settings, request_id)
        task = asyncio.create_task(coroutine, name=f"ingestion:{job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task.get_name()

    async def close(self) -> None:
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


async def build_dispatcher(settings: Settings) -> JobDispatcher:
    if settings.queue_mode == "arq":
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        return ArqJobDispatcher(pool)
    return InlineJobDispatcher(settings)
