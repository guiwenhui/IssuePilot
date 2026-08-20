from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.implementation_graph import (
    GRAPH_VERSION,
    build_implementation_graph,
)
from app.agents.implementation_state import (
    ImplementationBundle,
    ImplementationRuntimeContext,
    ImplementationSourceFile,
)
from app.schemas.implementation import PatchDraft


class FakeProvider:
    name = "fake"
    model = "fake-v1"

    async def generate(self, messages, response_model):
        return response_model.model_validate(
            {
                "replacements": [
                    {
                        "path": "example.py",
                        "original_sha256": "a" * 64,
                        "content": "value = 2\n",
                    }
                ]
            }
        )


class FakeAdapter:
    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        self.tests = []
        self.patches: list[PatchDraft] = []

    async def load_bundle(self, run_id: UUID) -> ImplementationBundle:
        assert run_id == self.run_id
        return ImplementationBundle(
            implementation_run_id=run_id,
            issue="Change value",
            commit_sha="b" * 40,
            plan={"steps": []},
            files=[
                ImplementationSourceFile(
                    path="example.py", sha256="a" * 64, content="value = 1\n"
                )
            ],
        )

    async def apply_patch(self, run_id: UUID, draft: PatchDraft) -> str:
        self.patches.append(draft)
        return "c" * 64

    async def run_test(self, test_run_id: UUID) -> None:
        self.tests.append(test_run_id)


def config(run_id: UUID) -> dict:
    return {
        "configurable": {"thread_id": f"implementation:{run_id}"},
        "recursion_limit": 12,
    }


@pytest.mark.asyncio
async def test_graph_interrupts_after_patch_before_tests() -> None:
    run_id = uuid4()
    adapter = FakeAdapter(run_id)
    graph = build_implementation_graph(InMemorySaver())

    result = await graph.ainvoke(
        {"implementation_run_id": str(run_id)},
        config=config(run_id),
        context=ImplementationRuntimeContext(adapter, FakeProvider()),
    )

    assert result["__interrupt__"]
    assert result["patch_sha256"] == "c" * 64
    assert adapter.patches
    assert adapter.tests == []
    assert GRAPH_VERSION == "implementation-graph-v1"


@pytest.mark.asyncio
async def test_graph_resumes_only_explicit_test_run() -> None:
    run_id = uuid4()
    test_id = uuid4()
    adapter = FakeAdapter(run_id)
    graph = build_implementation_graph(InMemorySaver())
    runtime = ImplementationRuntimeContext(adapter, FakeProvider())
    await graph.ainvoke(
        {"implementation_run_id": str(run_id)},
        config=config(run_id),
        context=runtime,
    )

    await graph.ainvoke(
        Command(
            resume={
                "action": "run_tests",
                "test_run_id": str(test_id),
                "patch_sha256": "c" * 64,
            }
        ),
        config=config(run_id),
        context=runtime,
    )

    assert adapter.tests == [test_id]
