from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from scholarmind.core.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str


async def get_current_principal(
    credentials: Credentials,
    settings: SettingsDependency,
) -> Principal:
    if not settings.auth_required:
        return Principal(subject="local-user")

    expected = settings.api_bearer_token.get_secret_value() if settings.api_bearer_token else ""
    supplied = (
        credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
    )
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_credentials",
                "message": "Valid bearer credentials are required",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    digest = hashlib.sha256(supplied.encode()).hexdigest()[:24]
    return Principal(subject=f"token:{digest}")
