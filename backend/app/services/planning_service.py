import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence
from uuid import UUID

from langgraph.types import Command

from app.checkpoints.postgres import CheckpointerUnavailableError
from app.agents.planning_graph import (
    ANALYSIS_PROMPT_VERSION,
    GRAPH_VERSION,
    LEGACY_GRAPH_VERSION,
    PLAN_PROMPT_VERSION,
    build_planning_graph,
)
from app.agents.planning_state import (
    PlanningEvidenceBundle,
    PlanningRuntimeContext,
)
from app.llms.base import ChatModelProvider
from app.llms.ollama import LlmInvalidResponseError, LlmUnavailableError
from app.schemas.planning import (
    EvidenceItem,
    ImplementationPlanDraft,
    PlanningEvidenceInvalidError,
    PlanningResponse,
    PlanningDecisionCreate,
    PlanningDecisionResponse,
    PlanningDecisionAction,
    RequirementAnalysisDraft,
)
from app.schemas.task import TaskStatus
from app.services.git_client import GitClient
from app.services.repository_service import (
    WorkspaceInconsistentError,
    verify_workspace,
)
from app.services.task_service import DatabaseUnavailableError
from app.services.workspace import WorkspaceManager


FAILURE_MESSAGES = {
    "LLM_UNAVAILABLE": "本地规划模型暂时不可用",
    "LLM_INVALID_RESPONSE": "本地规划模型返回了不合法的数据",
    "PLANNING_CONTEXT_LIMIT_EXCEEDED": "规划证据超过允许的上下文限制",
    "PLANNING_EVIDENCE_INVALID": "规划结果引用了无效的代码证据",
    "WORKSPACE_INCONSISTENT": "仓库工作区与任务快照不一致",
    "PLANNING_FAILED": "需求分析和实施计划生成失败",
}


class PlanningNotReadyError(Exception):
    pass


class PlanningContextLimitError(Exception):
    pass


class ApprovalWorkflowDisabledError(Exception):
    pass


class PlanningConflictError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PlanningRecoveryBlockedError(Exception):
    pass


@dataclass(frozen=True)
class PlanningLimits:
    evidence_limit: int
    max_snippet_characters: int
    max_evidence_characters: int


@dataclass(frozen=True)
class PlanningEvidenceRecord:
    rank: int
    path: str
    symbol: Optional[str]
    kind: str
    start_line: int
    end_line: int
    content: str
    matched_channels: Sequence[str]


@dataclass(frozen=True)
class PlanningContext:
    task_id: UUID
    issue: str
    status: str
    snapshot_sha: str
    index_sha: str
    retrieval_run_id: UUID
    retrieval_sha: str
    evidence: Sequence[PlanningEvidenceRecord]


class PlanningStore(Protocol):
    async def load_context(self, task_id: UUID) -> PlanningContext:
        ...

    async def persist_planning(
        self,
        bundle: PlanningEvidenceBundle,
        analysis: RequirementAnalysisDraft,
        plan: ImplementationPlanDraft,
        provider: str,
        model: str,
        graph_version: str = GRAPH_VERSION,
    ) -> UUID:
        ...

    async def load_planning(self, task_id: UUID) -> Optional[PlanningResponse]:
        ...

    async def set_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> None:
        ...

    async def create_decision(
        self, task_id: UUID, payload: PlanningDecisionCreate
    ) -> PlanningDecisionResponse:
        ...

    async def load_decision(
        self, decision_id: UUID
    ) -> PlanningDecisionResponse:
        ...

    async def apply_terminal_decision(
        self, decision_id: UUID, action: str
    ) -> None:
        ...

    async def persist_revision(
        self,
        decision_id: UUID,
        bundle: PlanningEvidenceBundle,
        plan: ImplementationPlanDraft,
        feedback: str,
    ) -> int:
        ...

    async def load_pending_decision_ids(self, limit: int) -> list[UUID]:
        ...

    async def load_recoverable_task_ids(self, limit: int) -> list[UUID]:
        ...

    async def fail_decision(
        self,
        decision_id: UUID,
        task_status: TaskStatus,
        failure_code: str,
        failure_message: str,
    ) -> None:
        ...


class PlanningService:
    def __init__(
        self,
        store: PlanningStore,
        git_client: GitClient,
        workspace: WorkspaceManager,
        provider: ChatModelProvider,
        graph: object,
        limits: PlanningLimits,
        checkpoint_factory: object | None = None,
        approval_enabled: bool = False,
        revision_limit: int = 5,
    ) -> None:
        self._store = store
        self._git = git_client
        self._workspace = workspace
        self._provider = provider
        self._graph = graph
        self._limits = limits
        self._checkpoint_factory = checkpoint_factory
        self._approval_enabled = approval_enabled
        self._revision_limit = revision_limit

    async def plan_task(self, task_id: UUID) -> None:
        try:
            context = await self._store.load_context(task_id)
            if context.status != TaskStatus.ANALYZING:
                return
            await self._invoke_planning(task_id)
        except DatabaseUnavailableError:
            raise
        except CheckpointerUnavailableError:
            raise
        except PlanningRecoveryBlockedError:
            await self._store.set_status(
                task_id,
                TaskStatus.RECOVERY_BLOCKED,
                failure_code="WORKSPACE_INCONSISTENT",
                failure_message=FAILURE_MESSAGES["WORKSPACE_INCONSISTENT"],
            )
        except Exception as error:
            await self._fail_task(task_id, error)

    async def load_evidence(self, task_id: UUID) -> PlanningEvidenceBundle:
        context = await self._store.load_context(task_id)
        allowed = {
            TaskStatus.ANALYZING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.DECISION_PENDING,
            TaskStatus.REVISING,
        }
        if context.status not in allowed:
            raise WorkspaceInconsistentError()
        _require_matching_commits(context)
        await self._verify_workspace(task_id, context.snapshot_sha)
        return _evidence_bundle(context, self._limits)

    async def persist_plan(
        self,
        bundle: PlanningEvidenceBundle,
        analysis: RequirementAnalysisDraft,
        plan: ImplementationPlanDraft,
    ) -> UUID:
        return await self._store.persist_planning(
            bundle,
            analysis,
            plan,
            self._provider.name,
            self._provider.model,
            GRAPH_VERSION if self._approval_enabled else LEGACY_GRAPH_VERSION,
        )

    async def submit_decision(
        self, task_id: UUID, payload: PlanningDecisionCreate
    ) -> PlanningDecisionResponse:
        if not self._approval_enabled:
            raise ApprovalWorkflowDisabledError()
        planning = await self.get_planning(task_id)
        if (
            payload.action == PlanningDecisionAction.REQUEST_CHANGES
            and planning.plan.version >= self._revision_limit
        ):
            raise PlanningConflictError(
                "PLAN_REVISION_LIMIT", "计划修改次数已达到上限"
            )
        return await self._store.create_decision(task_id, payload)

    async def process_decision(self, decision_id: UUID) -> None:
        decision = await self._store.load_decision(decision_id)
        if decision.status != "pending":
            return
        try:
            planning = await self.get_planning(decision.task_id)
            _require_compatible_planning_run(planning)
            bundle = await self.load_evidence(decision.task_id)
            if bundle.evidence_sha256 != planning.run.evidence_sha256:
                raise WorkspaceInconsistentError()
            if decision.action == PlanningDecisionAction.REQUEST_CHANGES:
                await self._store.set_status(
                    decision.task_id, TaskStatus.REVISING
                )
            await self._resume_decision(decision, planning, bundle)
        except WorkspaceInconsistentError:
            await self._store.fail_decision(
                decision_id,
                TaskStatus.RECOVERY_BLOCKED,
                "WORKSPACE_INCONSISTENT",
                FAILURE_MESSAGES["WORKSPACE_INCONSISTENT"],
            )
        except (
            LlmUnavailableError,
            LlmInvalidResponseError,
            PlanningEvidenceInvalidError,
            PlanningContextLimitError,
        ) as error:
            code = _failure_code(error)
            await self._store.fail_decision(
                decision_id,
                TaskStatus.WAITING_APPROVAL,
                code,
                FAILURE_MESSAGES[code],
            )

    async def apply_decision(self, decision_id: UUID, action: str) -> None:
        await self._store.apply_terminal_decision(decision_id, action)

    async def persist_revision(
        self,
        decision_id: UUID,
        bundle: PlanningEvidenceBundle,
        plan: ImplementationPlanDraft,
        feedback: str,
    ) -> int:
        return await self._store.persist_revision(
            decision_id, bundle, plan, feedback
        )

    async def get_planning(self, task_id: UUID) -> PlanningResponse:
        response = await self._store.load_planning(task_id)
        if response is None:
            raise PlanningNotReadyError()
        context = await self._store.load_context(task_id)
        _require_matching_commits(context)
        if response.commit_sha != context.snapshot_sha:
            raise WorkspaceInconsistentError()
        await self._verify_workspace(task_id, context.snapshot_sha)
        return response

    async def _verify_workspace(self, task_id: UUID, commit_sha: str) -> None:
        repository = self._workspace.repository_path(task_id)
        await verify_workspace(self._git, repository, commit_sha)

    async def _invoke_planning(self, task_id: UUID) -> None:
        context = PlanningRuntimeContext(self, self._provider)
        if not self._approval_enabled:
            await self._graph.ainvoke(
                {"task_id": str(task_id)},
                context=context,
                config={"recursion_limit": 8},
            )
            return
        if self._checkpoint_factory is None:
            raise ApprovalWorkflowDisabledError()
        async with self._checkpoint_factory.saver() as saver:
            graph = build_planning_graph(saver, approval_enabled=True)
            config = _graph_config(task_id)
            checkpoint = await saver.aget_tuple(config)
            if checkpoint is None:
                await graph.ainvoke(
                    {"task_id": str(task_id)}, context=context, config=config
                )
                return
            try:
                bundle = await self.load_evidence(task_id)
                _require_checkpoint_evidence(checkpoint, bundle)
            except WorkspaceInconsistentError as error:
                raise PlanningRecoveryBlockedError() from error
            await graph.ainvoke(None, context=context, config=config)

    async def _resume_decision(
        self,
        decision: PlanningDecisionResponse,
        planning: PlanningResponse,
        bundle: PlanningEvidenceBundle,
    ) -> None:
        if self._checkpoint_factory is None:
            raise ApprovalWorkflowDisabledError()
        async with self._checkpoint_factory.saver() as saver:
            graph = build_planning_graph(saver, approval_enabled=True)
            config = _graph_config(decision.task_id)
            context = PlanningRuntimeContext(self, self._provider)
            checkpoint = await saver.aget_tuple(config)
            if checkpoint is None:
                await _bootstrap_checkpoint(
                    graph, config, planning, bundle, context
                )
            else:
                _require_checkpoint_plan(checkpoint, planning, bundle)
            command = Command(
                resume={
                    "decision_id": str(decision.decision_id),
                    "action": decision.action.value,
                    "comment": decision.comment,
                }
            )
            await graph.ainvoke(
                command,
                context=context,
                config=config,
            )

    async def _fail_task(self, task_id: UUID, error: Exception) -> None:
        code = _failure_code(error)
        await self._store.set_status(
            task_id,
            TaskStatus.FAILED,
            failure_code=code,
            failure_message=FAILURE_MESSAGES[code],
        )


def _require_matching_commits(context: PlanningContext) -> None:
    commits = {
        context.snapshot_sha,
        context.index_sha,
        context.retrieval_sha,
    }
    if len(commits) != 1:
        raise WorkspaceInconsistentError()


def _evidence_bundle(
    context: PlanningContext, limits: PlanningLimits
) -> PlanningEvidenceBundle:
    if min(
        limits.evidence_limit,
        limits.max_snippet_characters,
        limits.max_evidence_characters,
    ) < 1:
        raise PlanningContextLimitError()
    items, truncated = _bounded_evidence(context.evidence, limits)
    if not items:
        raise PlanningContextLimitError()
    payload = [item.model_dump(mode="json") for item in items]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return PlanningEvidenceBundle(
        task_id=context.task_id,
        issue=context.issue,
        commit_sha=context.snapshot_sha,
        retrieval_run_id=context.retrieval_run_id,
        evidence_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        evidence_truncated=truncated,
        evidence=items,
    )


def _bounded_evidence(
    records: Sequence[PlanningEvidenceRecord], limits: PlanningLimits
) -> tuple[list[EvidenceItem], bool]:
    items: list[EvidenceItem] = []
    remaining = limits.max_evidence_characters
    truncated = len(records) > limits.evidence_limit
    for record in records[: limits.evidence_limit]:
        allowed = min(limits.max_snippet_characters, remaining)
        if allowed < 1:
            truncated = True
            break
        snippet = record.content[:allowed]
        truncated = truncated or len(snippet) < len(record.content)
        items.append(_evidence_item(record, snippet))
        remaining -= len(snippet)
    return items, truncated


def _evidence_item(
    record: PlanningEvidenceRecord, snippet: str
) -> EvidenceItem:
    return EvidenceItem(
        rank=record.rank,
        path=record.path,
        symbol=record.symbol,
        kind=record.kind,
        start_line=record.start_line,
        end_line=record.end_line,
        snippet=snippet,
        matched_channels=list(record.matched_channels),
    )


def _failure_code(error: Exception) -> str:
    if isinstance(error, LlmUnavailableError):
        return "LLM_UNAVAILABLE"
    if isinstance(error, LlmInvalidResponseError):
        return "LLM_INVALID_RESPONSE"
    if isinstance(error, PlanningContextLimitError):
        return "PLANNING_CONTEXT_LIMIT_EXCEEDED"
    if isinstance(error, PlanningEvidenceInvalidError):
        return "PLANNING_EVIDENCE_INVALID"
    if isinstance(error, WorkspaceInconsistentError):
        return "WORKSPACE_INCONSISTENT"
    return "PLANNING_FAILED"


def planning_versions(
    graph_version: str = GRAPH_VERSION,
) -> tuple[str, str, str]:
    return graph_version, ANALYSIS_PROMPT_VERSION, PLAN_PROMPT_VERSION


def _require_compatible_planning_run(planning: PlanningResponse) -> None:
    run = planning.run
    valid = (
        run.graph_version in {GRAPH_VERSION, LEGACY_GRAPH_VERSION}
        and run.analysis_prompt_version == ANALYSIS_PROMPT_VERSION
        and run.plan_prompt_version == PLAN_PROMPT_VERSION
    )
    if not valid:
        raise WorkspaceInconsistentError()


def _require_checkpoint_evidence(
    checkpoint, bundle: PlanningEvidenceBundle
) -> None:
    values = checkpoint.checkpoint.get("channel_values", {})
    expected = values.get("evidence_sha256")
    if expected is not None and expected != bundle.evidence_sha256:
        raise WorkspaceInconsistentError()
    commit = values.get("commit_sha")
    if commit is not None and commit != bundle.commit_sha:
        raise WorkspaceInconsistentError()


def _require_checkpoint_plan(
    checkpoint,
    planning: PlanningResponse,
    bundle: PlanningEvidenceBundle,
) -> None:
    _require_checkpoint_evidence(checkpoint, bundle)
    values = checkpoint.checkpoint.get("channel_values", {})
    if (
        values.get("planning_run_id") != str(planning.run.id)
        or values.get("plan_version") != planning.plan.version
    ):
        raise WorkspaceInconsistentError()


def _graph_config(task_id: UUID) -> dict:
    return {
        "configurable": {
            "thread_id": str(task_id),
            "checkpoint_ns": "",
        },
        "recursion_limit": 24,
    }


async def _bootstrap_checkpoint(
    graph,
    config: dict,
    planning: PlanningResponse,
    bundle: PlanningEvidenceBundle,
    context: PlanningRuntimeContext,
) -> None:
    plan = ImplementationPlanDraft.model_validate(
        planning.plan.model_dump(
            exclude={
                "version",
                "status",
                "plan_id",
                "supersedes_plan_id",
                "revision_feedback",
                "created_at",
                "decided_at",
            }
        )
    )
    state = {
        "task_id": str(bundle.task_id),
        "issue": bundle.issue,
        "commit_sha": bundle.commit_sha,
        "retrieval_run_id": str(bundle.retrieval_run_id),
        "evidence": [item.model_dump(mode="json") for item in bundle.evidence],
        "evidence_sha256": bundle.evidence_sha256,
        "evidence_truncated": bundle.evidence_truncated,
        "analysis": planning.analysis.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "planning_run_id": str(planning.run.id),
        "plan_version": planning.plan.version,
    }
    await graph.aupdate_state(config, state, as_node="persist_plan")
    await graph.ainvoke(
        None,
        config=config,
        context=context,
    )
