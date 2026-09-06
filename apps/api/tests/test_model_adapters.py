from __future__ import annotations

import json

import httpx
import pytest

from scholarmind.core.config import Settings
from scholarmind.services.embeddings import OpenAICompatibleEmbedding
from scholarmind.services.ingestion_errors import IngestionError
from scholarmind.services.llm import OpenAICompatibleGateway
from scholarmind.services.paper_summary import OpenAIBriefingAnalyzer


def provider_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "llm-secret",
        "llm_model": "scholar-chat",
        "embedding_base_url": "https://embedding.example/v1",
        "embedding_api_key": "embedding-secret",
        "embedding_model": "scholar-embedding",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_openai_stream_uses_bearer_secret_and_yields_incremental_text() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = (
            'data: {"choices":[{"delta":{"content":"Grounded "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"answer [S1]."}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    settings = provider_settings()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OpenAICompatibleGateway(client, settings)
        tokens = [token async for token in gateway.stream("Question?", "[S1] Evidence", [])]

    assert "".join(tokens) == "Grounded answer [S1]."
    request = requests[0]
    assert request.url == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer llm-secret"
    assert "llm-secret" not in str(request.url)
    payload = json.loads(request.content)
    assert payload["model"] == "scholar-chat"
    assert payload["stream"] is True
    assert payload["messages"][0]["role"] == "system"
    assert "[S1] Evidence" in payload["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_briefing_analyzer_uses_summary_model_and_falls_back() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        briefing = {
            "tldr": "T",
            "background": "B",
            "contributions": [],
            "methodology": "M",
            "key_findings": [],
            "limitations": [],
            "key_terms": [],
        }
        delta = json.dumps({"choices": [{"delta": {"content": json.dumps(briefing)}}]})
        body = f"data: {delta}\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        override = OpenAIBriefingAnalyzer(
            client, provider_settings(summary_llm_model="flash-model")
        )
        await override.summarize("Title", None, "Context", "en")
        fallback = OpenAIBriefingAnalyzer(client, provider_settings())
        await fallback.summarize("Title", None, "Context", "en")

    assert payloads[0]["model"] == "flash-model"
    assert payloads[1]["model"] == "scholar-chat"


@pytest.mark.asyncio
async def test_openai_stream_rejects_empty_provider_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{}}]}\n\ndata: [DONE]\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = OpenAICompatibleGateway(client, provider_settings())
        with pytest.raises(RuntimeError, match="no answer content"):
            _ = [token async for token in gateway.stream("Question?", "Evidence", [])]


@pytest.mark.asyncio
async def test_openai_embeddings_use_v1_endpoint_and_restore_index_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        if len(payload["input"]) == 2:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                        {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0, 0.0, 1.0]}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embeddings = OpenAICompatibleEmbedding(client, provider_settings())
        documents = await embeddings.embed_documents(["first", "second"])
        query = await embeddings.embed_query("query")

    assert documents == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert query == [0.0, 0.0, 1.0]
    assert embeddings.dimension == 3
    assert requests[0].url == "https://embedding.example/v1/embeddings"
    assert requests[0].headers["authorization"] == "Bearer embedding-secret"
    assert json.loads(requests[0].content) == {
        "model": "scholar-embedding",
        "input": ["first", "second"],
    }


@pytest.mark.asyncio
async def test_openai_embedding_rejects_missing_response_indexes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embeddings = OpenAICompatibleEmbedding(client, provider_settings())
        with pytest.raises(IngestionError, match="invalid response") as caught:
            await embeddings.embed_documents(["document"])
    assert caught.value.code == "invalid_embedding_response"


@pytest.mark.asyncio
async def test_openai_embedding_marks_rate_limits_as_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embeddings = OpenAICompatibleEmbedding(client, provider_settings())
        with pytest.raises(IngestionError) as caught:
            await embeddings.embed_documents(["document"])
    assert caught.value.code == "embedding_temporarily_unavailable"
    assert caught.value.retryable is True
