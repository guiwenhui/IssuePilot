import hashlib
import os
from uuid import UUID, uuid4

import pytest

from app.agents.implementation_graph import build_implementation_graph
from app.agents.implementation_state import (
    ImplementationBundle,
    ImplementationRuntimeContext,
    ImplementationSourceFile,
)
from app.llms.ollama import OllamaChatProvider
from app.schemas.implementation import PatchDraft


SOURCE = "def add(left: int, right: int) -> int:\n    return left - right\n"


class EvaluationAdapter:
    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        self.draft: PatchDraft | None = None

    async def load_bundle(self, run_id: UUID) -> ImplementationBundle:
        assert run_id == self.run_id
        return ImplementationBundle(
            implementation_run_id=run_id,
            issue="Fix add so it returns the sum of left and right.",
            commit_sha="b" * 40,
            plan={
                "goal": "Correct the arithmetic implementation",
                "steps": [
                    {
                        "order": 1,
                        "description": "Return left plus right",
                        "paths": ["calculator.py"],
                    }
                ],
            },
            files=[
                ImplementationSourceFile(
                    path="calculator.py",
                    sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
                    content=SOURCE,
                )
            ],
        )

    async def apply_patch(self, run_id: UUID, draft: PatchDraft) -> str:
        assert run_id == self.run_id
        self.draft = draft
        return "c" * 64

    async def run_test(self, test_run_id: UUID) -> None:
        raise AssertionError("live evaluation must pause before test execution")


@pytest.mark.ollama
@pytest.mark.asyncio
async def test_qwen3_8b_live_implementation_is_a_valid_file_replacement() -> None:
    if os.environ.get("RUN_OLLAMA_LIVE") != "1":
        pytest.skip("set RUN_OLLAMA_LIVE=1 for the approved local model")
    run_id = uuid4()
    adapter = EvaluationAdapter(run_id)
    provider = OllamaChatProvider(
        "http://127.0.0.1:11434",
            "qwen3:8b",
            300,
            32_768,
            16_384,
            262_144,
        )

    result = await build_implementation_graph().ainvoke(
        {"implementation_run_id": str(run_id)},
        context=ImplementationRuntimeContext(adapter, provider),
        config={"recursion_limit": 8},
    )

    assert "__interrupt__" in result
    assert adapter.draft is not None
    replacement = adapter.draft.replacements[0]
    assert replacement.path == "calculator.py"
    assert replacement.original_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert "return left + right" in replacement.content
