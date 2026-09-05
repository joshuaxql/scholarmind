from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, cast

from arq import cron, run_worker
from arq.connections import RedisSettings
from arq.cron import CronJob
from arq.typing import StartupShutdown, WorkerCoroutine, WorkerSettingsBase
from arq.worker import Function

from scholarmind.core.config import get_settings
from scholarmind.workers.jobs import (
    cleanup_expired_papers,
    ingest_paper,
    shutdown,
    startup,
)

settings = get_settings()


class WorkerSettings:
    functions: ClassVar[Sequence[WorkerCoroutine | Function]] = (ingest_paper,)
    cron_jobs: ClassVar[Sequence[CronJob] | None] = (
        cron(
            cleanup_expired_papers,
            hour=3,
            minute=17,
            job_id="scholarmind:retention",
            max_tries=2,
        ),
    )
    on_startup: ClassVar[StartupShutdown | None] = startup
    on_shutdown: ClassVar[StartupShutdown | None] = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    job_timeout = 15 * 60
    max_jobs = 4
    max_tries = settings.ingestion_max_attempts
    keep_result = 60 * 60
    health_check_interval = 30


def run() -> None:
    run_worker(cast(type[WorkerSettingsBase], WorkerSettings))
