from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.parsers.python_ast import ParserLimits
from app.schemas.code_index import ParsedFile, ParsedSymbol, ParserResult
from app.schemas.task import TaskStatus
from app.services.git_client import TrackedEntry
from app.services.workspace import WorkspaceLimits, WorkspaceManager
from app.workers.repository_pipeline import RepositoryPipeline


class PipelineGitClient:
    async def ensure_remote_available(self, url: str) -> None:
        return None

    async def clone(self, url: str, destination: Path) -> None:
        (destination / "service.py").write_text(
            "class Service:\n    pass\n", encoding="utf-8"
        )

    async def head_sha(self, repository: Path) -> str:
        return "a" * 40

    async def tracked_entries(self, repository: Path) -> list[TrackedEntry]:
        return [TrackedEntry("service.py", "file", 24)]

    async def is_clean(self, repository: Path) -> bool:
        return True


class PipelineParserClient:
    async def parse(
        self, repository: Path, paths: list[str], limits: ParserLimits
    ) -> ParserResult:
        assert paths == ["service.py"]
        return ParserResult(
            parser_version="py-ast-v1",
            python_version="3.9.6",
            files=[
                ParsedFile(
                    path="service.py",
                    module_name="service",
                    source_sha256="b" * 64,
                    line_count=2,
                    size_bytes=24,
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
                        )
                    ],
                )
            ],
            parsed_file_count=1,
            symbol_count=1,
            import_count=0,
            test_count=0,
            parse_error_count=0,
        )


class PipelineRetrievalService:
    def __init__(
        self, task: Task, result_status: TaskStatus = TaskStatus.RETRIEVED
    ) -> None:
        self.task = task
        self.called = False
        self.result_status = result_status

    async def retrieve_task(self, task_id: object) -> None:
        self.called = True
        self.task.status = self.result_status


class PipelinePlanningService:
    def __init__(self, task: Task) -> None:
        self.task = task
        self.called = False

    async def plan_task(self, task_id: object) -> None:
        self.called = True
        self.task.status = TaskStatus.WAITING_APPROVAL


@pytest.mark.asyncio
async def test_pipeline_clones_then_indexes_task(tmp_path: Path) -> None:
    task = Task(
        id=uuid4(),
        repository_url="https://github.com/pallets/markupsafe.git",
        issue_text="Understand service",
        status=TaskStatus.QUEUED,
    )
    session = Mock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    async def get_record(model: type, record_id: object) -> object:
        if model is Task:
            return task
        if model is RepositorySnapshot:
            for call in session.add.call_args_list:
                if isinstance(call.args[0], RepositorySnapshot):
                    return call.args[0]
        return None

    session.get = AsyncMock(side_effect=get_record)
    workspace = WorkspaceManager(
        tmp_path / "workspaces", WorkspaceLimits(10_000, 100, 100, 10)
    )
    retrieval = PipelineRetrievalService(task)
    pipeline = RepositoryPipeline(
        PipelineGitClient(),
        workspace,
        PipelineParserClient(),
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
        lambda current_session: retrieval,
    )

    await pipeline.process(session, task.id)

    assert task.status == TaskStatus.RETRIEVED
    assert retrieval.called is True
    assert workspace.repository_path(task.id).is_dir()


@pytest.mark.asyncio
async def test_pipeline_runs_planning_only_after_analyzing(tmp_path: Path) -> None:
    task = Task(
        id=uuid4(),
        repository_url="https://github.com/pallets/markupsafe.git",
        issue_text="Understand service",
        status=TaskStatus.QUEUED,
    )
    session = Mock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()

    async def get_record(model: type, record_id: object) -> object:
        if model is Task:
            return task
        if model is RepositorySnapshot:
            for call in session.add.call_args_list:
                if isinstance(call.args[0], RepositorySnapshot):
                    return call.args[0]
        return None

    session.get = AsyncMock(side_effect=get_record)
    workspace = WorkspaceManager(
        tmp_path / "workspaces", WorkspaceLimits(10_000, 100, 100, 10)
    )
    retrieval = PipelineRetrievalService(task, TaskStatus.ANALYZING)
    planning = PipelinePlanningService(task)
    pipeline = RepositoryPipeline(
        PipelineGitClient(),
        workspace,
        PipelineParserClient(),
        ParserLimits(20, 20_000, 100_000, 200),
        2_000,
        lambda current_session: retrieval,
        lambda current_session: planning,
    )

    await pipeline.process(session, task.id)

    assert retrieval.called is True
    assert planning.called is True
    assert task.status == TaskStatus.WAITING_APPROVAL
