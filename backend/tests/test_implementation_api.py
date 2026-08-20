from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_implementation_queue,
    get_implementation_service,
)
from app.main import create_app
from app.schemas.implementation import (
    ImplementationCreate,
    ImplementationResponse,
    ImplementationRunResponse,
    TestRunCreate as RunRequest,
)
from app.services.implementation_service import ImplementationDisabledError
from app.services.implementation_store import (
    ImplementationConflictError,
    ImplementationNotReadyError,
)


class StubImplementationService:
    def __init__(self, task_id: UUID) -> None:
        self.error: Optional[Exception] = None
        self.submitted: object | None = None
        self.response = ImplementationResponse(
            run=ImplementationRunResponse(
                implementation_run_id=uuid4(),
                task_id=task_id,
                plan_id=uuid4(),
                plan_version=1,
                base_commit="a" * 40,
                status="pending",
                provider="ollama",
                model="qwen3:8b",
                failure_code=None,
                failure_message=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )

    async def submit_implementation(
        self, task_id: UUID, payload: ImplementationCreate
    ) -> ImplementationResponse:
        if self.error:
            raise self.error
        self.submitted = payload
        return self.response

    async def submit_test(
        self, task_id: UUID, payload: RunRequest
    ) -> ImplementationResponse:
        if self.error:
            raise self.error
        self.submitted = payload
        return self.response

    async def get_implementation(self, task_id: UUID) -> ImplementationResponse:
        if self.error:
            raise self.error
        return self.response


class StubQueue:
    def __init__(self) -> None:
        self.implementations = []
        self.tests = []

    def enqueue_implementation(self, item_id: UUID) -> bool:
        self.implementations.append(item_id)
        return True

    def enqueue_test(self, item_id: UUID) -> bool:
        self.tests.append(item_id)
        return True


@pytest.fixture
async def implementation_client() -> AsyncIterator[tuple[AsyncClient, StubImplementationService, StubQueue, UUID]]:
    task_id = uuid4()
    service = StubImplementationService(task_id)
    queue = StubQueue()
    app = create_app()
    app.dependency_overrides[get_implementation_service] = lambda: service
    app.dependency_overrides[get_implementation_queue] = lambda: queue
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, service, queue, task_id


@pytest.mark.asyncio
async def test_create_implementation_is_versioned_idempotent_and_queued(
    implementation_client,
) -> None:
    client, service, queue, task_id = implementation_client
    key = uuid4()

    response = await client.post(
        f"/api/v1/tasks/{task_id}/implementation",
        json={"expected_plan_version": 1, "idempotency_key": str(key)},
    )

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    assert service.submitted.idempotency_key == key
    assert queue.implementations == [service.response.run.implementation_run_id]


@pytest.mark.asyncio
async def test_get_implementation_disables_cache(implementation_client) -> None:
    client, _, _, task_id = implementation_client

    response = await client.get(f"/api/v1/tasks/{task_id}/implementation")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ImplementationNotReadyError(), "IMPLEMENTATION_NOT_READY"),
        (ImplementationDisabledError(), "IMPLEMENTATION_DISABLED"),
        (
            ImplementationConflictError("PLAN_VERSION_CONFLICT", "changed"),
            "PLAN_VERSION_CONFLICT",
        ),
    ],
)
async def test_implementation_maps_conflicts(
    implementation_client, error: Exception, code: str
) -> None:
    client, service, _, task_id = implementation_client
    service.error = error

    response = await client.post(
        f"/api/v1/tasks/{task_id}/implementation",
        json={
            "expected_plan_version": 1,
            "idempotency_key": str(uuid4()),
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code


@pytest.mark.asyncio
async def test_test_request_rejects_invalid_patch_hash(
    implementation_client,
) -> None:
    client, _, _, task_id = implementation_client

    response = await client.post(
        f"/api/v1/tasks/{task_id}/implementation/tests",
        json={
            "expected_patch_sha256": "invalid",
            "idempotency_key": str(uuid4()),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
