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


@pytest.mark.asyncio
async def test_set_status_persists_business_failure() -> None:
    task = Mock(status=TaskStatus.QUEUED)
    session = Mock()
    session.get = AsyncMock(return_value=task)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    service = TaskService(session)

    updated = await service.set_status(
        uuid4(),
        TaskStatus.FAILED,
        failure_code="CLONE_QUEUE_FULL",
        failure_message="克隆队列已满",
    )

    assert updated.status == TaskStatus.FAILED
    assert updated.failure_code == "CLONE_QUEUE_FULL"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_failure_if_status_in_uses_one_conditional_update() -> None:
    task_id = uuid4()
    result = Mock()
    result.scalar_one_or_none.return_value = task_id
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service = TaskService(session)

    updated = await service.set_failure_if_status_in(
        task_id,
        {TaskStatus.RETRIEVING, TaskStatus.ANALYZING},
        "REPOSITORY_PIPELINE_FAILED",
        "仓库后台处理失败",
    )

    assert updated is True
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert "tasks.status IN" in str(statement)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_failure_if_status_in_preserves_nonmatching_status() -> None:
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session = Mock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service = TaskService(session)

    updated = await service.set_failure_if_status_in(
        uuid4(),
        {TaskStatus.RETRIEVING},
        "REPOSITORY_PIPELINE_FAILED",
        "仓库后台处理失败",
    )

    assert updated is False
    session.commit.assert_awaited_once()
