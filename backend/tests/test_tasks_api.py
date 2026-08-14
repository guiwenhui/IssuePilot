from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_task_service
from app.main import create_app
from app.models.task import Task
from app.schemas.task import TaskStatus
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError


class StubTaskService:
    def __init__(self) -> None:
        self.task = make_task()
        self.create_error: Optional[Exception] = None
        self.get_error: Optional[Exception] = None

    async def create_task(self, payload: object) -> Task:
        if self.create_error:
            raise self.create_error
        return self.task

    async def get_task(self, task_id: UUID) -> Task:
        if self.get_error:
            raise self.get_error
        return self.task


def make_task() -> Task:
    now = datetime.now(timezone.utc)
    return Task(
        id=uuid4(),
        repository_url="https://github.com/example/project.git",
        issue_text="Fix the parser",
        status=TaskStatus.CREATED,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def service() -> StubTaskService:
    return StubTaskService()


@pytest.fixture
async def client(service: StubTaskService) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_create_task_returns_201(client: AsyncClient, service: StubTaskService) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={
            "repository_url": "https://github.com/example/project.git",
            "issue": "Fix the parser",
        },
    )

    assert response.status_code == 201
    assert response.json()["task_id"] == str(service.task.id)
    assert response.json()["status"] == "created"
    assert response.headers["location"] == f"/api/v1/tasks/{service.task.id}"


@pytest.mark.asyncio
async def test_create_task_returns_structured_validation_error(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"repository_url": "http://example.com/project.git", "issue": ""},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]


@pytest.mark.asyncio
async def test_get_task_disables_caching(
    client: AsyncClient, service: StubTaskService
) -> None:
    response = await client.get(f"/api/v1/tasks/{service.task.id}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_get_task_returns_structured_not_found(
    client: AsyncClient, service: StubTaskService
) -> None:
    service.get_error = TaskNotFoundError()

    response = await client.get(f"/api/v1/tasks/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


@pytest.mark.asyncio
async def test_database_failure_returns_503(
    client: AsyncClient, service: StubTaskService
) -> None:
    service.create_error = DatabaseUnavailableError()

    response = await client.post(
        "/api/v1/tasks",
        json={
            "repository_url": "https://github.com/example/project.git",
            "issue": "Fix the parser",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_unexpected_failure_returns_sanitized_500(
    service: StubTaskService,
) -> None:
    service.create_error = RuntimeError("sensitive implementation detail")
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/tasks",
            json={
                "repository_url": "https://github.com/example/project.git",
                "issue": "Fix the parser",
            },
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "sensitive" not in response.text
