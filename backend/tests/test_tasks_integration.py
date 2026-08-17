from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.db.session import session_factory
from app.main import create_app, mark_repository_task_failed
from app.models.task import Task
from app.schemas.task import TaskStatus


@pytest.fixture(autouse=True)
async def clean_tasks() -> AsyncIterator[None]:
    async with session_factory() as session:
        await session.execute(delete(Task))
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(delete(Task))
        await session.commit()


@pytest.fixture
async def database_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_create_then_query_persisted_task(
    database_client: AsyncClient,
) -> None:
    create_response = await database_client.post(
        "/api/v1/tasks",
        json={
            "repository_url": "https://github.com/example/project.git",
            "issue": "Fix the parser",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    query_response = await database_client.get(
        f"/api/v1/tasks/{created['task_id']}"
    )

    assert query_response.status_code == 200
    assert query_response.json() == created
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Task))
    assert count == 1


@pytest.mark.asyncio
async def test_invalid_request_does_not_insert_task(
    database_client: AsyncClient,
) -> None:
    response = await database_client.post(
        "/api/v1/tasks",
        json={"repository_url": "http://example.com/project.git", "issue": ""},
    )

    assert response.status_code == 422
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Task))
    assert count == 0


@pytest.mark.asyncio
async def test_repository_failure_handler_converges_active_task() -> None:
    async with session_factory() as session:
        task = Task(
            repository_url="https://github.com/example/project.git",
            issue_text="Fix retrieval",
            status=TaskStatus.RETRIEVING,
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    await mark_repository_task_failed(task_id)

    async with session_factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.failure_code == "REPOSITORY_PIPELINE_FAILED"


@pytest.mark.asyncio
async def test_repository_failure_handler_preserves_terminal_task() -> None:
    async with session_factory() as session:
        task = Task(
            repository_url="https://github.com/example/project.git",
            issue_text="Review plan",
            status=TaskStatus.WAITING_APPROVAL,
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    await mark_repository_task_failed(task_id)

    async with session_factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        assert task.status == TaskStatus.WAITING_APPROVAL
        assert task.failure_code is None


@pytest.mark.asyncio
async def test_repository_failure_handler_preserves_database_error_code() -> None:
    from app.services.task_service import DatabaseUnavailableError

    async with session_factory() as session:
        task = Task(
            repository_url="https://github.com/example/project.git",
            issue_text="Fix retrieval",
            status=TaskStatus.RETRIEVING,
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    await mark_repository_task_failed(task_id, DatabaseUnavailableError())

    async with session_factory() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.failure_code == "DATABASE_UNAVAILABLE"
