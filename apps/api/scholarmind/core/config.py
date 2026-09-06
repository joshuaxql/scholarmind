from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "ScholarMind"
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    web_origin: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]

    auth_required: bool = False
    api_bearer_token: SecretStr | None = None
    rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)

    database_url: str = "sqlite+aiosqlite:///./data/scholarmind.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_mode: Literal["arq", "inline"] = "inline"

    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = Path("./data/objects")
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket: str = "scholarmind"
    s3_region: str = "us-east-1"

    retrieval_backend: Literal["database", "qdrant"] = "database"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "scholarmind_chunks"
    embedding_dimension: int = Field(default=384, ge=32, le=4096)
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_model: str | None = None

    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(default=2048, ge=1, le=131_072)
    max_context_characters: int = Field(default=24_000, ge=1_000, le=200_000)

    arxiv_user_agent: str = "ScholarMind/0.1 (mailto:admin@example.com)"
    arxiv_search_min_interval_seconds: float = Field(default=3.0, ge=3.0, le=60.0)
    arxiv_search_max_attempts: int = Field(default=3, ge=1, le=5)
    arxiv_search_attempt_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    arxiv_search_total_timeout_seconds: float = Field(default=65.0, gt=0, le=100)
    research_cache_ttl_seconds: int = Field(default=21_600, ge=0, le=604_800)
    research_max_context_characters: int = Field(default=50_000, ge=5_000, le=200_000)
    summary_max_context_characters: int = Field(default=24_000, ge=2_000, le=200_000)
    max_pdf_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    max_pdf_pages: int = Field(default=500, ge=1, le=5000)
    ingestion_max_attempts: int = Field(default=3, ge=1, le=10)
    download_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    download_read_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_query_characters: int = Field(default=4000, ge=100, le=50_000)
    paper_retention_days: int = Field(default=90, ge=1, le=3650)
    worker_metrics_port: int = Field(default=9101, ge=0, le=65535)

    auto_create_schema: bool = True

    @field_validator(
        "llm_base_url",
        "llm_api_key",
        "llm_model",
        "embedding_base_url",
        "embedding_api_key",
        "embedding_model",
        mode="before",
    )
    @classmethod
    def normalize_optional_provider_values(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def enforce_production_secrets(self) -> Settings:
        if self.environment == Environment.PRODUCTION:
            if not self.auth_required:
                raise ValueError("AUTH_REQUIRED must be true in production")
            token = self.api_bearer_token.get_secret_value() if self.api_bearer_token else ""
            if len(token) < 32 or token.startswith("replace-"):
                raise ValueError("A unique API_BEARER_TOKEN of at least 32 characters is required")
            unsafe_origins = any(
                origin == "*" or "localhost" in origin or "127.0.0.1" in origin
                for origin in self.cors_origins
            )
            if unsafe_origins:
                raise ValueError("Production CORS_ORIGINS must contain explicit non-local origins")
        self._validate_provider_triplet(
            "LLM",
            self.llm_base_url,
            self.llm_api_key,
            self.llm_model,
        )
        self._validate_provider_triplet(
            "EMBEDDING",
            self.embedding_base_url,
            self.embedding_api_key,
            self.embedding_model,
        )
        return self

    @staticmethod
    def _validate_provider_triplet(
        prefix: str,
        base_url: str | None,
        api_key: SecretStr | None,
        model: str | None,
    ) -> None:
        secret = api_key.get_secret_value().strip() if api_key else ""
        populated = (
            bool(base_url and base_url.strip()),
            bool(secret),
            bool(model and model.strip()),
        )
        # API-key-only environment variables are common in developer shells. Ignore a lone
        # key so ScholarMind can still use its offline provider; a configured URL or model,
        # however, must always be accompanied by the complete triplet.
        if not populated[0] and not populated[2]:
            return
        if not all(populated):
            message = (
                f"{prefix}_BASE_URL, {prefix}_API_KEY and {prefix}_MODEL "
                "must be configured together"
            )
            raise ValueError(message)
        assert base_url is not None
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"{prefix}_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(f"{prefix}_BASE_URL must not contain credentials, query, or fragment")

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_base_url and self.embedding_api_key and self.embedding_model)

    @property
    def is_test(self) -> bool:
        return self.environment == Environment.TEST


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
