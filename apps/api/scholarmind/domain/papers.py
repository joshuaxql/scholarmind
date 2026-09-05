from __future__ import annotations

from enum import StrEnum

from scholarmind.domain.errors import ConflictError


class PaperStatus(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PARSING = "parsing"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStage(StrEnum):
    QUEUED = "queued"
    METADATA = "metadata"
    DOWNLOAD = "download"
    PARSE = "parse"
    STORE = "store"
    INDEX = "index"
    COMPLETE = "complete"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


_ALLOWED_TRANSITIONS: dict[PaperStatus, frozenset[PaperStatus]] = {
    PaperStatus.QUEUED: frozenset({PaperStatus.DOWNLOADING, PaperStatus.FAILED}),
    PaperStatus.DOWNLOADING: frozenset({PaperStatus.PARSING, PaperStatus.FAILED}),
    PaperStatus.PARSING: frozenset({PaperStatus.INDEXING, PaperStatus.FAILED}),
    PaperStatus.INDEXING: frozenset({PaperStatus.READY, PaperStatus.FAILED}),
    PaperStatus.READY: frozenset({PaperStatus.QUEUED}),
    PaperStatus.FAILED: frozenset({PaperStatus.QUEUED}),
}

_STAGE_PROGRESS: dict[JobStage, int] = {
    JobStage.QUEUED: 0,
    JobStage.METADATA: 8,
    JobStage.DOWNLOAD: 22,
    JobStage.PARSE: 48,
    JobStage.STORE: 68,
    JobStage.INDEX: 82,
    JobStage.COMPLETE: 100,
}


def ensure_paper_transition(current: PaperStatus, target: PaperStatus) -> None:
    if current == target:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ConflictError(
            "invalid_paper_transition",
            f"Cannot move paper from {current.value} to {target.value}",
            current=current.value,
            target=target.value,
        )


def progress_for_stage(stage: JobStage) -> int:
    return _STAGE_PROGRESS[stage]
