from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.task_service import TaskService


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_task_service(session: SessionDependency) -> TaskService:
    return TaskService(session)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
