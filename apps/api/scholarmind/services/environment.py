"""Read and atomically update the repository's fixed .env file, never runtime state."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values
from dotenv.parser import parse_stream
from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from sqlalchemy.engine import make_url

from scholarmind.core.config import Settings
from scholarmind.domain.errors import ConflictError, DomainError

ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
SECRET_KEYS = {
    "API_BEARER_TOKEN",
    "API_INTERNAL_BEARER_TOKEN",
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "QDRANT_API_KEY",
}


class FileSettings(Settings):
    """Validate the future configuration independently of inherited process variables."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=3000, ge=1, le=65535)
    api_internal_url: str = "http://127.0.0.1:8000"
    api_internal_bearer_token: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)

    @model_validator(mode="after")
    def validate_launcher(self) -> FileSettings:
        for name in ("api_host", "web_host"):
            host = getattr(self, name)
            if not host or re.search(r"[\s/\\?#@]", host):
                raise ValueError(f"{name.upper()} must be a hostname or IP address")
        for name in ("api_internal_url", "web_origin", "s3_endpoint_url", "qdrant_url"):
            value = getattr(self, name)
            if not value:
                continue
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme in {"http", "https"} and parsed.hostname and parsed.port != 0
                valid = valid and not (
                    parsed.username or parsed.password or parsed.query or parsed.fragment
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    f"{name.upper()} must be an HTTP(S) URL without credentials or query"
                )
        try:
            make_url(self.database_url)
        except Exception as exc:
            raise ValueError("DATABASE_URL must be a valid SQLAlchemy connection URL") from exc
        if self.auth_required:
            token = self.api_bearer_token.get_secret_value() if self.api_bearer_token else ""
            internal = self.api_internal_bearer_token
            if not token.strip():
                raise ValueError("AUTH_REQUIRED requires API_BEARER_TOKEN")
            if internal and internal.get_secret_value() != token:
                raise ValueError(
                    "API_INTERNAL_BEARER_TOKEN must match API_BEARER_TOKEN or be empty"
                )
        return self


def _group(key: str) -> str:
    if key.startswith("LLM_") or key == "MAX_CONTEXT_CHARACTERS":
        return "llm"
    if key.startswith("EMBEDDING_"):
        return "embedding"
    if key.startswith(("ARXIV_", "RESEARCH_")):
        return "research"
    if key.startswith(("MAX_PDF_", "DOWNLOAD_", "INGESTION_")) or key == "MAX_QUERY_CHARACTERS":
        return "ingestion"
    if key.startswith(("S3_", "QDRANT_")) or key in {
        "DATABASE_URL",
        "REDIS_URL",
        "QUEUE_MODE",
        "STORAGE_BACKEND",
        "LOCAL_STORAGE_PATH",
        "RETRIEVAL_BACKEND",
        "PAPER_RETENTION_DAYS",
        "AUTO_CREATE_SCHEMA",
        "WORKER_METRICS_PORT",
    }:
        return "storage"
    if key.startswith("RATE_LIMIT_") or key in {"AUTH_REQUIRED", "API_BEARER_TOKEN"}:
        return "security"
    return "runtime"


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _sensitive(key: str, value: str) -> bool:
    # Mask suspicious URL contents in full; malformed URLs must not leak credentials either.
    return key in SECRET_KEYS or (key.endswith("_URL") and any(c in value for c in ("@", "?", "#")))


class EnvironmentService:
    def __init__(self, path: Path = ENV_PATH) -> None:
        self.path = path
        self.lock = asyncio.Lock()
        self.revision_key = secrets.token_bytes(32)
        self.initial_revision: str | None = None

    def _revision(self, raw: bytes) -> str:
        return hmac.new(self.revision_key, raw, hashlib.sha256).hexdigest()

    def _read(self) -> tuple[bytes, dict[str, str]]:
        try:
            if self.path.is_symlink():
                raise OSError("Symlink targets are not editable")
            raw = self.path.read_bytes() if self.path.exists() else b""
            if len(raw) > 128 * 1024:
                raise OSError("Configuration exceeds size limit")
            text = raw.decode("utf-8-sig")
            if any(binding.error for binding in parse_stream(io.StringIO(text))):
                raise DomainError(
                    "settings_file_invalid", ".env contains invalid dotenv syntax", 422
                )
            values = dotenv_values(stream=io.StringIO(text), interpolate=False)
        except (OSError, UnicodeError) as exc:
            raise DomainError(
                "settings_unavailable", "Cannot read the local .env file", 503
            ) from exc
        return raw, {key.upper(): value or "" for key, value in values.items()}

    async def initialize(self) -> None:
        try:
            raw, _ = await asyncio.to_thread(self._read)
            self.initial_revision = self._revision(raw)
        except DomainError:
            # A read-only deployment must still be able to serve papers.
            pass

    def _snapshot(self, raw: bytes, values: dict[str, str]) -> dict[str, Any]:
        schema = FileSettings.model_json_schema()
        defaults = FileSettings().model_dump(mode="json")
        fields = []
        for name, definition in schema["properties"].items():
            key = name.upper()
            value = values.get(key, _string(defaults[name]))
            sensitive = _sensitive(key, value)
            shape = definition.get("anyOf", [definition])[0]
            if "$ref" in shape:
                shape = schema["$defs"][shape["$ref"].split("/")[-1]]
            if shape.get("type") == "boolean":
                value = "true" if value.lower() in {"true", "1", "yes", "on"} else "false"
            fields.append(
                {
                    "key": key,
                    "group": _group(key),
                    "kind": shape.get("type", "string"),
                    "options": shape.get("enum", []),
                    "minimum": shape.get("minimum", shape.get("exclusiveMinimum")),
                    "maximum": shape.get("maximum"),
                    "exclusive_minimum": "exclusiveMinimum" in shape,
                    "sensitive": sensitive,
                    "configured": bool(value),
                    "value": None if sensitive else value,
                    "in_file": key in values,
                }
            )
        revision = self._revision(raw)
        return {
            "revision": revision,
            "restart_required": self.initial_revision is not None
            and revision != self.initial_revision,
            "fields": fields,
        }

    async def read(self) -> dict[str, Any]:
        async with self.lock:
            raw, values = await asyncio.to_thread(self._read)
            return self._snapshot(raw, values)

    @staticmethod
    def _validate(values: dict[str, str]) -> None:
        data: dict[str, Any] = {}
        for name, field in FileSettings.model_fields.items():
            if name.upper() not in values:
                continue
            value: Any = values[name.upper()]
            if value == "" and field.default is None:
                value = None
            if name == "cors_origins":
                try:
                    value = json.loads(value)
                except (TypeError, ValueError) as exc:
                    raise DomainError(
                        "settings_invalid", "CORS_ORIGINS must be a JSON array", 422
                    ) from exc
            data[name] = value
        try:
            FileSettings(**data)
        except ValidationError as exc:
            # Never serialize Pydantic input/context: both may contain submitted secrets.
            errors = [
                f"{'.'.join(str(part).upper() for part in error['loc']) or 'Configuration'}: "
                f"{error['msg']}"
                for error in exc.errors(include_input=False, include_context=False)
            ]
            raise DomainError("settings_invalid", "; ".join(errors), 422) from None

    def _write(self, raw: bytes, updates: dict[str, str]) -> None:
        remaining = updates.copy()
        parts = []
        for binding in parse_stream(io.StringIO(raw.decode("utf-8-sig"))):
            key = binding.key.upper() if binding.key else None
            if key not in updates:
                parts.append(binding.original.string)
                continue
            assert key is not None
            # Preserve whitespace and trailing comments, including on quoted assignments.
            original = binding.original.string
            prefix = re.match(r"\s*", original)
            comment = re.fullmatch(
                r"\s*(?:export\s+)?[^=]+=[ \t]*"
                r"(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|[^\r\n]*?)"
                r"([ \t]+#[^\r\n]*)?[\r\n]*",
                original,
                re.DOTALL,
            )
            suffix = (comment.group(1) or "") if comment else ""
            parts.append(
                f"{prefix.group() if prefix else ''}{key}={self._quote(updates[key])}{suffix}\n"
            )
            remaining.pop(key, None)
        text = "".join(parts)
        if remaining and text and not text.endswith("\n"):
            text += "\n"
        text += "".join(f"{key}={self._quote(value)}\n" for key, value in remaining.items())
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, prefix=".env.", delete=False
            ) as handle:
                temporary = handle.name
                handle.write(text.replace("\r\n", "\n").encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                os.chmod(temporary, self.path.stat().st_mode)
            # Catch an external edit made while preparing the replacement.
            current, _ = self._read()
            if current != raw:
                raise ConflictError(
                    "settings_conflict", ".env changed. Reload settings before saving"
                )
            os.replace(temporary, self.path)
        except OSError as exc:
            raise DomainError(
                "settings_write_failed", "Cannot save .env; the original file is unchanged", 503
            ) from exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    async def save(self, revision: str, updates: dict[str, str]) -> dict[str, Any]:
        async with self.lock:
            raw, values = await asyncio.to_thread(self._read)
            if not hmac.compare_digest(revision, self._revision(raw)):
                raise ConflictError(
                    "settings_conflict", ".env changed. Reload settings before saving"
                )
            allowed = {name.upper() for name in FileSettings.model_fields}
            if updates.keys() - allowed:
                raise DomainError("settings_invalid", "Unknown configuration key", 422)
            if any(
                len(value) > 8192 or any(c in value for c in ("\n", "\r", "\x00", "${"))
                for value in updates.values()
            ):
                raise DomainError(
                    "settings_invalid",
                    "Use single-line literal values (up to 8192 characters), "
                    "without ${...} expansion",
                    422,
                )
            changed = {key: value for key, value in updates.items() if values.get(key) != value}
            if changed:
                self._validate(values | changed)
                await asyncio.to_thread(self._write, raw, changed)
                raw, values = await asyncio.to_thread(self._read)
            return self._snapshot(raw, values)
