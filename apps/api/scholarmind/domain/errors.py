from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class NotFoundError(DomainError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(
            code="resource_not_found",
            message=f"{resource} was not found",
            status_code=404,
            details={"resource": resource, "id": resource_id},
        )


class ConflictError(DomainError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(code=code, message=message, status_code=409, details=details)
