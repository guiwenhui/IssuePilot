import hashlib
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.implementation_graph import GRAPH_VERSION, PROMPT_VERSION
from app.schemas.implementation import PatchDraft
from app.services.git_client import GitClient
from app.services.implementation_service import (
    ImplementationScopeError,
    ImplementationService,
    _allowed_paths,
    _verify_initial_checkpoint,
)
from app.services.implementation_workspace import ImplementationWorkspace
from app.services.patch_service import PatchLimits, PatchService
from app.services.repository_service import WorkspaceInconsistentError
from app.services.test_runner import TestExecutionResult as ExecutionResult
from app.services.workspace import WorkspaceLimits, WorkspaceManager
from app.services.workspace import UnsafeWorkspacePathError


SOURCE = "def add(left: int, right: int) -> int:\n    return left - right\n"


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


class ReplacementProvider:
    name = "fake-local"
    model = "fake-code-v1"

    async def generate(self, messages, response_model):
        del messages
        return response_model.model_validate(
            {
                "replacements": [
                    {
                        "path": "calculator.py",
                        "original_sha256": hashlib.sha256(
                            SOURCE.encode()
                        ).hexdigest(),
                        "content": SOURCE.replace("left - right", "left + right"),
                    }
                ]
            }
        )


class MemoryCheckpointFactory:
    def __init__(self) -> None:
        self.checkpointer = InMemorySaver()

    @asynccontextmanager
    async def saver(self):
        yield self.checkpointer


class PassingRunner:
    image = "runner:m7"

    def __init__(self) -> None:
        self.cleaned = []

    async def run(self, worktree: Path, test_id: UUID) -> ExecutionResult:
        del test_id
        assert "left + right" in (worktree / "calculator.py").read_text()
        return ExecutionResult(
            command_argv=["python", "-m", "pytest", "-q"],
            runner_image="sha256:fixed",
            exit_code=0,
            timed_out=False,
            duration_ms=12,
            stdout="1 passed",
            stderr="",
            output_sha256="d" * 64,
            output_truncated=False,
        )

    async def cleanup(self, test_id: UUID) -> None:
        self.cleaned.append(test_id)


class MemoryImplementationStore:
    def __init__(self, context, test_id: UUID) -> None:
        self.context = context
        self.test_id = test_id
        self.patch = None
        self.test = SimpleNamespace(status="pending")
        self.saved_test_result = None
        self.failures = []

    async def load_context(self, run_id: UUID):
        assert run_id == self.context.run.id
        return self.context

    async def set_generating(self, run_id: UUID, worktree_relpath: str) -> None:
        assert run_id == self.context.run.id
        self.context.run.status = "generating_patch"
        self.context.run.worktree_relpath = worktree_relpath

    async def load_response_by_run(self, run_id: UUID):
        assert run_id == self.context.run.id
        patch = (
            SimpleNamespace(sha256=self.patch.diff_sha256)
            if self.patch
            else None
        )
        return SimpleNamespace(patch=patch)

    async def persist_patch(self, run_id: UUID, artifact) -> str:
        assert run_id == self.context.run.id
        self.patch = artifact
        self.context.run.status = "patch_ready"
        return artifact.diff_sha256

    async def load_response(self, task_id: UUID):
        assert task_id == self.context.task.id
        return SimpleNamespace(
            run=SimpleNamespace(implementation_run_id=self.context.run.id),
            patch=SimpleNamespace(sha256=self.patch.diff_sha256),
            test=None,
        )

    async def load_test_context(self, test_id: UUID):
        assert test_id == self.test_id
        return SimpleNamespace(
            task=self.context.task,
            run=self.context.run,
            patch=SimpleNamespace(diff_sha256=self.patch.diff_sha256),
            test=self.test,
        )

    async def mark_testing(self, test_id: UUID) -> None:
        assert test_id == self.test_id
        self.test.status = "running"
        self.context.run.status = "testing"

    async def persist_test_result(self, test_id: UUID, result) -> None:
        assert test_id == self.test_id
        self.test.status = "passed"
        self.context.run.status = "tested"
        self.saved_test_result = result

    async def fail(
        self, run_id: UUID, code: str, message: str, recovery_blocked=False
    ) -> None:
        self.failures.append((run_id, code, message, recovery_blocked))


def service_fixture(tmp_path: Path):
    task_id, run_id, plan_id, test_id = uuid4(), uuid4(), uuid4(), uuid4()
    manager = WorkspaceManager(
        tmp_path / "workspace",
        WorkspaceLimits(1_000_000, 100, 100, 10),
    )
    source = manager.repository_path(task_id)
    source.mkdir(parents=True)
    git(source, "init")
    git(source, "config", "user.email", "test@example.com")
    git(source, "config", "user.name", "IssuePilot Test")
    (source / "calculator.py").write_text(SOURCE)
    git(source, "add", "calculator.py")
    git(source, "commit", "-m", "fixture")
    commit = git(source, "rev-parse", "HEAD")
    context = SimpleNamespace(
        task=SimpleNamespace(id=task_id, issue_text="Fix addition"),
        run=SimpleNamespace(
            id=run_id,
            status="pending",
            base_commit=commit,
            plan_id=plan_id,
            plan_version=1,
            graph_version=GRAPH_VERSION,
            prompt_version=PROMPT_VERSION,
            llm_provider="fake-local",
            llm_model="fake-code-v1",
            checkpoint_thread_id=f"implementation:{run_id}",
            worktree_relpath=None,
        ),
        plan=SimpleNamespace(
            id=plan_id,
            status="approved",
            version=1,
            steps=[{"paths": ["calculator.py"]}],
            test_strategy=[{"target_paths": ["calculator.py"]}],
            risk_notes=[],
        ),
        planning_run=SimpleNamespace(commit_sha=commit),
        snapshot=SimpleNamespace(
            commit_sha=commit,
            tree_manifest=[{"path": "calculator.py", "kind": "file"}],
        ),
        code_index=SimpleNamespace(commit_sha=commit),
        retrieval_run=SimpleNamespace(commit_sha=commit),
    )
    client = GitClient(10)
    store = MemoryImplementationStore(context, test_id)
    runner = PassingRunner()
    service = ImplementationService(
        store,
        client,
        manager,
        ImplementationWorkspace(manager.root, client),
        PatchService(client, PatchLimits()),
        ReplacementProvider(),
        MemoryCheckpointFactory(),
        runner,
        True,
    )
    return service, store, context, source, test_id


@pytest.mark.asyncio
async def test_service_generates_patch_then_resumes_explicit_test(
    tmp_path: Path,
) -> None:
    service, store, context, source, test_id = service_fixture(tmp_path)

    await service.process_implementation(context.run.id)

    assert store.failures == []
    assert context.run.status == "patch_ready"
    assert (source / "calculator.py").read_text() == SOURCE
    response = await service.get_implementation(context.task.id)
    assert response.patch.sha256 == store.patch.diff_sha256

    await service.process_test(test_id)

    assert context.run.status == "tested"
    assert store.saved_test_result.exit_code == 0
    assert store.test.status == "passed"


@pytest.mark.asyncio
async def test_running_test_without_completion_evidence_is_recovery_blocked(
    tmp_path: Path,
) -> None:
    service, store, context, _, test_id = service_fixture(tmp_path)
    store.patch = SimpleNamespace(diff_sha256="a" * 64)
    store.test.status = "running"

    await service.process_test(test_id)

    assert service._test_runner.cleaned == [test_id]
    assert store.failures[-1][1:] == (
        "WORKSPACE_INCONSISTENT",
        "测试曾开始但缺少可证明的完成证据",
        True,
    )


@pytest.mark.asyncio
async def test_changed_prompt_contract_is_recovery_blocked(
    tmp_path: Path,
) -> None:
    service, store, context, _, _ = service_fixture(tmp_path)
    context.run.prompt_version = "obsolete-prompt"

    await service.process_implementation(context.run.id)

    assert store.failures[-1][1:] == (
        "WORKSPACE_INCONSISTENT",
        "实现记录与真实工作区不一致",
        True,
    )


def test_approved_scope_rejects_traversal_even_if_manifest_is_corrupt(
    tmp_path: Path,
) -> None:
    _, _, context, _, _ = service_fixture(tmp_path)
    context.plan.steps = [{"paths": ["../secret.py"]}]
    context.plan.test_strategy = [{"target_paths": ["../secret.py"]}]
    context.snapshot.tree_manifest = [
        {"path": "../secret.py", "kind": "file"}
    ]

    with pytest.raises(ImplementationScopeError):
        _allowed_paths(context)


def test_test_only_path_is_not_authorized_for_patch(tmp_path: Path) -> None:
    _, _, context, _, _ = service_fixture(tmp_path)
    context.plan.test_strategy = [
        {"target_paths": ["calculator.py", "tests/test_calculator.py"]}
    ]
    context.snapshot.tree_manifest.append(
        {"path": "tests/test_calculator.py", "kind": "file"}
    )

    assert _allowed_paths(context) == {"calculator.py"}


def test_initial_checkpoint_allows_only_status_compatible_nodes(
    tmp_path: Path,
) -> None:
    _, _, context, _, _ = service_fixture(tmp_path)
    early = SimpleNamespace(
        values={"implementation_run_id": str(context.run.id)},
        next=("load_context",),
    )
    _verify_initial_checkpoint(early, context)

    context.run.status = "generating_patch"
    inconsistent = SimpleNamespace(values=early.values, next=("await_test_approval",))
    with pytest.raises(WorkspaceInconsistentError):
        _verify_initial_checkpoint(inconsistent, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("relative", [None, "tasks/wrong/implementations/wrong"])
async def test_generating_recovery_rejects_missing_or_wrong_worktree_record(
    tmp_path: Path, relative: str | None
) -> None:
    service, _, context, _, _ = service_fixture(tmp_path)
    context.run.status = "generating_patch"
    context.run.worktree_relpath = relative

    with pytest.raises((WorkspaceInconsistentError, UnsafeWorkspacePathError)):
        await service._verify_initial_worktree(context)
