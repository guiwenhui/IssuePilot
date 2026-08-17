import uuid
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planning_state import PlanningEvidenceBundle
from app.models.code_index import CodeIndex
from app.models.planning import (
    ImplementationPlan,
    PlanningRun,
    RequirementAnalysis,
)
from app.models.repository_snapshot import RepositorySnapshot
from app.models.retrieval import CodeChunk, RetrievalResult, RetrievalRun
from app.models.task import Task
from app.schemas.planning import (
    ImplementationPlanDraft,
    PlanningAnalysis,
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
    ) -> UUID:
        try:
            await self._require_current_context(bundle)
            run = _planning_run(bundle, provider, model)
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
            response = _planning_response(task_id, *row)
            await self._session.commit()
            return response
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

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
    bundle: PlanningEvidenceBundle, provider: str, model: str
) -> PlanningRun:
    graph, analysis_prompt, plan_prompt = planning_versions()
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
        **values,
    )


def _planning_response(
    task_id: UUID,
    run: PlanningRun,
    analysis: RequirementAnalysis,
    plan: ImplementationPlan,
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
            version=plan.version,
            status=plan.status,
            steps=plan.steps,
            test_strategy=plan.test_strategy,
            risk_notes=plan.risk_notes,
            created_at=plan.created_at,
        ),
    )
