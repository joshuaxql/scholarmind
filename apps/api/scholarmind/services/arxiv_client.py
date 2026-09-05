from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import aiofiles
import aiofiles.os
import httpx
import structlog
from defusedxml import ElementTree

from scholarmind.core.config import Settings
from scholarmind.domain.arxiv import ArxivIdentifier
from scholarmind.services.ingestion_errors import IngestionError

logger = structlog.get_logger(__name__)
_ALLOWED_HOSTS = frozenset({"arxiv.org", "www.arxiv.org", "export.arxiv.org"})
_ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True, slots=True)
class ArxivMetadata:
    title: str
    authors: list[str]
    abstract: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class DownloadedPaper:
    path: Path
    sha256: str
    size_bytes: int


class ArxivClient:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def fetch_metadata(self, identifier: ArxivIdentifier) -> ArxivMetadata | None:
        url = f"https://export.arxiv.org/api/query?id_list={quote(identifier.canonical, safe='/')}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise IngestionError("metadata_too_large", "arXiv metadata response is too large")
            return _parse_metadata(response.content)
        except (httpx.HTTPError, ValueError, ElementTree.ParseError) as exc:
            logger.warning(
                "arxiv_metadata_unavailable",
                arxiv_id=identifier.canonical,
                error_type=type(exc).__name__,
            )
            return None

    async def download_pdf(self, identifier: ArxivIdentifier, destination: Path) -> DownloadedPaper:
        url = identifier.pdf_url
        for _ in range(4):
            _validate_remote_url(url)
            async with self.client.stream("GET", url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise IngestionError("invalid_redirect", "arXiv returned an empty redirect")
                    url = urljoin(url, location)
                    continue
                if response.status_code == 404:
                    raise IngestionError("paper_not_found", "The arXiv PDF was not found")
                if response.status_code == 429 or response.status_code >= 500:
                    raise IngestionError(
                        "arxiv_temporarily_unavailable",
                        "arXiv is temporarily unavailable",
                        retryable=True,
                    )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise IngestionError(
                        "download_failed", "The arXiv PDF could not be downloaded"
                    ) from exc

                declared_size = int(response.headers.get("content-length", "0") or "0")
                if declared_size > self.settings.max_pdf_bytes:
                    raise IngestionError(
                        "pdf_too_large",
                        "The PDF exceeds the configured size limit",
                    )

                digest = hashlib.sha256()
                total = 0
                prefix = bytearray()
                async with aiofiles.open(destination, "wb") as output:
                    async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                        total += len(chunk)
                        if total > self.settings.max_pdf_bytes:
                            raise IngestionError(
                                "pdf_too_large", "The PDF exceeds the configured size limit"
                            )
                        if len(prefix) < 5:
                            prefix.extend(chunk[: 5 - len(prefix)])
                        digest.update(chunk)
                        await output.write(chunk)

                if bytes(prefix) != b"%PDF-":
                    await aiofiles.os.remove(destination)
                    raise IngestionError("invalid_pdf", "arXiv did not return a valid PDF")
                if total == 0:
                    raise IngestionError("empty_pdf", "arXiv returned an empty PDF")
                return DownloadedPaper(destination, digest.hexdigest(), total)
        raise IngestionError("too_many_redirects", "arXiv redirected the request too many times")


def build_http_client(settings: Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(
        connect=settings.download_connect_timeout_seconds,
        read=settings.download_read_timeout_seconds,
        write=30.0,
        pool=10.0,
    )
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={
            "User-Agent": settings.arxiv_user_agent,
            "Accept": "application/pdf, application/atom+xml",
        },
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise IngestionError("unsafe_redirect", "arXiv redirected to a disallowed host")


def _parse_metadata(content: bytes) -> ArxivMetadata | None:
    root = ElementTree.fromstring(content)
    entry = root.find(f"{_ATOM}entry")
    if entry is None:
        return None
    title = _normalized_text(entry.findtext(f"{_ATOM}title"))
    abstract = _normalized_text(entry.findtext(f"{_ATOM}summary"))
    authors = [
        _normalized_text(author.findtext(f"{_ATOM}name"))
        for author in entry.findall(f"{_ATOM}author")
    ]
    authors = [author for author in authors if author]
    published_raw = entry.findtext(f"{_ATOM}published")
    published = (
        datetime.fromisoformat(published_raw.replace("Z", "+00:00")) if published_raw else None
    )
    return ArxivMetadata(title=title, authors=authors, abstract=abstract, published_at=published)


def _normalized_text(value: str | None) -> str:
    return " ".join((value or "").split())
