from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol, cast

import httpx

from scholarmind.core.config import Settings
from scholarmind.services.ingestion_errors import IngestionError

_TOKEN = re.compile(r"\w+", re.UNICODE)


class EmbeddingProvider(Protocol):
    @property
    def dimension(self) -> int | None: ...

    @property
    def identifier(self) -> str: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LocalHashEmbedding:
    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def identifier(self) -> str:
        return f"local-hash-v1:{self._dimension}"

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


class OpenAICompatibleEmbedding:
    """Embedding adapter for OpenAI-compatible ``POST /embeddings`` APIs."""

    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        if not settings.embedding_configured:
            raise ValueError("OpenAI-compatible embedding settings are incomplete")
        assert settings.embedding_base_url is not None
        assert settings.embedding_api_key is not None
        assert settings.embedding_model is not None
        self.client = client
        self.endpoint = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
        self.model = settings.embedding_model
        endpoint_hash = hashlib.sha256(self.endpoint.encode()).hexdigest()[:12]
        self._identifier = f"openai-compatible:{endpoint_hash}:{self.model}"[:500]
        self.api_key = settings.embedding_api_key.get_secret_value()
        self._dimension: int | None = None

    @property
    def dimension(self) -> int | None:
        return self._dimension

    @property
    def identifier(self) -> str:
        return self._identifier

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), 100):
            embeddings.extend(await self._request(texts[start : start + 100]))
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        return (await self._request([text]))[0]

    async def _request(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise IngestionError(
                "embedding_temporarily_unavailable",
                "The embedding service is temporarily unavailable",
                retryable=True,
            )
        if response.status_code in {401, 403}:
            raise IngestionError(
                "embedding_authentication_failed",
                "The embedding service rejected its configured credentials",
            )
        if response.is_error:
            raise IngestionError(
                "embedding_request_rejected",
                "The embedding service rejected the request",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise self._invalid_response() from exc
        return self._decode_response(payload, len(texts))

    def _decode_response(self, payload: Any, expected_count: int) -> list[list[float]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise self._invalid_response()
        raw_items = cast(list[Any], payload["data"])
        if len(raw_items) != expected_count:
            raise self._invalid_response()
        if not all(
            isinstance(item, dict) and isinstance(item.get("index"), int) for item in raw_items
        ):
            raise self._invalid_response()
        indices = [cast(dict[str, Any], item)["index"] for item in raw_items]
        if sorted(indices) != list(range(expected_count)):
            raise self._invalid_response()
        raw_items = sorted(raw_items, key=lambda item: cast(dict[str, Any], item)["index"])
        embeddings: list[list[float]] = []
        try:
            for item in raw_items:
                if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                    raise TypeError
                vector = [float(value) for value in item["embedding"]]
                if not vector or not all(math.isfinite(value) for value in vector):
                    raise ValueError
                embeddings.append(vector)
        except (TypeError, ValueError, OverflowError) as exc:
            raise self._invalid_response() from exc

        dimensions = {len(vector) for vector in embeddings}
        if len(dimensions) != 1:
            raise self._invalid_response()
        dimension = dimensions.pop()
        if self._dimension is not None and dimension != self._dimension:
            raise self._invalid_response()
        self._dimension = dimension
        return embeddings

    @staticmethod
    def _invalid_response() -> IngestionError:
        return IngestionError(
            "invalid_embedding_response",
            "The embedding service returned an invalid response",
        )


def build_embedding_provider(
    settings: Settings,
    client: httpx.AsyncClient,
) -> EmbeddingProvider:
    if settings.embedding_configured:
        return OpenAICompatibleEmbedding(client, settings)
    return LocalHashEmbedding(settings.embedding_dimension)


def lexical_terms(text: str) -> list[str]:
    return _tokens(text)


def _tokens(text: str) -> list[str]:
    base = [token.casefold() for token in _TOKEN.findall(text) if len(token) > 1]
    expanded: list[str] = []
    for token in base:
        expanded.append(token)
        if len(token) >= 6:
            expanded.extend(token[index : index + 3] for index in range(len(token) - 2))
        if any("\u4e00" <= character <= "\u9fff" for character in token):
            expanded.extend(token[index : index + 2] for index in range(len(token) - 1))
    return expanded
