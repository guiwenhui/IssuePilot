import os
from uuid import UUID, uuid4

import pytest

from app.agents.planning_graph import build_planning_graph
from app.agents.planning_state import (
    PlanningEvidenceBundle,
    PlanningRuntimeContext,
)
from app.llms.ollama import OllamaChatProvider
from app.schemas.planning import (
    EvidenceItem,
    ImplementationPlanDraft,
    RequirementAnalysisDraft,
)


class MarkupSafeAdapter:
    def __init__(self) -> None:
        self.saved: tuple | None = None

    async def load_evidence(self, task_id: UUID) -> PlanningEvidenceBundle:
        return PlanningEvidenceBundle(
            task_id=task_id,
            issue=(
                "Make escape_silent return an empty Markup value for None, "
                "while preserving normal escaping for other inputs."
            ),
            commit_sha="a" * 40,
            retrieval_run_id=uuid4(),
            evidence_sha256="b" * 64,
            evidence_truncated=False,
            evidence=[
                EvidenceItem(
                    rank=1,
                    path="src/markupsafe/__init__.py",
                    symbol="escape_silent",
                    kind="function",
                    start_line=62,
                    end_line=69,
                    snippet=(
                        "def escape_silent(s: t.Any, /) -> Markup:\n"
                        "    if s is None:\n"
                        "        return Markup()\n"
                        "    return escape(s)"
                    ),
                    matched_channels=["keyword", "symbol", "vector"],
                ),
                EvidenceItem(
                    rank=2,
                    path="tests/test_markupsafe.py",
                    symbol="test_escape_silent",
                    kind="function",
                    start_line=70,
                    end_line=74,
                    snippet=(
                        "def test_escape_silent() -> None:\n"
                        "    assert escape_silent(None) == Markup()\n"
                        "    assert escape_silent('<foo>') == Markup('&lt;foo&gt;')"
                    ),
                    matched_channels=["keyword", "vector"],
                ),
            ],
        )

    async def persist_plan(
        self,
        bundle: PlanningEvidenceBundle,
        analysis: RequirementAnalysisDraft,
        plan: ImplementationPlanDraft,
    ) -> UUID:
        self.saved = bundle, analysis, plan
        return uuid4()


@pytest.mark.ollama
@pytest.mark.asyncio
async def test_qwen3_8b_live_planning_is_structured_and_evidenced() -> None:
    if os.environ.get("RUN_OLLAMA_LIVE") != "1":
        pytest.skip("set RUN_OLLAMA_LIVE=1 for the approved local model")
    adapter = MarkupSafeAdapter()
    model = os.environ.get("PLANNING_TEST_MODEL", "qwen3:8b")
    provider = OllamaChatProvider(
        "http://127.0.0.1:11434",
        model,
        180,
        16_384,
        2_048,
        65_536,
    )

    await build_planning_graph().ainvoke(
        {"task_id": str(uuid4())},
        context=PlanningRuntimeContext(adapter, provider),
        config={"recursion_limit": 8},
    )

    assert adapter.saved is not None
    _, analysis, plan = adapter.saved
    assert analysis.acceptance_criteria
    assert plan.steps
    assert {path for step in plan.steps for path in step.paths} <= {
        "src/markupsafe/__init__.py",
        "tests/test_markupsafe.py",
    }
