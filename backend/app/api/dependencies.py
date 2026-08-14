from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.code_index_service import CodeIndexService
from app.services.repository_service import RepositoryService
from app.services.task_service import TaskService
from app.workers.repository_queue import RepositoryQueue


SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_task_service(session: SessionDependency) -> TaskService:
    return TaskService(session)


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]


def get_repository_queue(request: Request) -> RepositoryQueue:
    return request.app.state.repository_queue


RepositoryQueueDependency = Annotated[
    RepositoryQueue, Depends(get_repository_queue)
]


def get_repository_service(
    request: Request,
    session: SessionDependency,
) -> RepositoryService:
    return RepositoryService(
        session,
        request.app.state.git_client,
        request.app.state.workspace,
    )


RepositoryServiceDependency = Annotated[
    RepositoryService, Depends(get_repository_service)
]


def get_code_index_service(
    request: Request,
    session: SessionDependency,
) -> CodeIndexService:
    return CodeIndexService(
        session,
        request.app.state.git_client,
        request.app.state.workspace,
        request.app.state.parser_client,
        request.app.state.parser_limits,
        request.app.state.max_code_preview_entries,
    )


CodeIndexServiceDependency = Annotated[
    CodeIndexService, Depends(get_code_index_service)
]
