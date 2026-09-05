from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scholarmind.core.config import Environment, Settings


def test_example_env_boots_in_all_local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    names = [
        "DATABASE_URL",
        "QUEUE_MODE",
        "STORAGE_BACKEND",
        "RETRIEVAL_BACKEND",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_MODEL",
    ]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    example = Path(__file__).resolve().parents[3] / ".env.example"
    settings = Settings(_env_file=example)  # type: ignore[call-arg]
    assert settings.database_url.startswith("sqlite+")
    assert settings.queue_mode == "inline"
    assert settings.storage_backend == "local"
    assert settings.retrieval_backend == "database"
    assert settings.llm_configured is False
    assert settings.embedding_configured is False


def test_production_refuses_weak_authentication() -> None:
    with pytest.raises(ValidationError, match="AUTH_REQUIRED"):
        Settings(environment=Environment.PRODUCTION, auth_required=False)
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(
            environment=Environment.PRODUCTION,
            auth_required=True,
            api_bearer_token="short",
            cors_origins=["https://scholarmind.example"],
        )


def test_production_refuses_local_cors_origins() -> None:
    with pytest.raises(ValidationError, match="non-local"):
        Settings(
            environment=Environment.PRODUCTION,
            auth_required=True,
            api_bearer_token="a-unique-production-token-that-is-long-enough",
            cors_origins=["http://localhost:3000"],
        )


def test_lone_shell_api_keys_do_not_disable_offline_mode() -> None:
    settings = Settings(llm_api_key="shell-secret", embedding_api_key="shell-secret")
    assert settings.llm_configured is False
    assert settings.embedding_configured is False


def test_openai_provider_configuration_requires_complete_triplets() -> None:
    with pytest.raises(ValidationError, match=r"LLM_BASE_URL.*LLM_API_KEY.*LLM_MODEL"):
        Settings(llm_base_url="https://provider.example/v1")
    with pytest.raises(ValidationError, match="EMBEDDING_BASE_URL"):
        Settings(
            embedding_base_url="https://provider.example/v1",
            embedding_api_key="secret",
        )


def test_openai_provider_configuration_rejects_unsafe_base_urls() -> None:
    with pytest.raises(ValidationError, match="absolute HTTP"):
        Settings(
            llm_base_url="file:///tmp/model",
            llm_api_key="secret",
            llm_model="model",
        )
    with pytest.raises(ValidationError, match="must not contain credentials"):
        Settings(
            embedding_base_url="https://user:password@provider.example/v1?secret=yes",
            embedding_api_key="secret",
            embedding_model="model",
        )


def test_complete_openai_provider_configuration_is_detected() -> None:
    settings = Settings(
        llm_base_url="https://llm.example/v1",
        llm_api_key="secret",
        llm_model="chat-model",
        embedding_base_url="http://127.0.0.1:11434/v1",
        embedding_api_key="local-secret",
        embedding_model="embedding-model",
    )
    assert settings.llm_configured is True
    assert settings.embedding_configured is True
