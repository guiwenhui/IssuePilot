from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest

from app.llms.ollama import LlmUnavailableError
from app.schemas.task import TaskStatus
from app.services.planning_service import (
    PlanningContext,
    PlanningEvidenceRecord,
    PlanningLimits,
    PlanningService,
)
from app.services.repository_service import WorkspaceInconsistentError
from app.services.task_service import DatabaseUnavailableError
from app.services.workspace import WorkspaceLimits, WorkspaceManager


class FakeGit:
    sha = "a" * 40
    clean = True

    async def head_sha(self, repository: Path) -> str:
        return self.sha

    async def is_clean(self, repository: Path) -> bool:
        return self.clean


class FakeProvider:
    name = "fake"
    model = "fake-model"


class FakeStore:
    def __init__(self, context: PlanningContext) -> None:
        self.context = context
        self.status: Optional[TaskStatus] = None
        self.failure_code: Optional[str] = None
        self.load_error: Optional[Exception] = None

    async def load_context(self, task_id: UUID) -> PlanningContext:
        if self.load_error:
            raise self.load_error
        return self.context

    async def persist_planning(self, *args, **kwargs) -> UUID:
        return uuid4()

    async def load_planning(self, task_id: UUID):
        return None

    async def set_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> None:
        self.status = status
        self.failure_code = failure_code


class RecordingGraph:
    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.bundle = None

    async def ainvoke(self, state, context, config):
        if self.error:
            raise self.error
        self.bundle = await context.adapter.load_evidence(UUID(state["task_id"]))
        return {"planning_run_id": str(uuid4())}


def make_context() -> PlanningContext:
    task_id = uuid4()
    return PlanningContext(
        task_id=task_id,
        issue="Fix nullable escaping",
        status=TaskStatus.ANALYZING,
        snapshot_sha="a" * 40,
        index_sha="a" * 40,
        retrieval_run_id=uuid4(),
        retrieval_sha="a" * 40,
        evidence=[
            PlanningEvidenceRecord(
                rank=1,
                path="src/module.py",
                symbol="escape_silent",
                kind="function",
                start_line=1,
                end_line=4,
                content="x" * 12,
                matched_channels=["symbol", "vector"],
            ),
            PlanningEvidenceRecord(
                rank=2,
                path="tests/test_module.py",
                symbol="test_escape_silent",
                kind="function",
                start_line=1,
                end_line=3,
                content="y" * 12,
                matched_channels=["keyword"],
            ),
        ],
    )


def make_service(tmp_path: Path, graph: RecordingGraph):
    context = make_context()
    workspace = WorkspaceManager(
        tmp_path / "workspaces", WorkspaceLimits(10_000, 100, 100, 10)
    )
    workspace.repository_path(context.task_id).mkdir(parents=True)
    store = FakeStore(context)
    service = PlanningService(
        store,
        FakeGit(),
        workspace,
        FakeProvider(),
        graph,
        PlanningLimits(10, 10, 15),
    )
    return service, store, context


@pytest.mark.asyncio
async def test_plan_task_builds_bounded_deterministic_evidence(tmp_path: Path) -> None:
    graph = RecordingGraph()
    service, _, context = make_service(tmp_path, graph)

    await service.plan_task(context.task_id)

    assert graph.bundle is not None
    assert [len(item.snippet) for item in graph.bundle.evidence] == [10, 5]
    assert graph.bundle.evidence_truncated is True
    first_sha = graph.bundle.evidence_sha256
    second = await service.load_evidence(context.task_id)
    assert second.evidence_sha256 == first_sha


@pytest.mark.asyncio
async def test_plan_task_stops_when_stage_is_not_analyzing(tmp_path: Path) -> None:
    graph = RecordingGraph()
    service, _, context = make_service(tmp_path, graph)
    object.__setattr__(context, "status", TaskStatus.RETRIEVED)

    await service.plan_task(context.task_id)

    assert graph.bundle is None


@pytest.mark.asyncio
async def test_plan_task_maps_llm_outage_to_stable_failure(tmp_path: Path) -> None:
    graph = RecordingGraph(LlmUnavailableError("offline"))
    service, store, context = make_service(tmp_path, graph)

    await service.plan_task(context.task_id)

    assert store.status == TaskStatus.FAILED
    assert store.failure_code == "LLM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_plan_task_maps_initial_context_mismatch_to_failure(
    tmp_path: Path,
) -> None:
    service, store, context = make_service(tmp_path, RecordingGraph())
    store.load_error = WorkspaceInconsistentError()

    await service.plan_task(context.task_id)

    assert store.status == TaskStatus.FAILED
    assert store.failure_code == "WORKSPACE_INCONSISTENT"


@pytest.mark.asyncio
async def test_plan_task_does_not_convert_database_outage(tmp_path: Path) -> None:
    graph = RecordingGraph(DatabaseUnavailableError())
    service, store, context = make_service(tmp_path, graph)

    with pytest.raises(DatabaseUnavailableError):
        await service.plan_task(context.task_id)

    assert store.status is None


@pytest.mark.asyncio
async def test_load_evidence_rejects_commit_or_worktree_mismatch(
    tmp_path: Path,
) -> None:
    service, _, context = make_service(tmp_path, RecordingGraph())
    object.__setattr__(context, "index_sha", "b" * 40)

    with pytest.raises(WorkspaceInconsistentError):
        await service.load_evidence(context.task_id)
