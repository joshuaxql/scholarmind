from __future__ import annotations

import asyncio
import json
import runpy
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values
from fastapi import FastAPI

from scholarmind.core.config import Settings
from scholarmind.domain.errors import DomainError
from scholarmind.services.environment import SECRET_KEYS, EnvironmentService, FileSettings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def env_service(tmp_path: Path) -> EnvironmentService:
    path = tmp_path / ".env"
    path.write_bytes(
        b"# Keep this comment\nLLM_BASE_URL=https://model.example/v1\n"
        b"LLM_API_KEY='existing-secret' # private\nLLM_MODEL=model-a\n"
        b"LOG_LEVEL=INFO # logging\nDATABASE_URL=postgresql+asyncpg://user:password@db/app\n"
        b"CUSTOM_VARIABLE=preserve-me\n"
    )
    return EnvironmentService(path)


async def test_catalog_covers_all_template_and_backend_fields_without_secret_values(
    env_service: EnvironmentService,
) -> None:
    await env_service.initialize()
    result = await env_service.read()
    fields = {field["key"]: field for field in result["fields"]}
    template = dotenv_values(ROOT / ".env.example")
    assert set(template) <= fields.keys()
    assert {name.upper() for name in Settings.model_fields} <= fields.keys()
    assert len(fields) == len(FileSettings.model_fields)
    for key in SECRET_KEYS | {"DATABASE_URL"}:
        assert fields[key]["value"] is None
        assert fields[key]["sensitive"]
    assert fields["LLM_API_KEY"]["configured"]
    assert not fields["EMBEDDING_API_KEY"]["configured"]
    assert not result["restart_required"]
    assert "existing-secret" not in json.dumps(result)
    assert "password" not in json.dumps(result)


async def test_save_preserves_secrets_comments_unknown_keys_and_literal_round_trip(
    env_service: EnvironmentService,
) -> None:
    await env_service.initialize()
    initial = await env_service.read()
    literal = r"D:\papers\O'Reilly # local"
    updated = await env_service.save(
        initial["revision"],
        {
            "LOG_LEVEL": "DEBUG",
            "LOCAL_STORAGE_PATH": literal,
        },
    )
    content = env_service.path.read_text(encoding="utf-8")
    assert "# Keep this comment" in content
    assert "LOG_LEVEL='DEBUG' # logging" in content
    assert "LLM_API_KEY='existing-secret' # private" in content
    assert "CUSTOM_VARIABLE=preserve-me" in content
    assert updated["restart_required"]
    parsed = dotenv_values(env_service.path, interpolate=False)
    assert parsed["LOCAL_STORAGE_PATH"] == literal
    launcher = runpy.run_path(str(ROOT / "scripts/start.py"))
    assert launcher["load_env"](env_service.path)["LOCAL_STORAGE_PATH"] == literal
    assert launcher["load_env"](env_service.path)["LOG_LEVEL"] == "DEBUG"
    restarted = EnvironmentService(env_service.path)
    await restarted.initialize()
    assert not (await restarted.read())["restart_required"]


async def test_replace_and_clear_secret_never_echo_value(env_service: EnvironmentService) -> None:
    before = await env_service.read()
    saved = await env_service.save(before["revision"], {"LLM_API_KEY": "new-secret'\\#value"})
    assert "new-secret" not in json.dumps(saved)
    assert dotenv_values(env_service.path)["LLM_API_KEY"] == "new-secret'\\#value"
    saved = await env_service.save(
        saved["revision"],
        {
            "LLM_BASE_URL": "",
            "LLM_API_KEY": "",
            "LLM_MODEL": "",
        },
    )
    key = next(field for field in saved["fields"] if field["key"] == "LLM_API_KEY")
    assert not key["configured"] and key["value"] is None


@pytest.mark.parametrize(
    "updates",
    [
        {"API_PORT": "70000"},
        {"WEB_PORT": "0"},
        {"LLM_API_KEY": ""},
        {"LLM_API_KEY": "secret", "LLM_BASE_URL": "bad-url"},
        {"CORS_ORIGINS": "bad-json"},
        {"CORS_ORIGINS": "{}"},
        {"ENVIRONMENT": "production"},
        {"AUTH_REQUIRED": "true", "API_BEARER_TOKEN": ""},
        {"AUTH_REQUIRED": "true", "API_BEARER_TOKEN": "new", "API_INTERNAL_BEARER_TOKEN": "old"},
        {"ARXIV_SEARCH_MIN_INTERVAL_SECONDS": "2"},
        {"LLM_TEMPERATURE": "nan"},
        {"ARXIV_SEARCH_ATTEMPT_TIMEOUT_SECONDS": "0"},
        {"PYTHONPATH": "arbitrary"},
        {"LLM_MODEL": "model\nINJECTED=1"},
        {"LLM_API_KEY": "${OTHER_KEY}"},
        {"API_INTERNAL_URL": "http://user:secret@example.com"},
        {"WEB_HOST": "bad/host"},
        {"DATABASE_URL": "bad"},
        {"LLM_MODEL": "a" * 8193},
    ],
)
async def test_invalid_configuration_does_not_write(
    env_service: EnvironmentService,
    updates: dict[str, str],
) -> None:
    before = env_service.path.read_bytes()
    snapshot = await env_service.read()
    with pytest.raises(DomainError) as failure:
        await env_service.save(snapshot["revision"], updates)
    assert failure.value.status_code == 422
    assert "existing-secret" not in failure.value.message
    assert env_service.path.read_bytes() == before


async def test_external_edit_and_concurrent_saves_cannot_overwrite_newer_version(
    env_service: EnvironmentService,
) -> None:
    snapshot = await env_service.read()
    outcomes = await asyncio.gather(
        env_service.save(snapshot["revision"], {"LOG_LEVEL": "DEBUG"}),
        env_service.save(snapshot["revision"], {"LOG_LEVEL": "WARNING"}),
        return_exceptions=True,
    )
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert any(
        isinstance(outcome, DomainError) and outcome.status_code == 409 for outcome in outcomes
    )
    snapshot = await env_service.read()
    env_service.path.write_bytes(env_service.path.read_bytes() + b"# External edit\n")
    with pytest.raises(DomainError, match="changed"):
        await env_service.save(snapshot["revision"], {"LOG_LEVEL": "INFO"})
    assert "# External edit" in env_service.path.read_text()


async def test_failed_atomic_replace_keeps_original_and_cleans_temporary_file(
    env_service: EnvironmentService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = await env_service.read()
    original = env_service.path.read_bytes()

    def fail_replace(source: str, target: Path) -> None:
        raise PermissionError("File locked")

    monkeypatch.setattr("scholarmind.services.environment.os.replace", fail_replace)
    with pytest.raises(DomainError, match="Cannot save"):
        await env_service.save(snapshot["revision"], {"LOG_LEVEL": "DEBUG"})
    assert env_service.path.read_bytes() == original
    assert list(env_service.path.parent.glob(".env.*")) == []


async def test_missing_file_can_be_created_and_noop_leaves_it_untouched(tmp_path: Path) -> None:
    service = EnvironmentService(tmp_path / ".env")
    snapshot = await service.read()
    await service.save(snapshot["revision"], {})
    assert not service.path.exists()
    saved = await service.save(snapshot["revision"], {"WEB_PORT": "3100"})
    assert service.path.exists()
    assert next(field["value"] for field in saved["fields"] if field["key"] == "WEB_PORT") == "3100"


async def test_file_validation_ignores_process_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_PORT", "9999")
    monkeypatch.setenv("LLM_BASE_URL", "https://irrelevant.example")
    service = EnvironmentService(tmp_path / ".env")
    snapshot = await service.read()
    assert next(f["value"] for f in snapshot["fields"] if f["key"] == "API_PORT") == "8000"
    await service.save(snapshot["revision"], {"API_PORT": "3001"})


async def test_local_settings_routes_require_local_host_header_and_existing_auth(
    client: httpx.AsyncClient,
    app: FastAPI,
    env_service: EnvironmentService,
) -> None:
    app.state.environment_service = env_service
    url = "http://127.0.0.1/api/v1/settings"
    headers = {"x-scholarmind-settings": "1"}
    assert (await client.get(url)).status_code == 403
    assert (
        await client.get("http://untrusted.example/api/v1/settings", headers=headers)
    ).status_code == 403
    assert (
        await client.get(url, headers=headers | {"sec-fetch-site": "cross-site"})
    ).status_code == 403
    read = await client.get(url, headers=headers)
    assert read.status_code == 200 and read.headers["cache-control"] == "no-store"
    saved = await client.post(
        url,
        headers=headers,
        json={
            "revision": read.json()["revision"],
            "updates": {"LOG_LEVEL": "ERROR"},
        },
    )
    assert saved.status_code == 200 and "existing-secret" not in saved.text
    app.state.settings.auth_required = True
    assert (await client.get(url, headers=headers)).status_code == 401


async def test_public_bind_and_remote_client_cannot_edit(
    app: FastAPI,
    env_service: EnvironmentService,
) -> None:
    app.state.environment_service = env_service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("192.0.2.1", 1234)),
        base_url="http://localhost",
    ) as remote:
        assert (
            await remote.get("/api/v1/settings", headers={"x-scholarmind-settings": "1"})
        ).status_code == 403
    app.state.settings.api_host = "0.0.0.0"  # noqa: S104 - testing rejection
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as local:
        assert (
            await local.get("/api/v1/settings", headers={"x-scholarmind-settings": "1"})
        ).status_code == 403
