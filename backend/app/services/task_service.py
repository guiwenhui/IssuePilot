from uuid import UUID

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
