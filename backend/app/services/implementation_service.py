import hashlib
from pathlib import Path, PurePosixPath
from typing import Optional, Set
from uuid import UUID

from langgraph.types import Command

from app.agents.implementation_graph import (
    GRAPH_VERSION,
    PROMPT_VERSION,
    build_implementation_graph,
)
from app.agents.implementation_state import (
    ImplementationBundle,
    ImplementationRuntimeContext,
    ImplementationSourceFile,
)
from app.checkpoints.postgres import CheckpointerUnavailableError
from app.llms.base import ChatModelProvider
from app.llms.ollama import LlmInvalidResponseError, LlmUnavailableError
from app.schemas.implementation import (
    ImplementationCreate,
    ImplementationResponse,
    PatchDraft,
    TestRunCreate,
)
from app.schemas.task import TaskStatus
from app.services.git_client import GitClient, GitClientError
from app.services.implementation_store import (
    ImplementationConflictError,
    ImplementationContext,
    ImplementationNotReadyError,
    SqlImplementationStore,
)
from app.services.implementation_workspace import ImplementationWorkspace
from app.services.patch_service import (
    PatchService,
    PatchSourceChangedError,
    PatchValidationError,
)
from app.services.repository_service import (
    WorkspaceInconsistentError,
    verify_workspace,
)
from app.services.test_runner import DockerTestRunner, TestRunnerUnavailableError
from app.services.task_service import DatabaseUnavailableError
from app.services.workspace import UnsafeWorkspacePathError, WorkspaceManager


class ImplementationDisabledError(Exception):
    pass


class ImplementationScopeError(Exception):
    pass


FAILURE_MESSAGES = {
    "IMPLEMENTATION_SCOPE_INVALID": "批准计划的文件范围不适合安全实现",
    "PATCH_OUTPUT_INVALID": "本地模型生成的代码修改未通过安全校验",
    "LLM_UNAVAILABLE": "本地代码生成模型暂时不可用",
    "LLM_INVALID_RESPONSE": "本地代码生成模型返回了非法结果",
    "TEST_RUNNER_UNAVAILABLE": "安全 pytest Runner 暂时不可用",
    "WORKSPACE_INCONSISTENT": "实现记录与真实工作区不一致",
    "IMPLEMENTATION_FAILED": "本地 Patch 生成失败",
}


class ImplementationService:
    def __init__(
        self,
        store: SqlImplementationStore,
        git_client: GitClient,
        source_workspace: WorkspaceManager,
        implementation_workspace: ImplementationWorkspace,
        patch_service: PatchService,
        provider: ChatModelProvider,
        checkpoint_factory: object,
        test_runner: DockerTestRunner,
        enabled: bool,
    ) -> None:
        self._store = store
        self._git = git_client
        self._source_workspace = source_workspace
        self._implementation_workspace = implementation_workspace
        self._patch_service = patch_service
        self._provider = provider
        self._checkpoint_factory = checkpoint_factory
        self._test_runner = test_runner
        self._enabled = enabled

    async def submit_implementation(
        self, task_id: UUID, payload: ImplementationCreate
    ) -> ImplementationResponse:
        self._require_enabled()
        return await self._store.create_run(
            task_id, payload, self._provider.name, self._provider.model
        )

    async def submit_test(
        self, task_id: UUID, payload: TestRunCreate
    ) -> ImplementationResponse:
        self._require_enabled()
        return await self._store.create_test(
            task_id, payload, self._test_runner.image
        )

    async def get_implementation(self, task_id: UUID) -> ImplementationResponse:
        response = await self._store.load_response(task_id)
        if response is None:
            raise ImplementationNotReadyError()
        context = await self._store.load_context(
            response.run.implementation_run_id
        )
        await self._verify_source(context)
        if response.patch is not None:
            worktree = self._require_worktree(context)
            artifact = await self._patch_service.inspect(
                worktree, _allowed_paths(context)
            )
            if artifact.diff_sha256 != response.patch.sha256:
                raise WorkspaceInconsistentError()
        return response

    async def process_implementation(self, run_id: UUID) -> None:
        try:
            await self._invoke_initial(run_id)
        except (
            WorkspaceInconsistentError,
            UnsafeWorkspacePathError,
            PatchSourceChangedError,
        ):
            await self._store.fail(
                run_id,
                "WORKSPACE_INCONSISTENT",
                FAILURE_MESSAGES["WORKSPACE_INCONSISTENT"],
                recovery_blocked=True,
            )
        except (CheckpointerUnavailableError, DatabaseUnavailableError):
            raise
        except Exception as error:
            code = _failure_code(error)
            await self._store.fail(run_id, code, FAILURE_MESSAGES[code])

    async def process_test(self, test_id: UUID) -> None:
        context = await self._store.load_test_context(test_id)
        if context.test.status in {"passed", "failed"}:
            return
        if context.test.status == "running":
            cleanup = getattr(self._test_runner, "cleanup", None)
            try:
                if cleanup is not None:
                    await cleanup(test_id)
            except TestRunnerUnavailableError:
                await self._store.fail(
                    context.run.id,
                    "TEST_RUNNER_UNAVAILABLE",
                    "遗留测试容器无法确认已经停止",
                    recovery_blocked=True,
                )
                return
            await self._store.fail(
                context.run.id,
                "WORKSPACE_INCONSISTENT",
                "测试曾开始但缺少可证明的完成证据",
                recovery_blocked=True,
            )
            return
        try:
            await self._resume_test(context.run.id, test_id, context.patch.diff_sha256)
        except (
            WorkspaceInconsistentError,
            UnsafeWorkspacePathError,
            PatchSourceChangedError,
            ValueError,
        ):
            await self._store.fail(
                context.run.id,
                "WORKSPACE_INCONSISTENT",
                FAILURE_MESSAGES["WORKSPACE_INCONSISTENT"],
                recovery_blocked=True,
            )
        except (CheckpointerUnavailableError, DatabaseUnavailableError):
            raise
        except Exception as error:
            code = _failure_code(error)
            await self._store.fail(
                context.run.id, code, FAILURE_MESSAGES[code]
            )

    async def load_bundle(self, run_id: UUID) -> ImplementationBundle:
        context = await self._store.load_context(run_id)
        if context.run.status not in {"pending", "generating_patch"}:
            raise ImplementationConflictError(
                "IMPLEMENTATION_STATE_CONFLICT", "实现状态不能加载模型输入"
            )
        await self._verify_source(context)
        source = self._source_workspace.repository_path(context.task.id)
        worktree = await self._implementation_workspace.prepare(
            source, context.task.id, run_id, context.run.base_commit
        )
        await self._store.set_generating(
            run_id, self._implementation_workspace.relative_path(worktree)
        )
        files = _load_source_files(source, context)
        return ImplementationBundle(
            implementation_run_id=run_id,
            issue=context.task.issue_text,
            commit_sha=context.run.base_commit,
            plan={
                "version": context.plan.version,
                "steps": context.plan.steps,
                "test_strategy": context.plan.test_strategy,
                "risk_notes": context.plan.risk_notes,
            },
            files=files,
        )

    async def apply_patch(self, run_id: UUID, draft: PatchDraft) -> str:
        response = await self._store.load_response_by_run(run_id)
        if response.patch is not None:
            context = await self._store.load_context(run_id)
            worktree = self._require_worktree(context)
            artifact = await self._patch_service.inspect(
                worktree, _allowed_paths(context)
            )
            if artifact.diff_sha256 != response.patch.sha256:
                raise WorkspaceInconsistentError()
            return response.patch.sha256
        context = await self._store.load_context(run_id)
        await self._verify_source(context)
        worktree = self._require_worktree(context)
        artifact = await self._patch_service.apply(
            worktree, _allowed_paths(context), draft.replacements
        )
        return await self._store.persist_patch(run_id, artifact)

    async def run_test(self, test_run_id: UUID) -> None:
        context = await self._store.load_test_context(test_run_id)
        await self._verify_source_for_test(context.run.id)
        worktree = self._implementation_workspace.resolve_for(
            context.task.id,
            context.run.id,
            context.run.worktree_relpath or "",
        )
        artifact = await self._patch_service.inspect(
            worktree, await self._allowed_paths_for_run(context.run.id)
        )
        if artifact.diff_sha256 != context.patch.diff_sha256:
            raise WorkspaceInconsistentError()
        await self._store.mark_testing(test_run_id)
        result = await self._test_runner.run(worktree, test_run_id)
        await self._store.persist_test_result(test_run_id, result)

    async def _invoke_initial(self, run_id: UUID) -> None:
        context = ImplementationRuntimeContext(self, self._provider)
        async with self._checkpoint_factory.saver() as saver:
            graph = build_implementation_graph(saver)
            config = _graph_config(run_id)
            checkpoint = await saver.aget_tuple(config)
            if checkpoint is None:
                await graph.ainvoke(
                    {"implementation_run_id": str(run_id)},
                    context=context,
                    config=config,
                )
            else:
                context_record = await self._store.load_context(run_id)
                await self._verify_source(context_record)
                snapshot = await graph.aget_state(config)
                _verify_initial_checkpoint(snapshot, context_record)
                await self._verify_initial_worktree(context_record)
                await graph.ainvoke(None, context=context, config=config)

    async def _resume_test(
        self, run_id: UUID, test_id: UUID, patch_sha256: str
    ) -> None:
        context_record = await self._store.load_context(run_id)
        await self._verify_source(context_record)
        async with self._checkpoint_factory.saver() as saver:
            graph = build_implementation_graph(saver)
            config = _graph_config(run_id)
            checkpoint = await saver.aget_tuple(config)
            if checkpoint is None:
                raise WorkspaceInconsistentError()
            snapshot = await graph.aget_state(config)
            if snapshot.next == ("apply_patch",):
                _verify_checkpoint_values(snapshot.values, context_record)
                await graph.ainvoke(None, context=ImplementationRuntimeContext(
                    self, self._provider
                ), config=config)
                snapshot = await graph.aget_state(config)
            if snapshot.next != ("await_test_approval",):
                raise WorkspaceInconsistentError()
            values = snapshot.values
            _verify_checkpoint_values(values, context_record)
            if values.get("patch_sha256") != patch_sha256:
                raise WorkspaceInconsistentError()
            await graph.ainvoke(
                Command(
                    resume={
                        "action": "run_tests",
                        "test_run_id": str(test_id),
                        "patch_sha256": patch_sha256,
                    }
                ),
                context=ImplementationRuntimeContext(self, self._provider),
                config=config,
            )

    async def _verify_source(self, context: ImplementationContext) -> None:
        commits = {
            context.run.base_commit,
            context.planning_run.commit_sha,
            context.snapshot.commit_sha,
            context.code_index.commit_sha,
            context.retrieval_run.commit_sha,
        }
        if len(commits) != 1 or context.plan.id != context.run.plan_id:
            raise WorkspaceInconsistentError()
        if (
            context.plan.status != "approved"
            or context.plan.version != context.run.plan_version
            or context.run.graph_version != GRAPH_VERSION
            or context.run.prompt_version != PROMPT_VERSION
            or context.run.llm_provider != self._provider.name
            or context.run.llm_model != self._provider.model
            or context.run.checkpoint_thread_id
            != f"implementation:{context.run.id}"
        ):
            raise WorkspaceInconsistentError()
        source = self._source_workspace.repository_path(context.task.id)
        await verify_workspace(self._git, source, context.run.base_commit)

    async def _verify_source_for_test(self, run_id: UUID) -> None:
        await self._verify_source(await self._store.load_context(run_id))

    async def _verify_initial_worktree(
        self, context: ImplementationContext
    ) -> None:
        expected = self._implementation_workspace.path(
            context.task.id, context.run.id
        )
        if context.run.status == "pending":
            if context.run.worktree_relpath is not None:
                raise WorkspaceInconsistentError()
            if expected.exists():
                await self._require_clean_worktree(
                    expected, context.run.base_commit
                )
            return
        if not context.run.worktree_relpath:
            raise WorkspaceInconsistentError()
        worktree = self._implementation_workspace.resolve_for(
            context.task.id,
            context.run.id,
            context.run.worktree_relpath,
        )
        await self._require_clean_worktree(worktree, context.run.base_commit)

    async def _require_clean_worktree(
        self, worktree: Path, commit_sha: str
    ) -> None:
        try:
            valid = (
                worktree.is_dir()
                and await self._git.head_sha(worktree) == commit_sha
                and await self._git.is_clean(worktree)
            )
        except GitClientError as error:
            raise WorkspaceInconsistentError() from error
        if not valid:
            raise WorkspaceInconsistentError()

    async def _allowed_paths_for_run(self, run_id: UUID) -> Set[str]:
        return _allowed_paths(await self._store.load_context(run_id))

    def _require_worktree(self, context: ImplementationContext) -> Path:
        if not context.run.worktree_relpath:
            raise WorkspaceInconsistentError()
        worktree = self._implementation_workspace.resolve_for(
            context.task.id,
            context.run.id,
            context.run.worktree_relpath,
        )
        if not worktree.is_dir():
            raise WorkspaceInconsistentError()
        return worktree

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise ImplementationDisabledError()


def _allowed_paths(context: ImplementationContext) -> Set[str]:
    implementation_paths = {
        path
        for step in context.plan.steps
        for path in step.get("paths", [])
    }
    test_paths = {
        path
        for item in context.plan.test_strategy
        for path in item.get("target_paths", [])
    }
    paths = implementation_paths & test_paths
    manifest = {
        item["path"]
        for item in context.snapshot.tree_manifest
        if item.get("kind") == "file"
    }
    allowed = {
        path
        for path in paths
        if path in manifest and _is_safe_python_path(path)
    }
    if not paths or allowed != paths or len(allowed) > 4:
        raise ImplementationScopeError()
    return allowed


def _load_source_files(
    source: Path, context: ImplementationContext
) -> list[ImplementationSourceFile]:
    files = []
    total = 0
    root = source.resolve()
    for relative in sorted(_allowed_paths(context)):
        path = source.joinpath(*PurePosixPath(relative).parts)
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError) as error:
            raise ImplementationScopeError() from error
        if path.is_symlink() or not resolved.is_file():
            raise ImplementationScopeError()
        content = resolved.read_bytes()
        if len(content) > 81_920:
            raise ImplementationScopeError()
        total += len(content)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ImplementationScopeError() from error
        files.append(
            ImplementationSourceFile(
                path=relative,
                sha256=hashlib.sha256(content).hexdigest(),
                content=text,
            )
        )
    if total > 163_840:
        raise ImplementationScopeError()
    return files


def _is_safe_python_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and bool(path.parts)
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.parts[0] != ".git"
        and path.suffix == ".py"
    )


def _graph_config(run_id: UUID) -> dict:
    return {
        "configurable": {
            "thread_id": f"implementation:{run_id}",
            "checkpoint_ns": "",
        },
        "recursion_limit": 12,
    }


def _verify_checkpoint_values(values: dict, context: ImplementationContext) -> None:
    plan = values.get("plan") or {}
    if (
        values.get("implementation_run_id") != str(context.run.id)
        or values.get("commit_sha") != context.run.base_commit
        or plan.get("version") != context.run.plan_version
    ):
        raise WorkspaceInconsistentError()


def _verify_initial_checkpoint(snapshot, context: ImplementationContext) -> None:
    values = snapshot.values
    if values.get("implementation_run_id") != str(context.run.id):
        raise WorkspaceInconsistentError()
    if snapshot.next == ("load_context",):
        if context.run.status not in {"pending", "generating_patch"}:
            raise WorkspaceInconsistentError()
        return
    if context.run.status != "generating_patch" or snapshot.next not in {
        ("generate_replacements",),
        ("apply_patch",),
    }:
        raise WorkspaceInconsistentError()
    _verify_checkpoint_values(values, context)


def _failure_code(error: Exception) -> str:
    if isinstance(error, ImplementationScopeError):
        return "IMPLEMENTATION_SCOPE_INVALID"
    if isinstance(error, (PatchValidationError, LlmInvalidResponseError)):
        return "PATCH_OUTPUT_INVALID"
    if isinstance(error, LlmUnavailableError):
        return "LLM_UNAVAILABLE"
    if isinstance(error, TestRunnerUnavailableError):
        return "TEST_RUNNER_UNAVAILABLE"
    if isinstance(error, (WorkspaceInconsistentError, UnsafeWorkspacePathError)):
        return "WORKSPACE_INCONSISTENT"
    if isinstance(error, (ImplementationConflictError, GitClientError)):
        return "IMPLEMENTATION_FAILED"
    return "IMPLEMENTATION_FAILED"
