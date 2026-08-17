import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planning_graph import GRAPH_VERSION
from app.agents.planning_state import PlanningEvidenceBundle
from app.models.code_index import CodeIndex
from app.models.planning import (
    ImplementationPlan,
    PlanningDecision,
    PlanningRun,
    RequirementAnalysis,
)
from app.models.repository_snapshot import RepositorySnapshot
from app.models.retrieval import CodeChunk, RetrievalResult, RetrievalRun
from app.models.task import Task
from app.schemas.planning import (
    ImplementationPlanDraft,
    PlanningAnalysis,
    PlanningDecisionCreate,
    PlanningDecisionHistoryItem,
    PlanningDecisionResponse,
    PlanningPlan,
    PlanningResponse,
    PlanningRunMetadata,
    RequirementAnalysisDraft,
)
from app.schemas.task import TaskStatus
from app.services.planning_service import (
    PlanningContext,
    PlanningEvidenceRecord,
    planning_versions,
    PlanningConflictError,
)
from app.services.repository_service import WorkspaceInconsistentError
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError


class SqlPlanningStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_context(self, task_id: UUID) -> PlanningContext:
        try:
            task = await self._session.get(Task, task_id)
            if task is None:
                raise TaskNotFoundError()
            snapshot = await self._session.get(RepositorySnapshot, task_id)
            index = await self._session.get(CodeIndex, task_id)
            run = await self._session.scalar(
                select(RetrievalRun).where(RetrievalRun.task_id == task_id)
            )
            if snapshot is None or index is None or run is None:
                raise WorkspaceInconsistentError()
            evidence = await self._load_evidence(run.id)
            context = PlanningContext(
                task_id=task.id,
                issue=task.issue_text,
                status=task.status,
                snapshot_sha=snapshot.commit_sha,
                index_sha=index.commit_sha,
                retrieval_run_id=run.id,
                retrieval_sha=run.commit_sha,
                evidence=evidence,
            )
            await self._session.commit()
            return context
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def persist_planning(
        self,
        bundle: PlanningEvidenceBundle,
        analysis: RequirementAnalysisDraft,
        plan: ImplementationPlanDraft,
        provider: str,
        model: str,
        graph_version: str = GRAPH_VERSION,
    ) -> UUID:
        try:
            await self._require_current_context(bundle)
            run = _planning_run(bundle, provider, model, graph_version)
            self._session.add(run)
            await self._session.flush()
            self._session.add(_analysis_record(run.id, analysis))
            self._session.add(_plan_record(run.id, plan))
            task = await self._session.get(Task, bundle.task_id)
            if task is None:
                raise TaskNotFoundError()
            task.status = TaskStatus.WAITING_APPROVAL
            task.failure_code = None
            task.failure_message = None
            await self._session.commit()
            return run.id
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def load_planning(self, task_id: UUID) -> Optional[PlanningResponse]:
        try:
            task = await self._session.get(Task, task_id)
            if task is None:
                raise TaskNotFoundError()
            row = (
                await self._session.execute(
                    select(PlanningRun, RequirementAnalysis, ImplementationPlan)
                    .join(
                        RequirementAnalysis,
                        RequirementAnalysis.run_id == PlanningRun.id,
                    )
                    .join(
                        ImplementationPlan,
                        ImplementationPlan.run_id == PlanningRun.id,
                    )
                    .where(PlanningRun.task_id == task_id)
                    .order_by(ImplementationPlan.version.desc())
                    .limit(1)
                )
            ).first()
            if row is None:
                await self._session.commit()
                return None
            decisions = await self._load_decisions(task_id)
            response = _planning_response(task_id, *row, decisions)
            await self._session.commit()
            return response
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def create_decision(
        self, task_id: UUID, payload: PlanningDecisionCreate
    ) -> PlanningDecisionResponse:
        try:
            task = await self._lock_task(task_id)
            existing = await self._decision_by_key(
                task_id, payload.idempotency_key
            )
            if existing is not None:
                _require_same_decision(existing, payload)
                await self._session.commit()
                return _decision_response(existing, task.status)
            run, plan = await self._lock_current_plan(task_id)
            _require_submittable(task, plan, payload.expected_plan_version)
            decision = PlanningDecision(
                id=uuid.uuid4(),
                task_id=task_id,
                run_id=run.id,
                plan_id=plan.id,
                plan_version=plan.version,
                action=payload.action.value,
                comment=payload.comment,
                idempotency_key=payload.idempotency_key,
                status="pending",
            )
            self._session.add(decision)
            task.status = TaskStatus.DECISION_PENDING
            await self._session.commit()
            await self._session.refresh(decision)
            return _decision_response(decision, task.status)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def load_decision(
        self, decision_id: UUID
    ) -> PlanningDecisionResponse:
        try:
            decision = await self._session.get(PlanningDecision, decision_id)
            if decision is None:
                raise PlanningConflictError(
                    "DECISION_NOT_FOUND", "审批决定不存在"
                )
            task = await self._require_task(decision.task_id)
            await self._session.commit()
            return _decision_response(decision, task.status)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def apply_terminal_decision(
        self, decision_id: UUID, action: str
    ) -> None:
        try:
            decision, task, plan = await self._lock_decision(decision_id)
            if decision.status == "applied":
                await self._session.commit()
                return
            _require_pending_action(decision, plan, action)
            now = datetime.now(timezone.utc)
            plan.status = "approved" if action == "approve" else "rejected"
            plan.decided_at = now
            decision.status = "applied"
            decision.applied_at = now
            task.status = (
                TaskStatus.APPROVED
                if action == "approve"
                else TaskStatus.REJECTED
            )
            task.failure_code = None
            task.failure_message = None
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def persist_revision(
        self,
        decision_id: UUID,
        bundle: PlanningEvidenceBundle,
        plan: ImplementationPlanDraft,
        feedback: str,
    ) -> int:
        try:
            decision, task, previous = await self._lock_decision(decision_id)
            _require_pending_action(
                decision, previous, "request_changes"
            )
            run = await self._session.get(PlanningRun, decision.run_id)
            if run is None or not _matches_bundle(run, bundle):
                raise WorkspaceInconsistentError()
            previous.status = "superseded"
            previous.decided_at = datetime.now(timezone.utc)
            await self._session.flush()
            version = previous.version + 1
            self._session.add(
                _revision_record(run.id, previous.id, version, plan, feedback)
            )
            decision.status = "applied"
            decision.applied_at = datetime.now(timezone.utc)
            task.status = TaskStatus.WAITING_APPROVAL
            task.failure_code = None
            task.failure_message = None
            await self._session.commit()
            return version
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def load_pending_decision_ids(self, limit: int) -> list[UUID]:
        try:
            rows = (
                await self._session.scalars(
                    select(PlanningDecision.id)
                    .where(PlanningDecision.status == "pending")
                    .order_by(PlanningDecision.created_at)
                    .limit(limit)
                )
            ).all()
            await self._session.commit()
            return list(rows)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def load_recoverable_task_ids(self, limit: int) -> list[UUID]:
        try:
            rows = (
                await self._session.scalars(
                    select(Task.id)
                    .where(Task.status == TaskStatus.ANALYZING)
                    .order_by(Task.updated_at)
                    .limit(limit)
                )
            ).all()
            await self._session.commit()
            return list(rows)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def fail_decision(
        self,
        decision_id: UUID,
        task_status: TaskStatus,
        failure_code: str,
        failure_message: str,
    ) -> None:
        try:
            decision, task, _ = await self._lock_decision(decision_id)
            if decision.status != "pending":
                await self._session.commit()
                return
            decision.status = "failed"
            decision.failure_code = failure_code
            decision.failure_message = failure_message
            task.status = task_status
            task.failure_code = failure_code
            task.failure_message = failure_message
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def set_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> None:
        try:
            task = await self._session.get(Task, task_id)
            if task is None:
                raise TaskNotFoundError()
            task.status = status
            task.failure_code = failure_code
            task.failure_message = failure_message
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def _load_evidence(
        self, run_id: UUID
    ) -> list[PlanningEvidenceRecord]:
        rows = (
            await self._session.execute(
                select(RetrievalResult, CodeChunk)
                .join(CodeChunk, CodeChunk.id == RetrievalResult.chunk_id)
                .where(RetrievalResult.run_id == run_id)
                .order_by(RetrievalResult.rank)
            )
        ).all()
        return [
            PlanningEvidenceRecord(
                rank=result.rank,
                path=chunk.path,
                symbol=chunk.symbol_name,
                kind=chunk.kind,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
                matched_channels=result.matched_channels,
            )
            for result, chunk in rows
        ]

    async def _load_decisions(
        self, task_id: UUID
    ) -> list[PlanningDecisionHistoryItem]:
        rows = (
            await self._session.scalars(
                select(PlanningDecision)
                .where(PlanningDecision.task_id == task_id)
                .order_by(PlanningDecision.created_at.desc())
                .limit(20)
            )
        ).all()
        return [_decision_history(row) for row in rows]

    async def _decision_by_key(
        self, task_id: UUID, key: UUID
    ) -> Optional[PlanningDecision]:
        return await self._session.scalar(
            select(PlanningDecision).where(
                PlanningDecision.task_id == task_id,
                PlanningDecision.idempotency_key == key,
            )
        )

    async def _require_task(self, task_id: UUID) -> Task:
        task = await self._session.get(Task, task_id)
        if task is None:
            raise TaskNotFoundError()
        return task

    async def _lock_task(self, task_id: UUID) -> Task:
        task = await self._session.scalar(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        if task is None:
            raise TaskNotFoundError()
        return task

    async def _lock_current_plan(
        self, task_id: UUID
    ) -> tuple[PlanningRun, ImplementationPlan]:
        row = (
            await self._session.execute(
                select(PlanningRun, ImplementationPlan)
                .join(ImplementationPlan, ImplementationPlan.run_id == PlanningRun.id)
                .where(
                    PlanningRun.task_id == task_id,
                    ImplementationPlan.status == "proposed",
                )
                .with_for_update()
            )
        ).first()
        if row is None:
            raise PlanningConflictError("APPROVAL_NOT_READY", "没有待审批计划")
        return row[0], row[1]

    async def _lock_decision(
        self, decision_id: UUID
    ) -> tuple[PlanningDecision, Task, ImplementationPlan]:
        decision = await self._session.scalar(
            select(PlanningDecision)
            .where(PlanningDecision.id == decision_id)
            .with_for_update()
        )
        if decision is None:
            raise PlanningConflictError("DECISION_NOT_FOUND", "审批决定不存在")
        task = await self._require_task(decision.task_id)
        plan = await self._session.get(ImplementationPlan, decision.plan_id)
        if plan is None:
            raise PlanningConflictError("APPROVAL_NOT_READY", "原计划不存在")
        return decision, task, plan

    async def _require_current_context(
        self, bundle: PlanningEvidenceBundle
    ) -> None:
        task = await self._session.scalar(
            select(Task)
            .where(Task.id == bundle.task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is None:
            raise TaskNotFoundError()
        snapshot = await self._session.get(RepositorySnapshot, bundle.task_id)
        index = await self._session.get(CodeIndex, bundle.task_id)
        retrieval = await self._session.get(
            RetrievalRun, bundle.retrieval_run_id
        )
        valid = (
            task.status == TaskStatus.ANALYZING
            and snapshot is not None
            and index is not None
            and retrieval is not None
            and retrieval.task_id == bundle.task_id
            and snapshot.commit_sha == bundle.commit_sha
            and index.commit_sha == bundle.commit_sha
            and retrieval.commit_sha == bundle.commit_sha
        )
        if not valid:
            raise WorkspaceInconsistentError()


def _planning_run(
    bundle: PlanningEvidenceBundle,
    provider: str,
    model: str,
    graph_version: str,
) -> PlanningRun:
    graph, analysis_prompt, plan_prompt = planning_versions(graph_version)
    return PlanningRun(
        id=uuid.uuid4(),
        task_id=bundle.task_id,
        retrieval_run_id=bundle.retrieval_run_id,
        commit_sha=bundle.commit_sha,
        graph_version=graph,
        llm_provider=provider,
        llm_model=model,
        analysis_prompt_version=analysis_prompt,
        plan_prompt_version=plan_prompt,
        evidence_sha256=bundle.evidence_sha256,
        evidence_count=len(bundle.evidence),
        evidence_truncated=bundle.evidence_truncated,
    )


def _analysis_record(
    run_id: UUID, draft: RequirementAnalysisDraft
) -> RequirementAnalysis:
    values = draft.model_dump(mode="json")
    return RequirementAnalysis(run_id=run_id, **values)


def _plan_record(
    run_id: UUID, draft: ImplementationPlanDraft
) -> ImplementationPlan:
    values = draft.model_dump(mode="json")
    return ImplementationPlan(
        id=uuid.uuid4(),
        run_id=run_id,
        version=1,
        status="proposed",
        supersedes_plan_id=None,
        revision_feedback=None,
        **values,
    )


def _revision_record(
    run_id: UUID,
    previous_id: UUID,
    version: int,
    draft: ImplementationPlanDraft,
    feedback: str,
) -> ImplementationPlan:
    values = draft.model_dump(mode="json")
    return ImplementationPlan(
        id=uuid.uuid4(),
        run_id=run_id,
        version=version,
        status="proposed",
        supersedes_plan_id=previous_id,
        revision_feedback=feedback,
        **values,
    )


def _planning_response(
    task_id: UUID,
    run: PlanningRun,
    analysis: RequirementAnalysis,
    plan: ImplementationPlan,
    decisions: list[PlanningDecisionHistoryItem],
) -> PlanningResponse:
    return PlanningResponse(
        task_id=task_id,
        commit_sha=run.commit_sha,
        run=PlanningRunMetadata(
            id=run.id,
            graph_version=run.graph_version,
            provider=run.llm_provider,
            model=run.llm_model,
            analysis_prompt_version=run.analysis_prompt_version,
            plan_prompt_version=run.plan_prompt_version,
            evidence_count=run.evidence_count,
            evidence_sha256=run.evidence_sha256,
            evidence_truncated=run.evidence_truncated,
            created_at=run.created_at,
        ),
        analysis=PlanningAnalysis(
            summary=analysis.summary,
            acceptance_criteria=analysis.acceptance_criteria,
            constraints=analysis.constraints,
            assumptions=analysis.assumptions,
            affected_areas=analysis.affected_areas,
            risks=analysis.risks,
        ),
        plan=PlanningPlan(
            plan_id=plan.id,
            version=plan.version,
            status=plan.status,
            supersedes_plan_id=plan.supersedes_plan_id,
            revision_feedback=plan.revision_feedback,
            steps=plan.steps,
            test_strategy=plan.test_strategy,
            risk_notes=plan.risk_notes,
            created_at=plan.created_at,
            decided_at=plan.decided_at,
        ),
        decisions=decisions,
    )


def _require_same_decision(
    decision: PlanningDecision, payload: PlanningDecisionCreate
) -> None:
    same = (
        decision.action == payload.action.value
        and decision.plan_version == payload.expected_plan_version
        and decision.comment == payload.comment
    )
    if not same:
        raise PlanningConflictError(
            "IDEMPOTENCY_KEY_CONFLICT",
            "同一个幂等键不能用于不同审批内容",
        )


def _require_submittable(
    task: Task, plan: ImplementationPlan, expected_version: int
) -> None:
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise PlanningConflictError("APPROVAL_NOT_READY", "任务不在待审批状态")
    if plan.version != expected_version:
        raise PlanningConflictError(
            "PLAN_VERSION_CONFLICT", "计划版本已经变化"
        )


def _require_pending_action(
    decision: PlanningDecision, plan: ImplementationPlan, action: str
) -> None:
    if decision.status != "pending":
        raise PlanningConflictError(
            "DECISION_ALREADY_APPLIED", "审批决定已经处理"
        )
    if decision.action != action or plan.status != "proposed":
        raise PlanningConflictError("APPROVAL_NOT_READY", "审批上下文已经变化")


def _matches_bundle(
    run: PlanningRun, bundle: PlanningEvidenceBundle
) -> bool:
    return (
        run.task_id == bundle.task_id
        and run.retrieval_run_id == bundle.retrieval_run_id
        and run.commit_sha == bundle.commit_sha
        and run.evidence_sha256 == bundle.evidence_sha256
    )


def _decision_response(
    decision: PlanningDecision, task_status: str
) -> PlanningDecisionResponse:
    return PlanningDecisionResponse(
        decision_id=decision.id,
        task_id=decision.task_id,
        action=decision.action,
        status=decision.status,
        plan_version=decision.plan_version,
        task_status=task_status,
        comment=decision.comment,
        created_at=decision.created_at,
        applied_at=decision.applied_at,
    )


def _decision_history(
    decision: PlanningDecision,
) -> PlanningDecisionHistoryItem:
    return PlanningDecisionHistoryItem(
        decision_id=decision.id,
        action=decision.action,
        status=decision.status,
        plan_version=decision.plan_version,
        comment=decision.comment,
        failure_code=decision.failure_code,
        failure_message=decision.failure_message,
        created_at=decision.created_at,
        applied_at=decision.applied_at,
    )
