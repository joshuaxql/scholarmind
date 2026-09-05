from __future__ import annotations

from enum import StrEnum


class ResearchStatus(StrEnum):
    SEARCHED = "searched"
    ANALYZING = "analyzing"
    COMPLETE = "complete"
    FAILED = "failed"


class ResearchSort(StrEnum):
    RELEVANCE = "relevance"
    SUBMITTED_DATE = "submitted_date"
    UPDATED_DATE = "updated_date"
