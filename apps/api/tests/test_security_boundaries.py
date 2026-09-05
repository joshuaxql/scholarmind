from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from scholarmind.core.config import Settings
from scholarmind.domain.arxiv import parse_arxiv_identifier
from scholarmind.services.arxiv_client import ArxivClient
from scholarmind.services.ingestion_errors import IngestionError
from scholarmind.services.storage import LocalObjectStore


@pytest.mark.asyncio
async def test_pdf_redirect_cannot_escape_arxiv_allowlist(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "arxiv.org"
        return httpx.Response(302, headers={"location": "https://169.254.169.254/latest/meta-data"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        arxiv = ArxivClient(client, Settings())
        with pytest.raises(IngestionError) as raised:
            await arxiv.download_pdf(parse_arxiv_identifier("2501.06713"), tmp_path / "paper.pdf")
    assert raised.value.code == "unsafe_redirect"
    assert not (tmp_path / "paper.pdf").exists()


@pytest.mark.asyncio
async def test_pdf_stream_enforces_actual_size_not_only_content_length(tmp_path: Path) -> None:
    body = b"%PDF-" + b"x" * 1200

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=body)

    settings = Settings(max_pdf_bytes=1024)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IngestionError) as raised:
            await ArxivClient(client, settings).download_pdf(
                parse_arxiv_identifier("2501.06713"), tmp_path / "paper.pdf"
            )
    assert raised.value.code == "pdf_too_large"


@pytest.mark.asyncio
async def test_local_object_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    await store.ensure_ready()
    with pytest.raises(ValueError, match="Invalid object key"):
        await store.put_bytes("../secret", b"no", "text/plain")
    with pytest.raises(ValueError, match="Invalid object key"):
        await store.put_bytes("papers\\secret", b"no", "text/plain")
