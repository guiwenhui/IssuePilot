from typing import Any, Dict, Optional, Sequence, Type
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.llms.base import ChatMessage, ResponseModel


class LlmUnavailableError(Exception):
    pass


class LlmInvalidResponseError(Exception):
    pass


class OllamaChatProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int,
        context_window: int,
        max_output_tokens: int,
        max_response_bytes: int,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = _loopback_base_url(base_url)
        if min(
            timeout_seconds,
            context_window,
            max_output_tokens,
            max_response_bytes,
        ) < 1:
            raise ValueError("LLM limits must be positive")
        if not model.strip():
            raise ValueError("LLM model must not be empty")
        self.model = model
        self._timeout = timeout_seconds
        self._context_window = context_window
        self._max_output_tokens = max_output_tokens
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        response_model: Type[ResponseModel],
    ) -> ResponseModel:
        payload = self._payload(messages, response_model)
        response = await self._post(payload)
        return self._validate_response(response, response_model)

    def _payload(
        self,
        messages: Sequence[ChatMessage],
        response_model: Type[ResponseModel],
    ) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "think": False,
            "format": _ollama_compatible_schema(
                response_model.model_json_schema()
            ),
            "options": {
                "temperature": 0,
                "seed": 0,
                "num_ctx": self._context_window,
                "num_predict": self._max_output_tokens,
            },
        }

    async def _post(self, payload: Dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
                return response
        except (httpx.HTTPStatusError, httpx.RequestError) as error:
            raise LlmUnavailableError("local Ollama chat unavailable") from error

    def _validate_response(
        self,
        response: httpx.Response,
        response_model: Type[ResponseModel],
    ) -> ResponseModel:
        if len(response.content) > self._max_response_bytes:
            raise LlmInvalidResponseError("Ollama response is too large")
        try:
            payload = response.json()
        except ValueError as error:
            raise LlmInvalidResponseError("Ollama returned invalid JSON") from error
        content = _message_content(payload, self.model)
        try:
            return response_model.model_validate_json(content)
        except (ValidationError, ValueError) as error:
            raise LlmInvalidResponseError(
                "Ollama structured output is invalid"
            ) from error


def _loopback_base_url(value: str) -> str:
    parsed = urlsplit(value)
    valid_host = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    valid_path = parsed.path in {"", "/"}
    if (
        parsed.scheme != "http"
        or not valid_host
        or parsed.username is not None
        or parsed.password is not None
        or not valid_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("LLM base URL must be an unambiguous loopback HTTP URL")
    return value.rstrip("/")


def _message_content(payload: Any, expected_model: str) -> str:
    if not isinstance(payload, dict) or payload.get("model") != expected_model:
        raise LlmInvalidResponseError("Ollama model does not match")
    message = payload.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise LlmInvalidResponseError("Ollama message content is invalid")
    return message["content"]


def _ollama_compatible_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _ollama_compatible_schema(item)
            for key, item in value.items()
            if key not in {"minLength", "maxLength"}
        }
    if isinstance(value, list):
        return [_ollama_compatible_schema(item) for item in value]
    return value
