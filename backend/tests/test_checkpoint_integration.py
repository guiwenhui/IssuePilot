import os
from pathlib import Path
from uuid import uuid4

import pytest
from langgraph.types import Command

from app.agents.planning_graph import build_planning_graph
from app.agents.planning_state import PlanningRuntimeContext
from app.checkpoints.postgres import PostgresCheckpointFactory
from app.llms.ollama import LlmUnavailableError
from app.db.session import session_factory
from app.schemas.planning import PlanningDecisionAction, PlanningDecisionCreate
from app.services.planning_service import PlanningLimits, PlanningService
from app.services.planning_store import SqlPlanningStore
from app.services.workspace import WorkspaceLimits, WorkspaceManager
from tests.test_approval_store_integration import _clean, _planned_task
from tests.test_approval_graph import ApprovalAdapter, graph_config
from tests.test_planning_graph import FakeProvider
from tests.test_planning_service import FakeGit


@pytest.mark.asyncio
async def test_postgres_checkpoint_survives_new_factory_and_graph() -> None:
    task_id = uuid4()
    decision_id = uuid4()
    database_url = os.environ["DATABASE_URL"]
    first = PostgresCheckpointFactory(database_url, "issuepilot_checkpoint")
    adapter = ApprovalAdapter()
    context = PlanningRuntimeContext(adapter, FakeProvider())
    try:
        async with first.saver() as saver:
            graph = build_planning_graph(saver, approval_enabled=True)
            result = await graph.ainvoke(
                {"task_id": str(task_id)},
                config=graph_config(task_id),
                context=context,
            )
            assert result["__interrupt__"]

        second = PostgresCheckpointFactory(
            database_url, "issuepilot_checkpoint"
        )
        async with second.saver() as saver:
            graph = build_planning_graph(saver, approval_enabled=True)
            result = await graph.ainvoke(
                Command(
                    resume={
                        "decision_id": str(decision_id),
                        "action": "approve",
                        "comment": None,
                    }
                ),
                config=graph_config(task_id),
                context=context,
            )
            assert "__interrupt__" not in result
            assert adapter.decisions == [(decision_id, "approve")]
    finally:
        async with first.saver() as saver:
            await saver.adelete_thread(str(task_id))


@pytest.mark.asyncio
async def test_m5_plan_without_checkpoint_bootstraps_then_approves(
    tmp_path: Path,
) -> None:
    database_url = os.environ["DATABASE_URL"]
    factory = PostgresCheckpointFactory(database_url, "issuepilot_checkpoint")
    async with session_factory() as session:
        task, _, store = await _planned_task(session)
        task_id = task.id
        workspace = WorkspaceManager(
            tmp_path / "workspaces", WorkspaceLimits(10_000, 100, 100, 10)
        )
        workspace.repository_path(task_id).mkdir(parents=True)
        service = PlanningService(
            store,
            FakeGit(),
            workspace,
            FakeProvider(),
            build_planning_graph(),
            PlanningLimits(10, 3000, 20_000),
            factory,
            approval_enabled=True,
        )
        try:
            decision = await service.submit_decision(
                task_id,
                PlanningDecisionCreate(
                    action=PlanningDecisionAction.APPROVE,
                    expected_plan_version=1,
                    idempotency_key=uuid4(),
                ),
            )
            await service.process_decision(decision.decision_id)
            planning = await store.load_planning(task_id)
            assert planning is not None
            assert planning.plan.status == "approved"
        finally:
            async with factory.saver() as saver:
                await saver.adelete_thread(str(task_id))
            await _clean(session, task_id)


@pytest.mark.asyncio
async def test_saver_does_not_reclassify_graph_domain_errors() -> None:
    factory = PostgresCheckpointFactory(
        os.environ["DATABASE_URL"], "issuepilot_checkpoint"
    )

    with pytest.raises(LlmUnavailableError):
        async with factory.saver():
            raise LlmUnavailableError("offline")


@pytest.mark.asyncio
async def test_pending_decision_resumes_in_new_service_runtime(
    tmp_path: Path,
) -> None:
    database_url = os.environ["DATABASE_URL"]
    factory = PostgresCheckpointFactory(database_url, "issuepilot_checkpoint")
    workspace = WorkspaceManager(
        tmp_path / "workspaces", WorkspaceLimits(10_000, 100, 100, 10)
    )
    async with session_factory() as first_session:
        task, _, first_store = await _planned_task(first_session)
        task_id = task.id
        workspace.repository_path(task_id).mkdir(parents=True)
        first_service = _service(first_store, workspace, factory)
        decision = await first_service.submit_decision(
            task_id,
            PlanningDecisionCreate(
                action=PlanningDecisionAction.APPROVE,
                expected_plan_version=1,
                idempotency_key=uuid4(),
            ),
        )

    async with session_factory() as second_session:
        second_store = SqlPlanningStore(second_session)
        second_service = _service(second_store, workspace, factory)
        try:
            assert decision.decision_id in (
                await second_store.load_pending_decision_ids(20)
            )
            await second_service.process_decision(decision.decision_id)
            planning = await second_store.load_planning(task_id)
            assert planning is not None
            assert planning.plan.status == "approved"
        finally:
            async with factory.saver() as saver:
                await saver.adelete_thread(str(task_id))
            await _clean(second_session, task_id)


def _service(store, workspace, factory) -> PlanningService:
    return PlanningService(
        store,
        FakeGit(),
        workspace,
        FakeProvider(),
        build_planning_graph(),
        PlanningLimits(10, 3000, 20_000),
        factory,
        approval_enabled=True,
    )
