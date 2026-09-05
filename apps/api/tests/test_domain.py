from __future__ import annotations

import pytest

from scholarmind.domain.arxiv import parse_arxiv_identifier
from scholarmind.domain.errors import ConflictError, DomainError
from scholarmind.domain.papers import (
    JobStage,
    PaperStatus,
    ensure_paper_transition,
    progress_for_stage,
)


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("2501.06713", "2501.06713"),
        ("arXiv: 2501.06713v2", "2501.06713v2"),
        ("https://arxiv.org/abs/2501.06713", "2501.06713"),
        ("https://export.arxiv.org/pdf/2501.06713v3.pdf", "2501.06713v3"),
        ("hep-th/9901001", "hep-th/9901001"),
    ],
)
def test_normalizes_supported_arxiv_identifiers(raw: str, canonical: str) -> None:
    identifier = parse_arxiv_identifier(raw)
    assert identifier.canonical == canonical
    assert identifier.pdf_url.startswith("https://arxiv.org/pdf/")


@pytest.mark.parametrize(
    "raw",
    [
        "https://evil.example/abs/2501.06713",
        "https://arxiv.org.evil.example/abs/2501.06713",
        "https://arxiv.org@evil.example/abs/2501.06713",
        "https://arxiv.org:444/abs/2501.06713",
        "https://arxiv.org/abs/2501.06713?redirect=http://evil.example",
        "../../etc/passwd",
        "file:///etc/passwd",
        "2501.06713v0",
    ],
)
def test_rejects_noncanonical_or_ssrf_identifiers(raw: str) -> None:
    with pytest.raises(DomainError, match="canonical arXiv") as raised:
        parse_arxiv_identifier(raw)
    assert raised.value.code == "invalid_arxiv_identifier"


def test_paper_state_machine_rejects_skipped_stages() -> None:
    ensure_paper_transition(PaperStatus.QUEUED, PaperStatus.DOWNLOADING)
    with pytest.raises(ConflictError) as raised:
        ensure_paper_transition(PaperStatus.QUEUED, PaperStatus.READY)
    assert raised.value.code == "invalid_paper_transition"


def test_stage_progress_is_monotonic() -> None:
    stages = list(JobStage)
    values = [progress_for_stage(stage) for stage in stages]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 100
