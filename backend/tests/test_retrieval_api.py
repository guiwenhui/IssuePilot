from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_retrieval_service
from app.main import create_app
from app.schemas.retrieval import (
    RetrievalCounts,
    RetrievalEmbedding,
    RetrievalResponse,
    RetrievalResultItem,
    RetrievalVersions,
)
from app.services.repository_service import WorkspaceInconsistentError
from app.services.retrieval_service import RetrievalNotReadyError
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError


class StubRetrievalService:
    def __init__(self, task_id: UUID) -> None:
        self.error: Optional[Exception] = None
        self.response = RetrievalResponse(
            task_id=task_id,
            commit_sha="a" * 40,
            query="Fix escape html output",
            embedding=RetrievalEmbedding(
                provider="ollama",
                model="qwen3-embedding:0.6b",
                dimensions=1024,
            ),
            versions=RetrievalVersions(
                chunker="python-symbol-v1",
                fusion="rrf-v1",
                reranker="rules-v1",
            ),
            created_at=datetime.now(timezone.utc),
            counts=RetrievalCounts(
                chunks=2,
                keyword_candidates=2,
                symbol_candidates=1,
                vector_candidates=2,
                results=1,
            ),
            results=[
                RetrievalResultItem(
                    rank=1,
                    path="src/escape.py",
                    symbol="escape",
                    kind="function",
                    start_line=1,
                    end_line=4,
                    snippet="def escape(value): ...",
                    matched_channels=["keyword", "symbol", "vector"],
                    channel_ranks={"keyword": 1, "symbol": 1, "vector": 2},
                    rrf_score=0.04,
                    rerank_score=0.07,
                )
            ],
        )

    async def get_retrieval(self, task_id: UUID) -> RetrievalResponse:
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
async def retrieval_client() -> AsyncIterator[
    tuple[AsyncClient, StubRetrievalService, UUID]
]:
    task_id = uuid4()
    service = StubRetrievalService(task_id)
    app = create_app()
    app.dependency_overrides[get_retrieval_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, service, task_id


@pytest.mark.asyncio
async def test_retrieval_returns_ranked_evidence_and_disables_cache(
    retrieval_client: tuple[AsyncClient, StubRetrievalService, UUID],
) -> None:
    client, _, task_id = retrieval_client

    response = await client.get(f"/api/v1/tasks/{task_id}/retrieval")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["results"][0]["matched_channels"] == [
        "keyword",
        "symbol",
        "vector",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "expected_code"),
    [
        (RetrievalNotReadyError(), 409, "RETRIEVAL_NOT_READY"),
        (WorkspaceInconsistentError(), 409, "WORKSPACE_INCONSISTENT"),
        (TaskNotFoundError(), 404, "TASK_NOT_FOUND"),
        (DatabaseUnavailableError(), 503, "DATABASE_UNAVAILABLE"),
    ],
)
async def test_retrieval_returns_structured_errors(
    retrieval_client: tuple[AsyncClient, StubRetrievalService, UUID],
    error: Exception,
    status_code: int,
    expected_code: str,
) -> None:
    client, service, task_id = retrieval_client
    service.error = error

    response = await client.get(f"/api/v1/tasks/{task_id}/retrieval")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == expected_code


@pytest.mark.asyncio
async def test_retrieval_rejects_invalid_uuid(
    retrieval_client: tuple[AsyncClient, StubRetrievalService, UUID],
) -> None:
    client, _, _ = retrieval_client

    response = await client.get("/api/v1/tasks/not-a-uuid/retrieval")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
