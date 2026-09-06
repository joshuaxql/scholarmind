from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing

import anyio
import orjson
import structlog

from scholarmind.domain.errors import DomainError

HEARTBEAT_SECONDS = 10.0
GENERATION_TIMEOUT_SECONDS = 600.0
EventSink = Callable[[str, object], Awaitable[None]]


def encode_event(name: str, data: object) -> bytes:
    return b"event: " + name.encode() + b"\ndata: " + orjson.dumps(data) + b"\n\n"


async def operation_events(
    operation: Callable[[EventSink], Awaitable[object]],
    initial: object,
    *,
    duration: float = GENERATION_TIMEOUT_SECONDS,
) -> AsyncGenerator[bytes, None]:
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)

    async def emit(name: str, data: object) -> None:
        await queue.put(encode_event(name, data))

    async def run() -> None:
        try:
            async with asyncio.timeout(duration):
                result = await operation(emit)
            await emit("done", result)
        except DomainError as exc:
            await emit("error", {"code": exc.code, "message": exc.message})
        except TimeoutError:
            await emit(
                "error",
                {
                    "code": "generation_timeout",
                    "message": "Generation timed out; please retry",
                },
            )
        except Exception as exc:
            structlog.get_logger(__name__).warning(
                "generation_failed", error_type=type(exc).__name__
            )
            await emit(
                "error",
                {
                    "code": "generation_failed",
                    "message": "The model output could not be completed; please retry",
                },
            )
        await queue.put(None)

    task = asyncio.create_task(run())
    try:
        yield encode_event("meta", initial)
        while (item := await queue.get()) is not None:
            yield item
    finally:
        task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(task, return_exceptions=True)


async def keep_alive(events: AsyncGenerator[bytes, None]) -> AsyncGenerator[bytes, None]:
    """Keep an idle SSE connection open, with bounded buffering and disconnect cleanup."""
    queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue(maxsize=16)

    async def produce() -> None:
        try:
            async with aclosing(events):
                async for event in events:
                    await queue.put(event)
        except Exception as exc:
            await queue.put(exc)
        else:
            await queue.put(None)

    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield b": keep-alive\n\n"
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        producer.cancel()
        # Starlette cancels its task group on disconnect. Allow the producer to
        # close the provider connection and restore the report's retryable state.
        with anyio.CancelScope(shield=True):
            await asyncio.gather(producer, return_exceptions=True)
