from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.schemas.repository import RepositoryTreeResponse
from app.schemas.task import TaskStatus
from app.services.git_client import (
    CloneFailedError,
    CloneTimeoutError,
    GitClient,
    GitUnavailableError,
    RepositoryUnavailableError,
)
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError
from app.services.workspace import (
    RepositoryTooLargeError,
    RepositoryTreeLimitError,
    WorkspaceManager,
)


class RepositoryNotReadyError(Exception):
    pass


class WorkspaceInconsistentError(Exception):
    pass


FAILURE_MESSAGES = {
    "REPOSITORY_UNAVAILABLE": "仓库不存在、不是公开仓库或当前无法访问",
    "CLONE_TIMEOUT": "仓库克隆超时",
    "CLONE_FAILED": "仓库克隆失败",
    "GIT_UNAVAILABLE": "Git 运行环境不可用",
    "REPOSITORY_TOO_LARGE": "仓库超过允许的体积",
    "REPOSITORY_TREE_LIMIT_EXCEEDED": "仓库文件数量或目录深度超过限制",
}


class RepositoryService:
    def __init__(
        self,
        session: AsyncSession,
        git_client: GitClient,
        workspace: WorkspaceManager,
    ) -> None:
        self._session = session
        self._git = git_client
        self._workspace = workspace

    async def clone_task(self, task_id: UUID) -> None:
        task = await self._get_task(task_id)
        if task.status != TaskStatus.QUEUED:
            return
        await self._set_task_status(task, TaskStatus.CLONING)
        staging = self._workspace.create_staging(task_id)
        try:
            await self._clone_and_persist(task, staging)
        except _known_clone_errors() as error:
            self._workspace.cleanup_staging(staging)
            code = _failure_code(error)
            await self._set_task_status(
                task,
                TaskStatus.FAILED,
                failure_code=code,
                failure_message=FAILURE_MESSAGES[code],
            )

    async def get_tree(self, task_id: UUID) -> RepositoryTreeResponse:
        task = await self._get_task(task_id)
        if task.status != TaskStatus.CLONED:
            raise RepositoryNotReadyError()
        try:
            snapshot = await self._session.get(RepositorySnapshot, task_id)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error
        if snapshot is None:
            raise WorkspaceInconsistentError()
        repository = self._workspace.repository_path(task_id)
        await self._verify_workspace(repository, snapshot.commit_sha)
        return RepositoryTreeResponse(
            task_id=task_id,
            canonical_url=snapshot.canonical_url,
            commit_sha=snapshot.commit_sha,
            file_count=snapshot.file_count,
            total_bytes=snapshot.total_bytes,
            truncated=snapshot.file_count > len(snapshot.tree_manifest),
            cloned_at=snapshot.cloned_at,
            entries=snapshot.tree_manifest,
        )

    async def _clone_and_persist(self, task: Task, staging: Path) -> None:
        await self._git.ensure_remote_available(task.repository_url)
        await self._git.clone(task.repository_url, staging)
        commit_sha = await self._git.head_sha(staging)
        tracked_entries = await self._git.tracked_entries(staging)
        manifest = self._workspace.build_manifest(staging, tracked_entries)
        self._workspace.finalize(task.id, staging)
        snapshot = RepositorySnapshot(
            task_id=task.id,
            canonical_url=task.repository_url,
            commit_sha=commit_sha,
            file_count=manifest.file_count,
            total_bytes=manifest.total_bytes,
            tree_manifest=manifest.entries,
        )
        self._session.add(snapshot)
        await self._set_task_status(task, TaskStatus.CLONED)

    async def _get_task(self, task_id: UUID) -> Task:
        try:
            task = await self._session.get(Task, task_id)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error
        if task is None:
            raise TaskNotFoundError()
        return task

    async def _set_task_status(
        self,
        task: Task,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> None:
        task.status = status
        task.failure_code = failure_code
        task.failure_message = failure_message
        try:
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def _verify_workspace(self, repository: Path, expected_sha: str) -> None:
        if not repository.is_dir():
            raise WorkspaceInconsistentError()
        actual_sha = await self._git.head_sha(repository)
        if actual_sha != expected_sha or not await self._git.is_clean(repository):
            raise WorkspaceInconsistentError()


def _known_clone_errors() -> tuple[type[Exception], ...]:
    return (
        RepositoryUnavailableError,
        CloneTimeoutError,
        CloneFailedError,
        GitUnavailableError,
        RepositoryTooLargeError,
        RepositoryTreeLimitError,
    )


def _failure_code(error: Exception) -> str:
    mapping = {
        RepositoryUnavailableError: "REPOSITORY_UNAVAILABLE",
        CloneTimeoutError: "CLONE_TIMEOUT",
        CloneFailedError: "CLONE_FAILED",
        GitUnavailableError: "GIT_UNAVAILABLE",
        RepositoryTooLargeError: "REPOSITORY_TOO_LARGE",
        RepositoryTreeLimitError: "REPOSITORY_TREE_LIMIT_EXCEEDED",
    }
    return mapping[type(error)]
