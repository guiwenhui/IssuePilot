from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app.db.session import session_factory
from app.models.code_index import CodeFile, CodeImport, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.parsers.python_ast import ParserLimits
from app.schemas.task import TaskStatus
from app.services.code_index_service import CodeIndexService
from app.services.workspace import WorkspaceLimits, WorkspaceManager
from tests.test_code_index_service import (
    FakeGitClient,
    FakeParserClient,
    parser_result,
)


@pytest.mark.asyncio
async def test_index_task_writes_parent_rows_before_normalized_children(
    tmp_path: Path,
) -> None:
    task = Task(
        repository_url="https://github.com/pallets/markupsafe.git",
        issue_text="Understand services",
        status=TaskStatus.CLONED,
    )
    async with session_factory() as session:
        session.add(task)
        await session.flush()
        task_id = task.id
        session.add(
            RepositorySnapshot(
                task_id=task.id,
                canonical_url=task.repository_url,
                commit_sha="a" * 40,
                file_count=1,
                total_bytes=30,
                tree_manifest=[],
            )
        )
        await session.commit()

        workspace = WorkspaceManager(
            tmp_path / "workspaces", WorkspaceLimits(1000, 20, 20, 10)
        )
        workspace.repository_path(task.id).mkdir(parents=True)
        service = CodeIndexService(
            session,
            FakeGitClient(),
            workspace,
            FakeParserClient(parser_result()),
            ParserLimits(20, 20_000, 100_000, 200),
            2_000,
        )

        try:
            await service.index_task(task.id)

            assert await session.scalar(
                select(func.count()).select_from(CodeIndex)
            ) == 1
            assert await session.scalar(
                select(func.count()).select_from(CodeFile)
            ) == 1
            assert await session.scalar(
                select(func.count()).select_from(CodeSymbol)
            ) == 2
            assert await session.scalar(
                select(func.count()).select_from(CodeImport)
            ) == 1
            await session.refresh(task)
            assert task.status == TaskStatus.INDEXED
        finally:
            await session.rollback()
            await session.execute(delete(Task).where(Task.id == task_id))
            await session.commit()
