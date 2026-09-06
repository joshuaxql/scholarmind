from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx

TokenCallback = Callable[[str], Awaitable[None]]


class ModelStreamError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def stream_completion(
    client: httpx.AsyncClient,
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
) -> AsyncIterator[str]:
    """Read answer deltas only; never expose provider reasoning or error bodies."""
    emitted = False
    finished = False
    characters = 0
    async with client.stream(
        "POST",
        endpoint,
        headers={"Authorization": f"Bearer {api_key}"},
        json={**payload, "stream": True},
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            if data == "[DONE]":
                finished = True
                break
            try:
                chunk = json.loads(data)
            except ValueError as exc:
                raise RuntimeError("The generation provider returned invalid SSE data") from exc
            if not isinstance(chunk, dict) or chunk.get("error"):
                raise RuntimeError("The generation provider returned an error event")
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                continue
            choice = choices[0]
            reason = choice.get("finish_reason")
            if reason is not None:
                if reason == "length":
                    raise ModelStreamError(
                        "model_output_limit",
                        "The model exhausted its output token budget. Increase "
                        "LLM_MAX_OUTPUT_TOKENS in Settings and retry; reasoning models "
                        "may use this budget before producing answer text.",
                    )
                if reason != "stop":
                    raise RuntimeError("The generation provider could not finish the answer")
                finished = True
            delta = choice.get("delta")
            content = delta.get("content") if isinstance(delta, dict) else None
            fragments = (
                [content]
                if isinstance(content, str)
                else (
                    [part.get("text") for part in content if isinstance(part, dict)]
                    if isinstance(content, list)
                    else []
                )
            )
            for fragment in fragments:
                if not isinstance(fragment, str) or not fragment:
                    continue
                characters += len(fragment)
                if characters > 256_000:
                    raise RuntimeError("The generation provider exceeded the answer size limit")
                emitted = True
                yield fragment
    if not emitted:
        raise RuntimeError("The generation provider returned no answer content")
    if not finished:
        raise RuntimeError("The generation provider closed an incomplete answer stream")
