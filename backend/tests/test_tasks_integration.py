from typing import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.db.session import session_factory
from app.main import create_app
from app.models.task import Task


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
