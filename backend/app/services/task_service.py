from typing import Collection, Optional
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.schemas.task import TaskCreate, TaskStatus


class TaskNotFoundError(Exception):
    pass


class DatabaseUnavailableError(Exception):
    pass


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_task(self, payload: TaskCreate) -> Task:
        task = Task(
            repository_url=payload.repository_url,
            issue_text=payload.issue,
            status=TaskStatus.CREATED,
        )
        self._session.add(task)

        try:
            await self._session.commit()
            await self._session.refresh(task)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

        return task

    async def get_task(self, task_id: UUID) -> Task:
        try:
            task = await self._session.get(Task, task_id)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error

        if task is None:
            raise TaskNotFoundError()
        return task

    async def set_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> Task:
        task = await self.get_task(task_id)
        task.status = status
        task.failure_code = failure_code
        task.failure_message = failure_message
        try:
            await self._session.commit()
            await self._session.refresh(task)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        return task

    async def set_failure_if_status_in(
        self,
        task_id: UUID,
        expected_statuses: Collection[TaskStatus],
        failure_code: str,
        failure_message: str,
    ) -> bool:
        try:
            result = await self._session.execute(
                update(Task)
                .where(
                    Task.id == task_id,
                    Task.status.in_(tuple(expected_statuses)),
                )
                .values(
                    status=TaskStatus.FAILED,
                    failure_code=failure_code,
                    failure_message=failure_message,
                )
                .returning(Task.id)
            )
            updated = result.scalar_one_or_none() is not None
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        return updated
