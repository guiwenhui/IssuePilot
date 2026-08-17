import math
from typing import Any, Dict, List, Optional, Sequence

import httpx


QUERY_INSTRUCTION = (
    "Instruct: Given a software issue, retrieve Python code that helps solve it.\n"
    "Query: "
)
DOCUMENT_PREFIX = "Python code document:\n"


class EmbeddingUnavailableError(Exception):
    pass


class EmbeddingInvalidResponseError(Exception):
    pass


class OllamaEmbeddingProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: int,
        batch_size: int,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if dimensions < 1 or batch_size < 1 or timeout_seconds < 1:
            raise ValueError("embedding limits must be positive")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self._timeout = timeout_seconds
        self._batch_size = batch_size
        self._transport = transport

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> List[List[float]]:
        prepared = [DOCUMENT_PREFIX + text for text in texts]
        embeddings: List[List[float]] = []
        for offset in range(0, len(prepared), self._batch_size):
            batch = prepared[offset : offset + self._batch_size]
            embeddings.extend(await self._request(batch))
        return embeddings

    async def embed_query(self, text: str) -> List[float]:
        embeddings = await self._request([QUERY_INSTRUCTION + text])
        return embeddings[0]

    async def _request(self, inputs: Sequence[str]) -> List[List[float]]:
        payload = {
            "model": self.model,
            "input": list(inputs),
            "dimensions": self.dimensions,
            "truncate": False,
        }
        response = await self._post(payload)
        return _validate_response(
            response, self.model, len(inputs), self.dimensions
        )

    async def _post(self, payload: Dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self.base_url}/api/embed", json=payload
                )
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as error:
            raise EmbeddingUnavailableError("Ollama request failed") from error
        except httpx.RequestError as error:
            raise EmbeddingUnavailableError("Ollama unavailable") from error


def _validate_response(
    response: httpx.Response,
    expected_model: str,
    expected_count: int,
    dimensions: int,
) -> List[List[float]]:
    try:
        payload = response.json()
    except ValueError as error:
        raise EmbeddingInvalidResponseError("Ollama returned invalid JSON") from error
    if not isinstance(payload, dict) or payload.get("model") != expected_model:
        raise EmbeddingInvalidResponseError("Ollama model does not match")
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != expected_count:
        raise EmbeddingInvalidResponseError("Ollama embedding count does not match")
    return [_validate_vector(item, dimensions) for item in embeddings]


def _validate_vector(value: Any, dimensions: int) -> List[float]:
    if not isinstance(value, list) or len(value) != dimensions:
        raise EmbeddingInvalidResponseError("Ollama embedding dimensions do not match")
    if any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(item)
        for item in value
    ):
        raise EmbeddingInvalidResponseError("Ollama embedding values are invalid")
    return [float(item) for item in value]
