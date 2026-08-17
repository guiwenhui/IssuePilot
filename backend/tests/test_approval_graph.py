from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.planning_graph import GRAPH_VERSION, build_planning_graph
from app.agents.planning_state import PlanningRuntimeContext
from app.schemas.planning import ImplementationPlanDraft, RequirementAnalysisDraft
from tests.test_planning_graph import FakeAdapter, FakeProvider


class ApprovalAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[tuple[UUID, str]] = []
        self.revisions: list[tuple[UUID, str]] = []

    async def apply_decision(self, decision_id: UUID, action: str) -> None:
        self.decisions.append((decision_id, action))

    async def persist_revision(
        self,
        decision_id: UUID,
        bundle,
        plan: ImplementationPlanDraft,
        feedback: str,
    ) -> int:
        self.revisions.append((decision_id, feedback))
        return 2


def graph_config(task_id: UUID) -> dict:
    return {
        "configurable": {
            "thread_id": str(task_id),
            "checkpoint_ns": "",
        },
        "recursion_limit": 16,
    }


@pytest.mark.asyncio
async def test_approval_graph_interrupts_before_any_decision() -> None:
    task_id = uuid4()
    adapter = ApprovalAdapter()
    graph = build_planning_graph(InMemorySaver(), approval_enabled=True)

    result = await graph.ainvoke(
        {"task_id": str(task_id)},
        config=graph_config(task_id),
        context=PlanningRuntimeContext(adapter, FakeProvider()),
    )

    assert result["__interrupt__"]
    assert adapter.decisions == []
    assert GRAPH_VERSION == "planning-graph-v2"


@pytest.mark.asyncio
async def test_approval_graph_resumes_approve_exactly_once() -> None:
    task_id = uuid4()
    decision_id = uuid4()
    adapter = ApprovalAdapter()
    graph = build_planning_graph(InMemorySaver(), approval_enabled=True)
    context = PlanningRuntimeContext(adapter, FakeProvider())
    await graph.ainvoke(
        {"task_id": str(task_id)}, config=graph_config(task_id), context=context
    )

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


@pytest.mark.asyncio
async def test_request_changes_persists_v2_and_interrupts_again() -> None:
    task_id = uuid4()
    decision_id = uuid4()
    adapter = ApprovalAdapter()
    provider = FakeProvider()
    graph = build_planning_graph(InMemorySaver(), approval_enabled=True)
    context = PlanningRuntimeContext(adapter, provider)
    await graph.ainvoke(
        {"task_id": str(task_id)}, config=graph_config(task_id), context=context
    )

    result = await graph.ainvoke(
        Command(
            resume={
                "decision_id": str(decision_id),
                "action": "request_changes",
                "comment": "Add focused coverage.",
            }
        ),
        config=graph_config(task_id),
        context=context,
    )

    assert result["__interrupt__"]
    assert result["plan_version"] == 2
    assert adapter.revisions == [(decision_id, "Add focused coverage.")]
    assert provider.calls[-1] == "create_plan"
