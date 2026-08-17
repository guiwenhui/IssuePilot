from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.planning import (
    AcceptanceCriterion,
    AffectedArea,
    AnalysisRisk,
    EvidenceItem,
    ImplementationPlanDraft,
    PlanStep,
    PlanningAnalysis,
    PlanningEvidenceInvalidError,
    PlanningPlan,
    PlanningResponse,
    PlanningRunMetadata,
    RequirementAnalysisDraft,
    TestStrategyItem as StrategyItem,
    validate_planning_outputs,
)


def evidence() -> list[EvidenceItem]:
    return [
        EvidenceItem(
            rank=1,
            path="src/markupsafe/__init__.py",
            symbol="escape_silent",
            kind="function",
            start_line=48,
            end_line=61,
            snippet="def escape_silent(value):\n    return escape(value)",
            matched_channels=["keyword", "symbol", "vector"],
        ),
        EvidenceItem(
            rank=2,
            path="tests/test_markupsafe.py",
            symbol="test_escape_silent",
            kind="function",
            start_line=10,
            end_line=14,
            snippet="def test_escape_silent():\n    assert escape_silent(None) == ''",
            matched_channels=["keyword", "vector"],
        ),
    ]


def analysis() -> RequirementAnalysisDraft:
    return RequirementAnalysisDraft(
        summary="Treat None as an empty value while preserving existing escaping.",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC1",
                description="None produces an empty markup value.",
                evidence_ranks=[1],
            )
        ],
        constraints=[],
        assumptions=[],
        affected_areas=[
            AffectedArea(
                path="src/markupsafe/__init__.py",
                symbol="escape_silent",
                reason="The nullable escaping behavior lives here.",
                evidence_ranks=[1],
            )
        ],
        risks=[
            AnalysisRisk(
                description="Other values must preserve existing behavior.",
                mitigation="Add a focused regression test.",
                evidence_ranks=[1, 2],
            )
        ],
    )


def plan() -> ImplementationPlanDraft:
    return ImplementationPlanDraft(
        steps=[
            PlanStep(
                order=1,
                title="Adjust nullable escaping",
                description="Update the existing guard without changing other values.",
                paths=["src/markupsafe/__init__.py"],
                symbols=["escape_silent"],
                evidence_ranks=[1],
            ),
            PlanStep(
                order=2,
                title="Add regression coverage",
                description="Cover None and a representative non-null value.",
                paths=["tests/test_markupsafe.py"],
                symbols=["test_escape_silent"],
                evidence_ranks=[2],
            ),
        ],
        test_strategy=[
            StrategyItem(
                description="Run the focused escaping tests.",
                target_paths=["tests/test_markupsafe.py"],
                evidence_ranks=[2],
            )
        ],
        risk_notes=["Do not change escaping for non-null values."],
    )


def test_planning_drafts_forbid_unknown_fields_and_empty_collections() -> None:
    with pytest.raises(ValidationError):
        RequirementAnalysisDraft.model_validate(
            {"summary": "summary", "acceptance_criteria": [], "affected_areas": []}
        )
    with pytest.raises(ValidationError):
        ImplementationPlanDraft.model_validate(
            {"steps": [], "test_strategy": [], "risk_notes": [], "extra": True}
        )


def test_validator_accepts_only_real_rank_path_and_symbol_references() -> None:
    validate_planning_outputs(analysis(), plan(), evidence())

    invalid = plan().model_copy(deep=True)
    invalid.steps[0].paths = ["src/invented.py"]
    with pytest.raises(PlanningEvidenceInvalidError, match="path"):
        validate_planning_outputs(analysis(), invalid, evidence())

    invalid = plan().model_copy(deep=True)
    invalid.steps[0].evidence_ranks = [99]
    with pytest.raises(PlanningEvidenceInvalidError, match="rank"):
        validate_planning_outputs(analysis(), invalid, evidence())


def test_validator_rejects_patch_or_fenced_code_content() -> None:
    invalid = plan().model_copy(deep=True)
    invalid.steps[0].description = "```python\nreturn ''\n```"
    with pytest.raises(PlanningEvidenceInvalidError, match="implementation content"):
        validate_planning_outputs(analysis(), invalid, evidence())

    invalid = analysis().model_copy(deep=True)
    invalid.summary = "diff --git a/file.py b/file.py"
    with pytest.raises(PlanningEvidenceInvalidError, match="implementation content"):
        validate_planning_outputs(invalid, plan(), evidence())


def test_validator_requires_contiguous_plan_order() -> None:
    invalid = plan().model_copy(deep=True)
    invalid.steps[1].order = 3
    with pytest.raises(PlanningEvidenceInvalidError, match="contiguous"):
        validate_planning_outputs(analysis(), invalid, evidence())


def test_planning_response_has_stable_nested_contract() -> None:
    now = datetime.now(timezone.utc)
    response = PlanningResponse(
        task_id=uuid4(),
        commit_sha="a" * 40,
        run=PlanningRunMetadata(
            id=uuid4(),
            graph_version="planning-graph-v1",
            provider="ollama",
            model="qwen3:8b",
            analysis_prompt_version="analysis-v1",
            plan_prompt_version="plan-v1",
            evidence_count=2,
            evidence_truncated=False,
            created_at=now,
        ),
        analysis=PlanningAnalysis.model_validate(analysis().model_dump()),
        plan=PlanningPlan(
            version=1,
            status="proposed",
            **plan().model_dump(),
            created_at=now,
        ),
    )

    payload = response.model_dump(mode="json")
    assert payload["run"]["model"] == "qwen3:8b"
    assert payload["analysis"]["acceptance_criteria"][0]["evidence_ranks"] == [1]
    assert payload["plan"]["steps"][1]["paths"] == ["tests/test_markupsafe.py"]
