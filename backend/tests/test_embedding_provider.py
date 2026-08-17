import json
from typing import List

import httpx
import pytest

from app.embeddings.ollama import (
    EmbeddingInvalidResponseError,
    EmbeddingUnavailableError,
    OllamaEmbeddingProvider,
)


def vector(value: float = 0.1) -> List[float]:
    return [value] * 1024


@pytest.mark.asyncio
async def test_ollama_batches_documents_with_fixed_contract() -> None:
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "model": "qwen3-embedding:0.6b",
                "embeddings": [vector(index + 0.1) for index, _ in enumerate(payload["input"])],
            },
        )

    provider = OllamaEmbeddingProvider(
        "http://ollama.test",
        "qwen3-embedding:0.6b",
        1024,
        timeout_seconds=5,
        batch_size=2,
        transport=httpx.MockTransport(respond),
    )

    embeddings = await provider.embed_documents(["first", "second", "third"])

    assert len(embeddings) == 3
    assert [len(item["input"]) for item in requests] == [2, 1]
    assert all(item["model"] == "qwen3-embedding:0.6b" for item in requests)
    assert all(item["dimensions"] == 1024 for item in requests)
    assert all(item["truncate"] is False for item in requests)
    assert requests[0]["input"][0].startswith("Python code document:\n")


@pytest.mark.asyncio
async def test_ollama_query_uses_retrieval_instruction() -> None:
    captured = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"model": "qwen3-embedding:0.6b", "embeddings": [vector()]},
        )

    provider = OllamaEmbeddingProvider(
        "http://ollama.test/",
        "qwen3-embedding:0.6b",
        1024,
        5,
        32,
        httpx.MockTransport(respond),
    )

    await provider.embed_query("Fix escaping in HTML output")

    assert captured["input"][0].startswith("Instruct:")
    assert captured["input"][0].endswith("Query: Fix escaping in HTML output")


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 500])
async def test_ollama_http_errors_are_stable(status_code: int) -> None:
    provider = OllamaEmbeddingProvider(
        "http://ollama.test",
        "qwen3-embedding:0.6b",
        1024,
        5,
        32,
        httpx.MockTransport(
            lambda request: httpx.Response(status_code, text="unsafe response")
        ),
    )

    with pytest.raises(EmbeddingUnavailableError, match="Ollama request failed"):
        await provider.embed_query("issue")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "embeddings",
    [[], [[0.1]], [[float("nan")] * 1024], [[True] * 1024]],
)
async def test_ollama_rejects_invalid_embedding_payloads(embeddings: object) -> None:
    provider = OllamaEmbeddingProvider(
        "http://ollama.test",
        "qwen3-embedding:0.6b",
        1024,
        5,
        32,
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=json.dumps(
                    {
                        "model": "qwen3-embedding:0.6b",
                        "embeddings": embeddings,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        ),
    )

    with pytest.raises(EmbeddingInvalidResponseError):
        await provider.embed_query("issue")


@pytest.mark.asyncio
async def test_ollama_transport_error_is_stable() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    provider = OllamaEmbeddingProvider(
        "http://ollama.test",
        "qwen3-embedding:0.6b",
        1024,
        5,
        32,
        httpx.MockTransport(fail),
    )

    with pytest.raises(EmbeddingUnavailableError, match="Ollama unavailable"):
        await provider.embed_query("issue")
