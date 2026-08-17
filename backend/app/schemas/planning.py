from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Sequence, Set
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningDecisionAction(str, Enum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


class PlanningDecisionCreate(StrictModel):
    action: PlanningDecisionAction
    expected_plan_version: int = Field(ge=1, le=5)
    idempotency_key: UUID
    comment: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_comment(self):
        if self.comment is not None:
            self.comment = self.comment.strip() or None
        if self.action != PlanningDecisionAction.APPROVE and not self.comment:
            raise ValueError("comment is required for this action")
        return self


class PlanningDecisionResponse(StrictModel):
    decision_id: UUID
    task_id: UUID
    action: PlanningDecisionAction
    status: Literal["pending", "applied", "failed"]
    plan_version: int = Field(ge=1, le=5)
    task_status: str
    comment: Optional[str]
    created_at: datetime
    applied_at: Optional[datetime]


class PlanningDecisionHistoryItem(StrictModel):
    decision_id: UUID
    action: PlanningDecisionAction
    status: Literal["pending", "applied", "failed"]
    plan_version: int = Field(ge=1, le=5)
    comment: Optional[str]
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    created_at: datetime
    applied_at: Optional[datetime]


class EvidenceItem(StrictModel):
    rank: int = Field(ge=1, le=10)
    path: str = Field(min_length=1, max_length=4096)
    symbol: Optional[str] = Field(default=None, max_length=2048)
    kind: str = Field(min_length=1, max_length=32)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    snippet: str = Field(min_length=1, max_length=3000)
    matched_channels: List[str] = Field(min_length=1, max_length=3)


class EvidenceStatement(StrictModel):
    description: str = Field(min_length=1, max_length=1000)
    evidence_ranks: List[int] = Field(min_length=1, max_length=10)


class AcceptanceCriterion(EvidenceStatement):
    id: str = Field(min_length=1, max_length=32)


class AffectedArea(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    symbol: Optional[str] = Field(default=None, max_length=2048)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_ranks: List[int] = Field(min_length=1, max_length=10)


class AnalysisRisk(StrictModel):
    description: str = Field(min_length=1, max_length=1000)
    mitigation: str = Field(min_length=1, max_length=1000)
    evidence_ranks: List[int] = Field(min_length=1, max_length=10)


class RequirementAnalysisDraft(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    acceptance_criteria: List[AcceptanceCriterion] = Field(
        min_length=1, max_length=10
    )
    constraints: List[EvidenceStatement] = Field(max_length=10)
    assumptions: List[EvidenceStatement] = Field(max_length=10)
    affected_areas: List[AffectedArea] = Field(min_length=1, max_length=10)
    risks: List[AnalysisRisk] = Field(max_length=10)


class PlanStep(StrictModel):
    order: int = Field(ge=1, le=12)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1500)
    paths: List[str] = Field(min_length=1, max_length=10)
    symbols: List[str] = Field(max_length=10)
    evidence_ranks: List[int] = Field(min_length=1, max_length=10)


class TestStrategyItem(StrictModel):
    description: str = Field(min_length=1, max_length=1000)
    target_paths: List[str] = Field(min_length=1, max_length=10)
    evidence_ranks: List[int] = Field(min_length=1, max_length=10)


class ImplementationPlanDraft(StrictModel):
    steps: List[PlanStep] = Field(min_length=1, max_length=12)
    test_strategy: List[TestStrategyItem] = Field(min_length=1, max_length=10)
    risk_notes: List[str] = Field(max_length=10)


class PlanningRunMetadata(StrictModel):
    id: UUID
    graph_version: str
    provider: str
    model: str
    analysis_prompt_version: str
    plan_prompt_version: str
    evidence_count: int
    evidence_sha256: str = Field(min_length=64, max_length=64)
    evidence_truncated: bool
    created_at: datetime


class PlanningAnalysis(RequirementAnalysisDraft):
    pass


class PlanningPlan(ImplementationPlanDraft):
    version: int
    status: Literal["proposed", "approved", "rejected", "superseded"]
    plan_id: Optional[UUID] = None
    supersedes_plan_id: Optional[UUID] = None
    revision_feedback: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class PlanningResponse(StrictModel):
    task_id: UUID
    commit_sha: str
    run: PlanningRunMetadata
    analysis: PlanningAnalysis
    plan: PlanningPlan
    decisions: List[PlanningDecisionHistoryItem] = Field(
        default_factory=list, max_length=20
    )


class PlanningEvidenceInvalidError(Exception):
    pass


def validate_planning_outputs(
    analysis: RequirementAnalysisDraft,
    plan: ImplementationPlanDraft,
    evidence: Sequence[EvidenceItem],
) -> None:
    by_rank = _evidence_by_rank(evidence)
    _validate_analysis_references(analysis, by_rank)
    _validate_plan_references(plan, by_rank)
    expected_order = list(range(1, len(plan.steps) + 1))
    if [step.order for step in plan.steps] != expected_order:
        raise PlanningEvidenceInvalidError("plan order must be contiguous")
    if _contains_implementation_content(analysis.model_dump()) or (
        _contains_implementation_content(plan.model_dump())
    ):
        raise PlanningEvidenceInvalidError("implementation content is forbidden")


def _evidence_by_rank(
    evidence: Sequence[EvidenceItem],
) -> Dict[int, EvidenceItem]:
    by_rank = {item.rank: item for item in evidence}
    if not evidence or len(by_rank) != len(evidence):
        raise PlanningEvidenceInvalidError("evidence ranks must be unique")
    return by_rank


def _require_ranks(
    ranks: Sequence[int], by_rank: Dict[int, EvidenceItem]
) -> List[EvidenceItem]:
    if any(rank not in by_rank for rank in ranks):
        raise PlanningEvidenceInvalidError("unknown evidence rank")
    return [by_rank[rank] for rank in ranks]


def _validate_analysis_references(
    analysis: RequirementAnalysisDraft,
    by_rank: Dict[int, EvidenceItem],
) -> None:
    referenced = [
        *analysis.acceptance_criteria,
        *analysis.constraints,
        *analysis.assumptions,
        *analysis.risks,
    ]
    for item in referenced:
        _require_ranks(item.evidence_ranks, by_rank)
    for area in analysis.affected_areas:
        items = _require_ranks(area.evidence_ranks, by_rank)
        if area.path not in {item.path for item in items}:
            raise PlanningEvidenceInvalidError("analysis path is not evidenced")
        if area.symbol and area.symbol not in _symbols(items):
            raise PlanningEvidenceInvalidError("analysis symbol is not evidenced")


def _validate_plan_references(
    plan: ImplementationPlanDraft,
    by_rank: Dict[int, EvidenceItem],
) -> None:
    for step in plan.steps:
        items = _require_ranks(step.evidence_ranks, by_rank)
        _require_paths(step.paths, items)
        if not set(step.symbols).issubset(_symbols(items)):
            raise PlanningEvidenceInvalidError("plan symbol is not evidenced")
    for strategy in plan.test_strategy:
        items = _require_ranks(strategy.evidence_ranks, by_rank)
        _require_paths(strategy.target_paths, items)


def _require_paths(paths: Sequence[str], items: Sequence[EvidenceItem]) -> None:
    if not set(paths).issubset({item.path for item in items}):
        raise PlanningEvidenceInvalidError("plan path is not evidenced")


def _symbols(items: Sequence[EvidenceItem]) -> Set[str]:
    return {item.symbol for item in items if item.symbol is not None}


def _contains_implementation_content(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        markers = ("```", "diff --git", "@@ ", "+++ b/", "--- a/")
        return any(marker in lowered for marker in markers)
    if isinstance(value, dict):
        return any(_contains_implementation_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_implementation_content(item) for item in value)
    return False
