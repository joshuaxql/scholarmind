from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from scholarmind.services.ingestion_errors import IngestionError

PARSER_VERSION = "pypdf-page-v1"
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][^.!?]{2,100}$")


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    ordinal: int
    text: str
    page_number: int
    section: str | None
    token_count: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ParsedPaper:
    markdown: str
    chunks: list[ParsedChunk]
    page_count: int


class PdfParser:
    def __init__(self, *, max_pages: int = 500, chunk_characters: int = 2800) -> None:
        self.max_pages = max_pages
        self.chunk_characters = chunk_characters

    async def parse(self, path: Path) -> ParsedPaper:
        return await asyncio.to_thread(self._parse_sync, path)

    def _parse_sync(self, path: Path) -> ParsedPaper:
        try:
            reader = PdfReader(path, strict=False)
            if reader.is_encrypted:
                raise IngestionError("encrypted_pdf", "Encrypted PDFs are not supported")
            if not reader.pages:
                raise IngestionError("empty_pdf", "The PDF has no pages")
            if len(reader.pages) > self.max_pages:
                raise IngestionError("too_many_pages", "The PDF exceeds the page limit")

            markdown_pages: list[str] = []
            chunks: list[ParsedChunk] = []
            ordinal = 0
            current_section: str | None = None
            for page_number, page in enumerate(reader.pages, start=1):
                text = _clean_text(page.extract_text() or "")
                if not text:
                    continue
                markdown_pages.append(f"## Page {page_number}\n\n{text}")
                for part, section in _chunk_page(text, self.chunk_characters, current_section):
                    current_section = section or current_section
                    digest = hashlib.sha256(part.encode()).hexdigest()
                    chunks.append(
                        ParsedChunk(
                            ordinal=ordinal,
                            text=part,
                            page_number=page_number,
                            section=current_section,
                            token_count=max(1, len(part) // 4),
                            content_sha256=digest,
                        )
                    )
                    ordinal += 1
        except IngestionError:
            raise
        except (PdfReadError, OSError, ValueError) as exc:
            raise IngestionError("pdf_parse_failed", "The PDF could not be parsed") from exc

        if not chunks:
            raise IngestionError(
                "no_extractable_text",
                "No extractable text was found; scanned PDFs require OCR",
            )
        return ParsedPaper(
            markdown="\n\n".join(markdown_pages) + "\n",
            chunks=chunks,
            page_count=len(reader.pages),
        )


def _chunk_page(
    text: str,
    limit: int,
    inherited_section: str | None,
) -> list[tuple[str, str | None]]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    result: list[tuple[str, str | None]] = []
    buffer: list[str] = []
    size = 0
    section = inherited_section

    def flush() -> None:
        nonlocal buffer, size
        if buffer:
            result.append(("\n\n".join(buffer), section))
            overlap = buffer[-1:] if len(buffer[-1]) < 500 else []
            buffer = overlap
            size = sum(len(item) for item in buffer)

    for paragraph in paragraphs:
        first_line = paragraph.splitlines()[0].strip()
        if _HEADING.fullmatch(first_line):
            flush()
            section = first_line
        if len(paragraph) > limit:
            flush()
            for start in range(0, len(paragraph), limit):
                part = paragraph[start : start + limit].strip()
                if part:
                    result.append((part, section))
            continue
        if buffer and size + len(paragraph) + 2 > limit:
            flush()
        buffer.append(paragraph)
        size += len(paragraph) + 2
    flush()
    return result


def _clean_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\x00", "").splitlines()]
    output: list[str] = []
    blank = False
    for line in lines:
        normalized = " ".join(line.split())
        if not normalized:
            if output and not blank:
                output.append("")
            blank = True
        else:
            output.append(normalized)
            blank = False
    return "\n".join(output).strip()
