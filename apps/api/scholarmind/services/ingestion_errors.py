from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IngestionError(Exception):
    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.message
