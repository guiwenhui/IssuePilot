from typing import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.parsers.python_ast import ParserLimits
from app.schemas.task import TaskStatus
from app.services.code_index_service import CodeIndexService
from app.services.git_client import GitClient
from app.services.parser_client import ParserClient
from app.services.repository_service import RepositoryService
from app.services.retrieval_service import RetrievalService
from app.services.workspace import WorkspaceManager


RetrievalServiceFactory = Callable[[AsyncSession], RetrievalService]


class RepositoryPipeline:
    def __init__(
        self,
        git_client: GitClient,
        workspace: WorkspaceManager,
        parser_client: ParserClient,
        parser_limits: ParserLimits,
        max_preview_entries: int,
        retrieval_service_factory: RetrievalServiceFactory,
    ) -> None:
        self._git = git_client
        self._workspace = workspace
        self._parser = parser_client
        self._limits = parser_limits
        self._max_preview_entries = max_preview_entries
        self._retrieval_service_factory = retrieval_service_factory

    async def process(self, session: AsyncSession, task_id: UUID) -> None:
        repository_service = RepositoryService(
            session, self._git, self._workspace
        )
        await repository_service.clone_task(task_id, TaskStatus.INDEXING)
        code_index_service = CodeIndexService(
            session,
            self._git,
            self._workspace,
            self._parser,
            self._limits,
            self._max_preview_entries,
        )
        await code_index_service.index_task(task_id, TaskStatus.RETRIEVING)
        task = await session.get(Task, task_id)
        if task is not None and task.status == TaskStatus.RETRIEVING:
            retrieval_service = self._retrieval_service_factory(session)
            await retrieval_service.retrieve_task(task_id)
