from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from scholarmind.core.config import Environment, Settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_epoch: int


class RateLimiter:
    def __init__(self, settings: Settings) -> None:
        self._limit = settings.rate_limit_requests
        self._window = settings.rate_limit_window_seconds
        self._fail_closed = settings.environment == Environment.PRODUCTION
        self._use_redis = settings.queue_mode == "arq"
        self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self._memory: dict[tuple[str, int], int] = {}
        self._lock = asyncio.Lock()

    async def check(self, raw_key: str) -> RateLimitResult:
        now = int(time.time())
        window_id = now // self._window
        reset = (window_id + 1) * self._window
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()[:32]
        if not self._use_redis:
            return await self._check_memory(key_hash, window_id, reset)
        redis_key = f"scholarmind:rate:{window_id}:{key_hash}"
        try:
            pipeline = self._redis.pipeline(transaction=True)
            pipeline.incr(redis_key)
            pipeline.expire(redis_key, self._window + 1)
            count, _ = await pipeline.execute()
            return self._result(int(count), reset)
        except RedisError as exc:
            logger.warning("rate_limit_redis_unavailable", error_type=type(exc).__name__)
            if self._fail_closed:
                raise
            return await self._check_memory(key_hash, window_id, reset)

    async def ping(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        await self._redis.aclose()

    async def _check_memory(self, key_hash: str, window_id: int, reset: int) -> RateLimitResult:
        async with self._lock:
            current_key = (key_hash, window_id)
            count = self._memory.get(current_key, 0) + 1
            self._memory[current_key] = count
            if len(self._memory) > 10_000:
                self._memory = {
                    key: value for key, value in self._memory.items() if key[1] >= window_id
                }
        return self._result(count, reset)

    def _result(self, count: int, reset: int) -> RateLimitResult:
        return RateLimitResult(
            allowed=count <= self._limit,
            limit=self._limit,
            remaining=max(0, self._limit - count),
            reset_epoch=reset,
        )
