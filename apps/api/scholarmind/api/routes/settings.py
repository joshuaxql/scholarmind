from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response

from scholarmind.api.schemas import EnvironmentResponse, EnvironmentUpdateRequest
from scholarmind.core.security import Principal, get_current_principal
from scholarmind.domain.errors import DomainError
from scholarmind.services.environment import LOOPBACK_HOSTS, EnvironmentService

router = APIRouter(prefix="/settings", tags=["settings"])
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def _service(request: Request, response: Response) -> EnvironmentService:
    response.headers["Cache-Control"] = "no-store"
    # This is a local machine editor, not a remotely accessible administration API.
    if (
        not request.client
        or request.client.host not in LOOPBACK_HOSTS
        or request.url.hostname not in LOOPBACK_HOSTS
        or request.app.state.settings.api_host not in LOOPBACK_HOSTS
        or request.headers.get("x-scholarmind-settings") != "1"
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise DomainError(
            "settings_local_only", "Settings are available only from the local workspace", 403
        )
    return cast(EnvironmentService, request.app.state.environment_service)


@router.get("", response_model=EnvironmentResponse)
async def read_settings(
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> EnvironmentResponse:
    return EnvironmentResponse.model_validate(await _service(request, response).read())


@router.post("", response_model=EnvironmentResponse)
async def save_settings(
    payload: EnvironmentUpdateRequest,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
) -> EnvironmentResponse:
    service = _service(request, response)
    return EnvironmentResponse.model_validate(await service.save(payload.revision, payload.updates))
