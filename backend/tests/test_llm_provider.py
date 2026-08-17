import json

import httpx
import pytest

from app.llms.ollama import (
    LlmInvalidResponseError,
    LlmUnavailableError,
    OllamaChatProvider,
)
from app.schemas.planning import RequirementAnalysisDraft


def valid_analysis() -> dict:
    return {
        "summary": "Treat None as empty.",
        "acceptance_criteria": [
            {
                "id": "AC1",
                "description": "None returns an empty value.",
                "evidence_ranks": [1],
            }
        ],
        "constraints": [],
        "assumptions": [],
        "affected_areas": [
            {
                "path": "src/module.py",
                "symbol": "escape_silent",
                "reason": "Behavior is implemented here.",
                "evidence_ranks": [1],
            }
        ],
        "risks": [],
    }


@pytest.mark.asyncio
async def test_ollama_chat_uses_local_structured_non_thinking_contract() -> None:
    captured = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen3:8b",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(valid_analysis()),
                    "thinking": "must not be persisted",
                },
            },
        )

    provider = OllamaChatProvider(
        "http://127.0.0.1:11434/",
        "qwen3:8b",
        timeout_seconds=180,
        context_window=16_384,
        max_output_tokens=2_048,
        max_response_bytes=65_536,
        transport=httpx.MockTransport(respond),
    )

    result = await provider.generate(
        [{"role": "system", "content": "Return analysis."}],
        RequirementAnalysisDraft,
    )

    assert result.summary == "Treat None as empty."
    assert captured["stream"] is False
    assert captured["think"] is False
    assert captured["format"]["additionalProperties"] is False
    serialized_schema = json.dumps(captured["format"])
    assert "minLength" not in serialized_schema
    assert "maxLength" not in serialized_schema
    assert captured["options"] == {
        "temperature": 0,
        "seed": 0,
        "num_ctx": 16_384,
        "num_predict": 2_048,
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.example.com",
        "http://10.0.0.1:11434",
        "http://user:pass@127.0.0.1:11434",
        "http://127.0.0.1:11434/path",
        "http://127.0.0.1:11434?query=yes",
    ],
)
def test_ollama_chat_rejects_non_loopback_or_ambiguous_urls(base_url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaChatProvider(base_url, "qwen3:8b", 5, 4096, 100, 1000)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 404, 500])
async def test_ollama_chat_maps_http_errors_to_unavailable(status_code: int) -> None:
    provider = OllamaChatProvider(
        "http://localhost:11434",
        "qwen3:8b",
        5,
        4096,
        100,
        1000,
        httpx.MockTransport(
            lambda request: httpx.Response(status_code, text="unsafe raw error")
        ),
    )

    with pytest.raises(LlmUnavailableError):
        await provider.generate([], RequirementAnalysisDraft)


@pytest.mark.asyncio
async def test_ollama_chat_maps_transport_timeout_to_unavailable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = OllamaChatProvider(
        "http://localhost:11434",
        "qwen3:8b",
        5,
        4096,
        100,
        1000,
        httpx.MockTransport(timeout),
    )

    with pytest.raises(LlmUnavailableError):
        await provider.generate([], RequirementAnalysisDraft)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"model": "wrong", "message": {"content": "{}"}},
        {"model": "qwen3:8b", "message": {"content": "not-json"}},
        {"model": "qwen3:8b", "message": {"content": "{}"}},
    ],
)
async def test_ollama_chat_rejects_invalid_response_shapes(payload: dict) -> None:
    provider = OllamaChatProvider(
        "http://localhost:11434",
        "qwen3:8b",
        5,
        4096,
        100,
        1000,
        httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )

    with pytest.raises(LlmInvalidResponseError):
        await provider.generate([], RequirementAnalysisDraft)


@pytest.mark.asyncio
async def test_ollama_chat_rejects_oversized_response() -> None:
    provider = OllamaChatProvider(
        "http://localhost:11434",
        "qwen3:8b",
        5,
        4096,
        100,
        20,
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "qwen3:8b",
                    "message": {"content": json.dumps(valid_analysis())},
                },
            )
        ),
    )

    with pytest.raises(LlmInvalidResponseError, match="too large"):
        await provider.generate([], RequirementAnalysisDraft)


@pytest.mark.asyncio
async def test_pydantic_still_enforces_bounds_removed_from_ollama_grammar() -> None:
    invalid = valid_analysis()
    invalid["summary"] = "x" * 2_001
    provider = OllamaChatProvider(
        "http://localhost:11434",
        "qwen3:8b",
        5,
        4096,
        100,
        10_000,
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "qwen3:8b",
                    "message": {"content": json.dumps(invalid)},
                },
            )
        ),
    )

    with pytest.raises(LlmInvalidResponseError):
        await provider.generate([], RequirementAnalysisDraft)
