import hashlib
import json
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence
from uuid import UUID

from app.agents.planning_graph import (
    ANALYSIS_PROMPT_VERSION,
    GRAPH_VERSION,
    PLAN_PROMPT_VERSION,
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


class PlanningService:
    def __init__(
        self,
        store: PlanningStore,
        git_client: GitClient,
        workspace: WorkspaceManager,
        provider: ChatModelProvider,
        graph: object,
        limits: PlanningLimits,
    ) -> None:
        self._store = store
        self._git = git_client
        self._workspace = workspace
        self._provider = provider
        self._graph = graph
        self._limits = limits

    async def plan_task(self, task_id: UUID) -> None:
        try:
            context = await self._store.load_context(task_id)
            if context.status != TaskStatus.ANALYZING:
                return
            await self._graph.ainvoke(
                {"task_id": str(task_id)},
                context=PlanningRuntimeContext(self, self._provider),
                config={"recursion_limit": 8},
            )
        except DatabaseUnavailableError:
            raise
        except Exception as error:
            await self._fail_task(task_id, error)

    async def load_evidence(self, task_id: UUID) -> PlanningEvidenceBundle:
        context = await self._store.load_context(task_id)
        if context.status != TaskStatus.ANALYZING:
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


def planning_versions() -> tuple[str, str, str]:
    return GRAPH_VERSION, ANALYSIS_PROMPT_VERSION, PLAN_PROMPT_VERSION
