from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.schemas.task import TaskCreate, TaskStatus
from app.services.task_service import (
    DatabaseUnavailableError,
    TaskNotFoundError,
    TaskService,
)


def make_payload() -> TaskCreate:
    return TaskCreate(
        repository_url="https://github.com/example/project.git",
        issue="Fix the parser",
    )


@pytest.mark.asyncio
async def test_create_task_persists_created_status() -> None:
    session = Mock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    service = TaskService(session)

    task = await service.create_task(make_payload())

    session.add.assert_called_once_with(task)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(task)
    assert task.status == TaskStatus.CREATED


@pytest.mark.asyncio
async def test_create_task_rolls_back_database_failure() -> None:
    session = Mock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.commit.side_effect = OperationalError("insert", {}, Exception("down"))
    service = TaskService(session)

    with pytest.raises(DatabaseUnavailableError):
        await service.create_task(make_payload())

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_task_maps_connection_refused_to_database_unavailable() -> None:
    session = Mock()
    session.commit = AsyncMock(side_effect=ConnectionRefusedError("down"))
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    service = TaskService(session)

    with pytest.raises(DatabaseUnavailableError):
        await service.create_task(make_payload())

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_task_raises_not_found_for_missing_record() -> None:
    session = Mock()
    session.get = AsyncMock(return_value=None)
    session.get.return_value = None
    service = TaskService(session)

    with pytest.raises(TaskNotFoundError):
        await service.get_task(uuid4())


@pytest.mark.asyncio
async def test_get_task_maps_database_failure() -> None:
    session = Mock()
    session.get = AsyncMock(
        side_effect=OperationalError("select", {}, Exception("down"))
    )
    service = TaskService(session)

    with pytest.raises(DatabaseUnavailableError):
        await service.get_task(uuid4())
