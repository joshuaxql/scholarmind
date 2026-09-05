from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from scholarmind.api.schemas import ErrorBody, ErrorResponse
from scholarmind.domain.errors import DomainError

logger = structlog.get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected_error)


async def _domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _response(request, exc.status_code, exc.code, exc.message, exc.details)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = {
        "fields": [
            {"path": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
            for error in exc.errors()
        ]
    }
    return _response(request, 422, "validation_error", "Request validation failed", details)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    detail = exc.detail
    details: dict[str, Any]
    if isinstance(detail, dict):
        code = str(detail.get("code", "http_error"))
        message = str(detail.get("message", "Request failed"))
        details = {key: value for key, value in detail.items() if key not in {"code", "message"}}
    else:
        code = "http_error"
        message = str(detail)
        details = {}
    return _response(request, exc.status_code, code, message, details, exc.headers)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_request_error", error_type=type(exc).__name__)
    return _response(request, 500, "internal_error", "An unexpected error occurred", {})


def _response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details,
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=headers,
    )
