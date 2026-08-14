from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_repository_queue,
    get_repository_service,
    get_task_service,
)
from app.main import create_app
from app.models.task import Task
from app.schemas.repository import RepositoryTreeResponse
from app.schemas.task import TaskStatus
from app.services.repository_service import (
    RepositoryNotReadyError,
    WorkspaceInconsistentError,
)
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError
from app.workers.repository_queue import CloneQueueFullError


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

    async def set_status(
        self,
        task_id: UUID,
        task_status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> Task:
        self.task.status = task_status
        self.task.failure_code = failure_code
        self.task.failure_message = failure_message
        return self.task


class StubRepositoryService:
    def __init__(self, task_id: UUID) -> None:
        self.error: Optional[Exception] = None
        self.tree = RepositoryTreeResponse(
            task_id=task_id,
            canonical_url="https://github.com/example/project.git",
            commit_sha="a" * 40,
            file_count=1,
            total_bytes=12,
            truncated=False,
            cloned_at=datetime.now(timezone.utc),
            entries=[
                {"path": "README.md", "kind": "file", "size_bytes": 12}
            ],
        )

    async def get_tree(self, task_id: UUID) -> RepositoryTreeResponse:
        if self.error:
            raise self.error
        return self.tree


class FullRepositoryQueue:
    enabled = True

    def enqueue(self, task_id: UUID) -> bool:
        raise CloneQueueFullError()


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
    assert response.json()["status"] == "queued"
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


@pytest.mark.asyncio
async def test_repository_tree_returns_persisted_manifest(
    service: StubTaskService,
) -> None:
    repository_service = StubRepositoryService(service.task.id)
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: service
    app.dependency_overrides[get_repository_service] = lambda: repository_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/tasks/{service.task.id}/repository/tree"
        )

    assert response.status_code == 200
    assert response.json()["commit_sha"] == "a" * 40
    assert response.json()["entries"][0]["path"] == "README.md"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (RepositoryNotReadyError(), "REPOSITORY_NOT_READY"),
        (WorkspaceInconsistentError(), "WORKSPACE_INCONSISTENT"),
    ],
)
async def test_repository_tree_returns_structured_conflict(
    service: StubTaskService,
    error: Exception,
    expected_code: str,
) -> None:
    repository_service = StubRepositoryService(service.task.id)
    repository_service.error = error
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: service
    app.dependency_overrides[get_repository_service] = lambda: repository_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/v1/tasks/{service.task.id}/repository/tree"
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == expected_code


@pytest.mark.asyncio
async def test_create_task_persists_queue_capacity_failure(
    service: StubTaskService,
) -> None:
    app = create_app()
    app.dependency_overrides[get_task_service] = lambda: service
    app.dependency_overrides[get_repository_queue] = lambda: FullRepositoryQueue()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/tasks",
            json={
                "repository_url": "https://github.com/example/project.git",
                "issue": "Fix the parser",
            },
        )

    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["failure"]["code"] == "CLONE_QUEUE_FULL"
