from __future__ import annotations

import json
import re
import time
from time import perf_counter
from uuid import uuid4

import structlog
from redis.exceptions import RedisError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from scholarmind.core.metrics import HTTP_IN_PROGRESS, HTTP_REQUEST_DURATION, HTTP_REQUESTS
from scholarmind.core.rate_limit import RateLimiter

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_UUID_PATH_SEGMENT = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_NUMERIC_PATH_SEGMENT = re.compile(r"/\d+(?=/|$)")
logger = structlog.get_logger(__name__)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        proposed = headers.get("x-request-id", "")
        request_id = proposed if _REQUEST_ID_PATTERN.fullmatch(proposed) else str(uuid4())
        method = str(scope.get("method", "UNKNOWN")).upper()
        started_at = perf_counter()
        status_code = 500
        bytes_sent = 0
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, method=method)
        scope.setdefault("state", {})["request_id"] = request_id
        HTTP_IN_PROGRESS.labels(method).inc()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, bytes_sent
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = response_headers
            elif message["type"] == "http.response.body":
                bytes_sent += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration = perf_counter() - started_at
            route = _route_name(scope)
            HTTP_IN_PROGRESS.labels(method).dec()
            HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
            HTTP_REQUEST_DURATION.labels(method, route).observe(duration)
            logger.info(
                "http_request_completed",
                route=route,
                status_code=status_code,
                duration_ms=round(duration * 1000, 2),
                bytes_sent=bytes_sent,
            )
            structlog.contextvars.clear_contextvars()


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (b"cross-origin-resource-policy", b"same-site"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, limiter: RateLimiter) -> None:
        self.app = app
        self.limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = _headers(scope)
        authorization = headers.get("authorization")
        client = scope.get("client")
        remote = client[0] if client else "unknown"
        key = authorization or remote
        try:
            result = await self.limiter.check(key)
        except RedisError:
            await _json_error(
                send,
                503,
                "rate_limiter_unavailable",
                "Service temporarily unavailable",
            )
            return

        if not result.allowed:
            await _json_error(
                send,
                429,
                "rate_limit_exceeded",
                "Too many requests",
                extra_headers=[
                    (b"retry-after", str(max(1, result.reset_epoch - int(time.time()))).encode())
                ],
            )
            return

        async def send_with_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-ratelimit-limit", str(result.limit).encode()),
                        (b"x-ratelimit-remaining", str(result.remaining).encode()),
                        (b"x-ratelimit-reset", str(result.reset_epoch).encode()),
                    ]
                )
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_limit_headers)


def _route_name(scope: Scope) -> str:
    route = scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path
    path = str(scope.get("path", "unknown"))
    path = _UUID_PATH_SEGMENT.sub("/{id}", path)
    return _NUMERIC_PATH_SEGMENT.sub("/{id}", path)


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


async def _json_error(
    send: Send,
    status_code: int,
    code: str,
    message: str,
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    headers = [(b"content-type", b"application/json"), *(extra_headers or [])]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})
