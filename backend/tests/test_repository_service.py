from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.schemas.task import TaskStatus
from app.services.git_client import RepositoryUnavailableError, TrackedEntry
from app.services.repository_service import (
    RepositoryNotReadyError,
    RepositoryService,
    WorkspaceInconsistentError,
)
from app.services.task_service import DatabaseUnavailableError
from app.services.workspace import WorkspaceLimits, WorkspaceManager


class FakeGitClient:
    def __init__(self) -> None:
        self.remote_error = None
        self.sha = "a" * 40
        self.clean = True

    async def ensure_remote_available(self, url: str) -> None:
        if self.remote_error:
            raise self.remote_error

    async def clone(self, url: str, destination: Path) -> None:
        (destination / "README.md").write_text("hello", encoding="utf-8")

    async def head_sha(self, repository: Path) -> str:
        return self.sha

    async def tracked_entries(self, repository: Path) -> list[TrackedEntry]:
        return [TrackedEntry("README.md", "file", 5)]

    async def is_clean(self, repository: Path) -> bool:
        return self.clean


def make_workspace(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(
        tmp_path / "workspaces",
        WorkspaceLimits(10_000, 100, 100, 10),
    )


def make_task(status: TaskStatus) -> Task:
    return Task(
        id=uuid4(),
        repository_url="https://github.com/pallets/markupsafe.git",
        issue_text="Inspect the tree",
        status=status,
    )


@pytest.mark.asyncio
async def test_clone_task_persists_snapshot_and_cloned_status(tmp_path: Path) -> None:
    task = make_task(TaskStatus.QUEUED)
    session = Mock()
    session.get = AsyncMock(return_value=task)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    git = FakeGitClient()
    workspace = make_workspace(tmp_path)
    service = RepositoryService(session, git, workspace)

    await service.clone_task(task.id)

    assert task.status == TaskStatus.CLONED
    snapshot = next(
        item
        for item in session.add.call_args_list
        if isinstance(item.args[0], RepositorySnapshot)
    ).args[0]
    assert snapshot.commit_sha == "a" * 40
    assert snapshot.tree_manifest[0]["path"] == "README.md"
    assert workspace.repository_path(task.id).is_dir()


@pytest.mark.asyncio
async def test_clone_task_maps_public_access_failure_and_cleans_staging(
    tmp_path: Path,
) -> None:
    task = make_task(TaskStatus.QUEUED)
    session = Mock()
    session.get = AsyncMock(return_value=task)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    git = FakeGitClient()
    git.remote_error = RepositoryUnavailableError("private details")
    workspace = make_workspace(tmp_path)
    service = RepositoryService(session, git, workspace)

    await service.clone_task(task.id)

    assert task.status == TaskStatus.FAILED
    assert task.failure_code == "REPOSITORY_UNAVAILABLE"
    assert list(workspace.staging_root.iterdir()) == []


@pytest.mark.asyncio
async def test_repository_tree_requires_cloned_task(tmp_path: Path) -> None:
    task = make_task(TaskStatus.CLONING)
    session = Mock()
    session.get = AsyncMock(return_value=task)
    service = RepositoryService(session, FakeGitClient(), make_workspace(tmp_path))

    with pytest.raises(RepositoryNotReadyError):
        await service.get_tree(task.id)


@pytest.mark.asyncio
async def test_repository_tree_detects_commit_mismatch(tmp_path: Path) -> None:
    task = make_task(TaskStatus.CLONED)
    snapshot = RepositorySnapshot(
        task_id=task.id,
        canonical_url=task.repository_url,
        commit_sha="b" * 40,
        file_count=1,
        total_bytes=5,
        tree_manifest=[
            {"path": "README.md", "kind": "file", "size_bytes": 5}
        ],
    )
    session = Mock()
    session.get = AsyncMock(side_effect=[task, snapshot])
    workspace = make_workspace(tmp_path)
    repository = workspace.repository_path(task.id)
    repository.mkdir(parents=True)
    service = RepositoryService(session, FakeGitClient(), workspace)

    with pytest.raises(WorkspaceInconsistentError):
        await service.get_tree(task.id)


@pytest.mark.asyncio
async def test_repository_tree_maps_database_failure(tmp_path: Path) -> None:
    session = Mock()
    session.get = AsyncMock(
        side_effect=OperationalError("select", {}, Exception("down"))
    )
    service = RepositoryService(session, FakeGitClient(), make_workspace(tmp_path))

    with pytest.raises(DatabaseUnavailableError):
        await service.get_tree(uuid4())
