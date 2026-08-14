from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models.code_index import CodeFile, CodeImport, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.parsers.python_ast import NoPythonFilesError, ParserLimits
from app.schemas.code_index import (
    ParsedFile,
    ParsedImport,
    ParsedSymbol,
    ParserResult,
)
from app.schemas.task import TaskStatus
from app.services.code_index_service import CodeIndexNotReadyError, CodeIndexService
from app.services.git_client import TrackedEntry
from app.services.workspace import WorkspaceLimits, WorkspaceManager


class FakeGitClient:
    sha = "a" * 40
    clean = True

    async def head_sha(self, repository: Path) -> str:
        return self.sha

    async def is_clean(self, repository: Path) -> bool:
        return self.clean

    async def tracked_entries(self, repository: Path) -> list[TrackedEntry]:
        return [
            TrackedEntry("service.py", "file", 30),
            TrackedEntry("linked.py", "symlink", None),
        ]


class FakeParserClient:
    def __init__(self, result: ParserResult) -> None:
        self.result = result
        self.paths: list[str] = []

    async def parse(
        self, repository: Path, paths: list[str], limits: ParserLimits
    ) -> ParserResult:
        self.paths = list(paths)
        return self.result


def parser_result() -> ParserResult:
    return ParserResult(
        parser_version="py-ast-v1",
        python_version="3.9.6",
        files=[
            ParsedFile(
                path="service.py",
                module_name="service",
                source_sha256="b" * 64,
                line_count=2,
                size_bytes=30,
                is_test_file=False,
                parse_status="parsed",
                symbols=[
                    ParsedSymbol(
                        local_id=1,
                        kind="class",
                        name="Service",
                        qualified_name="Service",
                        start_line=1,
                        end_line=2,
                    ),
                    ParsedSymbol(
                        local_id=2,
                        parent_local_id=1,
                        kind="method",
                        name="run",
                        qualified_name="Service.run",
                        start_line=2,
                        end_line=2,
                    ),
                ],
                imports=[
                    ParsedImport(kind="import", module="os", line=1)
                ],
            )
        ],
        parsed_file_count=1,
        symbol_count=2,
        import_count=1,
        test_count=0,
        parse_error_count=0,
    )


def task_and_snapshot() -> tuple[Task, RepositorySnapshot]:
    task = Task(
        id=uuid4(),
        repository_url="https://github.com/pallets/markupsafe.git",
        issue_text="Understand services",
        status=TaskStatus.CLONED,
    )
    snapshot = RepositorySnapshot(
        task_id=task.id,
        canonical_url=task.repository_url,
        commit_sha="a" * 40,
        file_count=1,
        total_bytes=30,
        tree_manifest=[],
    )
    return task, snapshot


def workspace_for(tmp_path: Path, task: Task) -> WorkspaceManager:
    workspace = WorkspaceManager(
        tmp_path / "workspaces", WorkspaceLimits(1000, 20, 20, 10)
    )
    workspace.repository_path(task.id).mkdir(parents=True)
    return workspace


@pytest.mark.asyncio
async def test_index_task_persists_normalized_entities_and_indexed_status(
    tmp_path: Path,
) -> None:
    task, snapshot = task_and_snapshot()
    session = Mock()
    session.get = AsyncMock(side_effect=[task, snapshot])
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    parser = FakeParserClient(parser_result())
    service = CodeIndexService(
        session,
        FakeGitClient(),
        workspace_for(tmp_path, task),
        parser,
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
    )

    await service.index_task(task.id)

    assert task.status == TaskStatus.INDEXED
    assert parser.paths == ["service.py"]
    added = [call.args[0] for call in session.add.call_args_list]
    assert sum(isinstance(item, CodeIndex) for item in added) == 1
    assert sum(isinstance(item, CodeFile) for item in added) == 1
    assert sum(isinstance(item, CodeSymbol) for item in added) == 2
    assert sum(isinstance(item, CodeImport) for item in added) == 1
    symbols = [item for item in added if isinstance(item, CodeSymbol)]
    assert symbols[1].parent_id == symbols[0].id
    assert session.flush.await_count == 4
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_index_task_maps_no_python_files_to_persisted_failure(
    tmp_path: Path,
) -> None:
    task, snapshot = task_and_snapshot()
    session = Mock()
    session.get = AsyncMock(side_effect=[task, snapshot])
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    parser = FakeParserClient(parser_result())
    parser.parse = AsyncMock(side_effect=NoPythonFilesError())
    service = CodeIndexService(
        session,
        FakeGitClient(),
        workspace_for(tmp_path, task),
        parser,
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
    )

    await service.index_task(task.id)

    assert task.status == TaskStatus.FAILED
    assert task.failure_code == "NO_PYTHON_FILES"
    assert task.failure_message == "仓库中没有可解析的 Python 文件"


@pytest.mark.asyncio
async def test_index_task_ignores_tasks_not_ready_for_indexing(
    tmp_path: Path,
) -> None:
    task, _ = task_and_snapshot()
    task.status = TaskStatus.FAILED
    session = Mock()
    session.get = AsyncMock(return_value=task)
    parser = FakeParserClient(parser_result())
    service = CodeIndexService(
        session,
        FakeGitClient(),
        workspace_for(tmp_path, task),
        parser,
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
    )

    await service.index_task(task.id)

    assert parser.paths == []
    session.commit.assert_not_called()


class ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> "ScalarResult":
        return self

    def all(self) -> list[object]:
        return self._values


@pytest.mark.asyncio
async def test_get_structure_returns_hierarchy_bound_to_workspace(
    tmp_path: Path,
) -> None:
    task, snapshot = task_and_snapshot()
    task.status = TaskStatus.INDEXED
    index = CodeIndex(
        task_id=task.id,
        commit_sha="a" * 40,
        parser_version="py-ast-v1",
        python_version="3.9.6",
        file_count=1,
        parsed_file_count=1,
        symbol_count=2,
        import_count=1,
        test_count=1,
        parse_error_count=0,
        indexed_at=datetime.now(timezone.utc),
    )
    file_id = uuid4()
    parent_id = uuid4()
    code_file = CodeFile(
        id=file_id,
        task_id=task.id,
        path="service.py",
        module_name="service",
        source_sha256="b" * 64,
        line_count=4,
        size_bytes=40,
        is_test_file=False,
        parse_status="parsed",
    )
    symbols = [
        CodeSymbol(
            id=parent_id,
            file_id=file_id,
            kind="class",
            name="Service",
            qualified_name="Service",
            start_line=1,
            end_line=4,
            decorators=[],
            is_async=False,
            is_test=False,
            is_fixture=False,
        ),
        CodeSymbol(
            id=uuid4(),
            file_id=file_id,
            parent_id=parent_id,
            kind="method",
            name="test_run",
            qualified_name="Service.test_run",
            start_line=2,
            end_line=4,
            decorators=[],
            is_async=False,
            is_test=True,
            is_fixture=False,
        ),
    ]
    imports = [
        CodeImport(
            id=uuid4(),
            file_id=file_id,
            kind="import",
            module="os",
            relative_level=0,
            line=1,
        )
    ]
    session = Mock()
    session.get = AsyncMock(side_effect=[task, snapshot, index])
    session.execute = AsyncMock(
        side_effect=[
            ScalarResult([code_file]),
            ScalarResult(symbols),
            ScalarResult(imports),
        ]
    )
    service = CodeIndexService(
        session,
        FakeGitClient(),
        workspace_for(tmp_path, task),
        FakeParserClient(parser_result()),
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
    )

    structure = await service.get_structure(task.id)

    assert structure.counts.symbols == 2
    assert structure.files[0].symbols[1].parent_local_id == 1
    assert structure.files[0].imports[0].module == "os"


@pytest.mark.asyncio
async def test_get_structure_requires_persisted_index(tmp_path: Path) -> None:
    task, snapshot = task_and_snapshot()
    session = Mock()
    session.get = AsyncMock(side_effect=[task, snapshot, None])
    service = CodeIndexService(
        session,
        FakeGitClient(),
        workspace_for(tmp_path, task),
        FakeParserClient(parser_result()),
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
    )

    with pytest.raises(CodeIndexNotReadyError):
        await service.get_structure(task.id)
