import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.implementation_graph import GRAPH_VERSION, PROMPT_VERSION
from app.models.code_index import CodeIndex
from app.models.implementation import ImplementationRun, PatchArtifact, TestRun
from app.models.planning import ImplementationPlan, PlanningRun
from app.models.repository_snapshot import RepositorySnapshot
from app.models.retrieval import RetrievalRun
from app.models.task import Task
from app.schemas.implementation import (
    ImplementationCreate,
    ImplementationResponse,
    ImplementationRunResponse,
    PatchArtifactResponse,
    PatchFile,
    TestRunCreate,
    TestRunResponse,
)
from app.schemas.task import TaskStatus
from app.services.patch_service import PatchArtifactDraft
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError
from app.services.test_runner import TEST_COMMAND, TestExecutionResult


class ImplementationConflictError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImplementationNotReadyError(Exception):
    pass


@dataclass(frozen=True)
class ImplementationContext:
    task: Task
    run: ImplementationRun
    plan: ImplementationPlan
    planning_run: PlanningRun
    snapshot: RepositorySnapshot
    code_index: CodeIndex
    retrieval_run: RetrievalRun


@dataclass(frozen=True)
class TestContext:
    task: Task
    run: ImplementationRun
    patch: PatchArtifact
    test: TestRun


class SqlImplementationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self,
        task_id: UUID,
        payload: ImplementationCreate,
        provider: str,
        model: str,
    ) -> ImplementationResponse:
        try:
            return await self._create_run_transaction(
                task_id, payload, provider, model
            )
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def load_response(self, task_id: UUID) -> Optional[ImplementationResponse]:
        try:
            task = await self._require_task(task_id)
            run = await self._run_for_task(task_id)
            if run is None:
                await self._session.commit()
                return None
            response = await self._response(run, task)
            await self._session.commit()
            return response
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def load_response_by_run(self, run_id: UUID) -> ImplementationResponse:
        try:
            run = await self._session.get(ImplementationRun, run_id)
            if run is None:
                raise ImplementationNotReadyError()
            task = await self._require_task(run.task_id)
            response = await self._response(run, task)
            await self._session.commit()
            return response
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def load_context(self, run_id: UUID) -> ImplementationContext:
        try:
            run = await self._session.get(ImplementationRun, run_id)
            if run is None:
                raise ImplementationNotReadyError()
            task = await self._require_task(run.task_id)
            plan = await self._session.get(ImplementationPlan, run.plan_id)
            planning_run = await self._session.get(
                PlanningRun, run.planning_run_id
            )
            snapshot = await self._session.get(RepositorySnapshot, run.task_id)
            code_index = await self._session.get(CodeIndex, run.task_id)
            retrieval_run = await self._session.scalar(
                select(RetrievalRun).where(RetrievalRun.task_id == run.task_id)
            )
            if any(value is None for value in (
                plan,
                planning_run,
                snapshot,
                code_index,
                retrieval_run,
            )):
                raise ImplementationNotReadyError()
            context = ImplementationContext(
                task,
                run,
                plan,
                planning_run,
                snapshot,
                code_index,
                retrieval_run,
            )
            await self._session.commit()
            return context
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def set_generating(self, run_id: UUID, worktree_relpath: str) -> None:
        try:
            run, task = await self._lock_run_and_task(run_id)
            if run.status not in {"pending", "generating_patch"}:
                raise ImplementationConflictError(
                    "IMPLEMENTATION_STATE_CONFLICT", "实现状态不能生成 Patch"
                )
            run.status = "generating_patch"
            run.worktree_relpath = worktree_relpath
            task.status = TaskStatus.GENERATING_PATCH
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def persist_patch(
        self, run_id: UUID, draft: PatchArtifactDraft
    ) -> str:
        try:
            run, task = await self._lock_run_and_task(run_id)
            existing = await self._session.get(PatchArtifact, run_id)
            if existing is not None:
                if existing.diff_sha256 != draft.diff_sha256:
                    raise ImplementationConflictError(
                        "PATCH_STATE_CONFLICT", "已保存 Patch 与工作区不一致"
                    )
                await self._session.commit()
                return existing.diff_sha256
            if run.status != "generating_patch":
                raise ImplementationConflictError(
                    "IMPLEMENTATION_STATE_CONFLICT", "实现状态不能保存 Patch"
                )
            self._session.add(
                PatchArtifact(
                    implementation_run_id=run_id,
                    unified_diff=draft.unified_diff,
                    diff_sha256=draft.diff_sha256,
                    file_manifest=draft.file_manifest,
                    file_count=draft.file_count,
                    insertions=draft.insertions,
                    deletions=draft.deletions,
                )
            )
            run.status = "patch_ready"
            task.status = TaskStatus.PATCH_READY
            await self._session.commit()
            return draft.diff_sha256
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def create_test(
        self,
        task_id: UUID,
        payload: TestRunCreate,
        runner_image: str,
    ) -> ImplementationResponse:
        try:
            return await self._create_test_transaction(
                task_id, payload, runner_image
            )
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def load_test_context(self, test_id: UUID) -> TestContext:
        try:
            test = await self._session.get(TestRun, test_id)
            if test is None:
                raise ImplementationNotReadyError()
            run = await self._session.get(
                ImplementationRun, test.implementation_run_id
            )
            patch = await self._session.get(
                PatchArtifact, test.implementation_run_id
            )
            if run is None or patch is None:
                raise ImplementationNotReadyError()
            task = await self._require_task(run.task_id)
            await self._session.commit()
            return TestContext(task, run, patch, test)
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def mark_testing(self, test_id: UUID) -> None:
        try:
            test, run, task = await self._lock_test_run_task(test_id)
            if test.status == "running":
                await self._session.commit()
                return
            if test.status != "pending" or run.status != "test_pending":
                raise ImplementationConflictError(
                    "TEST_STATE_CONFLICT", "测试状态不能开始执行"
                )
            test.status = "running"
            run.status = "testing"
            task.status = TaskStatus.TESTING
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def persist_test_result(
        self, test_id: UUID, result: TestExecutionResult
    ) -> None:
        try:
            test, run, task = await self._lock_test_run_task(test_id)
            if test.status in {"passed", "failed"}:
                await self._session.commit()
                return
            if test.status != "running":
                raise ImplementationConflictError(
                    "TEST_STATE_CONFLICT", "测试状态不能保存结果"
                )
            passed = result.exit_code == 0 and not result.timed_out
            test.status = "passed" if passed else "failed"
            test.runner_image = result.runner_image
            test.exit_code = result.exit_code
            test.timed_out = result.timed_out
            test.duration_ms = result.duration_ms
            test.stdout = result.stdout
            test.stderr = result.stderr
            test.output_sha256 = result.output_sha256
            test.output_truncated = result.output_truncated
            test.finished_at = datetime.now(timezone.utc)
            run.status = "tested" if passed else "test_failed"
            task.status = TaskStatus.TESTED if passed else TaskStatus.TEST_FAILED
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def pending_work(self, limit: int) -> list[tuple[str, UUID]]:
        try:
            run_ids = list(
                (
                    await self._session.scalars(
                        select(ImplementationRun.id)
                        .where(
                            ImplementationRun.status.in_(
                                ["pending", "generating_patch"]
                            )
                        )
                        .order_by(ImplementationRun.created_at)
                        .limit(limit)
                    )
                ).all()
            )
            remaining = max(0, limit - len(run_ids))
            test_ids = list(
                (
                    await self._session.scalars(
                        select(TestRun.id)
                        .where(TestRun.status.in_(["pending", "running"]))
                        .order_by(TestRun.created_at)
                        .limit(remaining)
                    )
                ).all()
            )
            await self._session.commit()
            return [("implementation", value) for value in run_ids] + [
                ("test", value) for value in test_ids
            ]
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def fail(
        self, run_id: UUID, code: str, message: str, recovery_blocked: bool = False
    ) -> None:
        try:
            run, task = await self._lock_run_and_task(run_id)
            if run.status in {"tested", "test_failed", "failed"}:
                await self._session.commit()
                return
            run.status = "recovery_blocked" if recovery_blocked else "failed"
            run.failure_code = code
            run.failure_message = message
            task.status = (
                TaskStatus.RECOVERY_BLOCKED
                if recovery_blocked
                else TaskStatus.FAILED
            )
            task.failure_code = code
            task.failure_message = message
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def _response(
        self, run: ImplementationRun, task: Task
    ) -> ImplementationResponse:
        del task
        patch = await self._session.get(PatchArtifact, run.id)
        test = await self._test_for_run(run.id)
        return ImplementationResponse(
            run=_run_response(run),
            patch=_patch_response(patch) if patch else None,
            test=_test_response(test) if test else None,
        )

    async def _create_run_transaction(
        self,
        task_id: UUID,
        payload: ImplementationCreate,
        provider: str,
        model: str,
    ) -> ImplementationResponse:
        task = await self._lock_task(task_id)
        existing = await self._run_by_key(task_id, payload.idempotency_key)
        if existing is not None:
            if existing.plan_version != payload.expected_plan_version:
                raise ImplementationConflictError(
                    "IMPLEMENTATION_REQUEST_MISMATCH",
                    "幂等键对应的计划版本不同",
                )
            response = await self._response(existing, task)
            await self._session.commit()
            return response
        if await self._run_for_task(task_id) is not None:
            raise ImplementationConflictError(
                "IMPLEMENTATION_ALREADY_EXISTS", "该任务已有实现记录"
            )
        planning_run, plan = await self._approved_plan(task_id)
        if task.status != TaskStatus.APPROVED or plan.status != "approved":
            raise ImplementationConflictError(
                "IMPLEMENTATION_NOT_APPROVED", "实施计划尚未批准"
            )
        if plan.version != payload.expected_plan_version:
            raise ImplementationConflictError(
                "PLAN_VERSION_CONFLICT", "计划版本已经变化"
            )
        run = _new_implementation_run(
            task_id, payload, planning_run, plan, provider, model
        )
        self._session.add(run)
        task.status = TaskStatus.IMPLEMENTATION_PENDING
        task.failure_code = None
        task.failure_message = None
        await self._session.commit()
        await self._session.refresh(run)
        return await self._response(run, task)

    async def _create_test_transaction(
        self,
        task_id: UUID,
        payload: TestRunCreate,
        runner_image: str,
    ) -> ImplementationResponse:
        task = await self._lock_task(task_id)
        run = await self._run_for_task(task_id, lock=True)
        if run is None:
            raise ImplementationNotReadyError()
        existing = await self._test_by_key(run.id, payload.idempotency_key)
        if existing is not None:
            if existing.expected_patch_sha256 != payload.expected_patch_sha256:
                raise ImplementationConflictError(
                    "TEST_REQUEST_MISMATCH", "幂等键对应的 Patch 不同"
                )
            response = await self._response(run, task)
            await self._session.commit()
            return response
        if await self._test_for_run(run.id) is not None:
            raise ImplementationConflictError(
                "TEST_ALREADY_EXISTS", "该 Patch 已有测试记录"
            )
        patch = await self._session.get(PatchArtifact, run.id)
        if (
            task.status != TaskStatus.PATCH_READY
            or run.status != "patch_ready"
            or patch is None
        ):
            raise ImplementationConflictError("PATCH_NOT_READY", "Patch 尚未准备好")
        if patch.diff_sha256 != payload.expected_patch_sha256:
            raise ImplementationConflictError(
                "PATCH_VERSION_CONFLICT", "Patch 已经变化"
            )
        test = _new_test_run(run.id, payload, patch, runner_image)
        self._session.add(test)
        run.status = "test_pending"
        task.status = TaskStatus.TEST_PENDING
        await self._session.commit()
        await self._session.refresh(run)
        await self._session.refresh(test)
        return await self._response(run, task)

    async def _lock_task(self, task_id: UUID) -> Task:
        task = await self._session.scalar(
            select(Task).where(Task.id == task_id).with_for_update()
        )
        if task is None:
            raise TaskNotFoundError()
        return task

    async def _require_task(self, task_id: UUID) -> Task:
        task = await self._session.get(Task, task_id)
        if task is None:
            raise TaskNotFoundError()
        return task

    async def _approved_plan(
        self, task_id: UUID
    ) -> tuple[PlanningRun, ImplementationPlan]:
        row = (
            await self._session.execute(
                select(PlanningRun, ImplementationPlan)
                .join(
                    ImplementationPlan,
                    ImplementationPlan.run_id == PlanningRun.id,
                )
                .where(
                    PlanningRun.task_id == task_id,
                    ImplementationPlan.status == "approved",
                )
                .with_for_update()
            )
        ).first()
        if row is None:
            raise ImplementationConflictError(
                "IMPLEMENTATION_NOT_APPROVED", "没有已批准计划"
            )
        return row[0], row[1]

    async def _run_for_task(
        self, task_id: UUID, lock: bool = False
    ) -> Optional[ImplementationRun]:
        query = select(ImplementationRun).where(
            ImplementationRun.task_id == task_id
        )
        if lock:
            query = query.with_for_update()
        return await self._session.scalar(query)

    async def _run_by_key(self, task_id: UUID, key: UUID):
        return await self._session.scalar(
            select(ImplementationRun).where(
                ImplementationRun.task_id == task_id,
                ImplementationRun.idempotency_key == key,
            )
        )

    async def _test_for_run(self, run_id: UUID):
        return await self._session.scalar(
            select(TestRun).where(TestRun.implementation_run_id == run_id)
        )

    async def _test_by_key(self, run_id: UUID, key: UUID):
        return await self._session.scalar(
            select(TestRun).where(
                TestRun.implementation_run_id == run_id,
                TestRun.idempotency_key == key,
            )
        )

    async def _lock_run_and_task(
        self, run_id: UUID
    ) -> tuple[ImplementationRun, Task]:
        reference = await self._session.get(ImplementationRun, run_id)
        if reference is None:
            raise ImplementationNotReadyError()
        task = await self._lock_task(reference.task_id)
        run = await self._session.scalar(
            select(ImplementationRun)
            .where(ImplementationRun.id == run_id)
            .with_for_update()
        )
        if run is None or run.task_id != task.id:
            raise ImplementationNotReadyError()
        return run, task

    async def _lock_test_run_task(
        self, test_id: UUID
    ) -> tuple[TestRun, ImplementationRun, Task]:
        reference = await self._session.get(TestRun, test_id)
        if reference is None:
            raise ImplementationNotReadyError()
        run, task = await self._lock_run_and_task(
            reference.implementation_run_id
        )
        test = await self._session.scalar(
            select(TestRun).where(TestRun.id == test_id).with_for_update()
        )
        if test is None or test.implementation_run_id != run.id:
            raise ImplementationNotReadyError()
        return test, run, task


def _new_implementation_run(
    task_id: UUID,
    payload: ImplementationCreate,
    planning_run: PlanningRun,
    plan: ImplementationPlan,
    provider: str,
    model: str,
) -> ImplementationRun:
    run_id = uuid.uuid4()
    return ImplementationRun(
        id=run_id,
        task_id=task_id,
        planning_run_id=planning_run.id,
        plan_id=plan.id,
        plan_version=plan.version,
        idempotency_key=payload.idempotency_key,
        base_commit=planning_run.commit_sha,
        graph_version=GRAPH_VERSION,
        prompt_version=PROMPT_VERSION,
        llm_provider=provider,
        llm_model=model,
        checkpoint_thread_id=f"implementation:{run_id}",
        status="pending",
    )


def _new_test_run(
    run_id: UUID,
    payload: TestRunCreate,
    patch: PatchArtifact,
    runner_image: str,
) -> TestRun:
    return TestRun(
        id=uuid.uuid4(),
        implementation_run_id=run_id,
        idempotency_key=payload.idempotency_key,
        expected_patch_sha256=patch.diff_sha256,
        status="pending",
        command_argv=TEST_COMMAND,
        runner_image=runner_image,
        timed_out=False,
        output_truncated=False,
    )


def _run_response(run: ImplementationRun) -> ImplementationRunResponse:
    return ImplementationRunResponse(
        implementation_run_id=run.id,
        task_id=run.task_id,
        plan_id=run.plan_id,
        plan_version=run.plan_version,
        base_commit=run.base_commit,
        status=run.status,
        provider=run.llm_provider,
        model=run.llm_model,
        failure_code=run.failure_code,
        failure_message=run.failure_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _patch_response(patch: PatchArtifact) -> PatchArtifactResponse:
    return PatchArtifactResponse(
        sha256=patch.diff_sha256,
        unified_diff=patch.unified_diff,
        files=[PatchFile.model_validate(item) for item in patch.file_manifest],
        file_count=patch.file_count,
        insertions=patch.insertions,
        deletions=patch.deletions,
        created_at=patch.created_at,
    )


def _test_response(test: TestRun) -> TestRunResponse:
    return TestRunResponse(
        test_run_id=test.id,
        status=test.status,
        command_argv=test.command_argv,
        runner_image=test.runner_image,
        exit_code=test.exit_code,
        timed_out=test.timed_out,
        duration_ms=test.duration_ms,
        stdout=test.stdout,
        stderr=test.stderr,
        output_sha256=test.output_sha256,
        output_truncated=test.output_truncated,
        created_at=test.created_at,
        finished_at=test.finished_at,
    )
