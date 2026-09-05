from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse

from scholarmind.domain.errors import DomainError

_NEW_ID = re.compile(r"^(?P<base>\d{4}\.\d{4,5})(?:v(?P<version>[1-9]\d*))?$")
_OLD_ID = re.compile(r"^(?P<base>[a-z][a-z0-9-]*(?:\.[A-Z]{2})?/\d{7})(?:v(?P<version>[1-9]\d*))?$")
_ARXIV_PREFIX = re.compile(r"^arxiv:\s*", re.IGNORECASE)
_ALLOWED_HOSTS = frozenset({"arxiv.org", "www.arxiv.org", "export.arxiv.org"})
_ALLOWED_PATH_PREFIXES = ("/abs/", "/pdf/", "/e-print/")


@dataclass(frozen=True, slots=True)
class ArxivIdentifier:
    canonical: str
    base_id: str
    version: int | None

    @property
    def abstract_url(self) -> str:
        return f"https://arxiv.org/abs/{quote(self.canonical, safe='/')}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{quote(self.canonical, safe='/')}.pdf"


def parse_arxiv_identifier(value: str) -> ArxivIdentifier:
    candidate = value.strip()
    if not candidate or len(candidate) > 256:
        raise _invalid_identifier()

    if "://" in candidate:
        parsed = urlparse(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or parsed.query
            or parsed.fragment
        ):
            raise _invalid_identifier()
        path = unquote(parsed.path)
        prefix = next((item for item in _ALLOWED_PATH_PREFIXES if path.startswith(item)), None)
        if prefix is None:
            raise _invalid_identifier()
        candidate = path.removeprefix(prefix)
        if prefix == "/pdf/" and candidate.endswith(".pdf"):
            candidate = candidate[:-4]
    else:
        candidate = _ARXIV_PREFIX.sub("", candidate)

    candidate = candidate.strip("/")
    match = _NEW_ID.fullmatch(candidate) or _OLD_ID.fullmatch(candidate)
    if match is None:
        raise _invalid_identifier()

    base_id = match.group("base")
    raw_version = match.group("version")
    version = int(raw_version) if raw_version is not None else None
    canonical = f"{base_id}v{version}" if version is not None else base_id
    return ArxivIdentifier(canonical=canonical, base_id=base_id, version=version)


def _invalid_identifier() -> DomainError:
    return DomainError(
        code="invalid_arxiv_identifier",
        message="Enter a canonical arXiv ID or an arxiv.org abstract/PDF URL",
        status_code=422,
    )
