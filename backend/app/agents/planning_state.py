from dataclasses import dataclass
from typing import Any, Dict, List, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

from app.llms.base import ChatModelProvider
from app.schemas.planning import (
    EvidenceItem,
    ImplementationPlanDraft,
    RequirementAnalysisDraft,
)


class PlanningState(TypedDict, total=False):
    task_id: str
    issue: str
    commit_sha: str
    retrieval_run_id: str
    evidence: List[Dict[str, Any]]
    evidence_sha256: str
    evidence_truncated: bool
    analysis: Dict[str, Any]
    plan: Dict[str, Any]
    planning_run_id: str
    plan_version: int
    decision: Dict[str, Any]


class PlanningEvidenceBundle(BaseModel):
    task_id: UUID
    issue: str = Field(min_length=1, max_length=20_000)
    commit_sha: str = Field(min_length=40, max_length=40)
    retrieval_run_id: UUID
    evidence_sha256: str = Field(min_length=64, max_length=64)
    evidence_truncated: bool
    evidence: List[EvidenceItem] = Field(min_length=1, max_length=10)

    model_config = ConfigDict(extra="forbid")


class PlanningGraphAdapter(Protocol):
    async def load_evidence(self, task_id: UUID) -> PlanningEvidenceBundle:
        ...

    async def persist_plan(
        self,
        bundle: PlanningEvidenceBundle,
        analysis: RequirementAnalysisDraft,
        plan: ImplementationPlanDraft,
    ) -> UUID:
        ...

    async def apply_decision(self, decision_id: UUID, action: str) -> None:
        ...

    async def persist_revision(
        self,
        decision_id: UUID,
        bundle: PlanningEvidenceBundle,
        plan: ImplementationPlanDraft,
        feedback: str,
    ) -> int:
        ...


@dataclass(frozen=True)
class PlanningRuntimeContext:
    adapter: PlanningGraphAdapter
    provider: ChatModelProvider
