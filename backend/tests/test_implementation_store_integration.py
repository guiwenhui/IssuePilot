import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.db.session import session_factory
from app.models.task import Task
from app.schemas.implementation import ImplementationCreate, TestRunCreate as RunRequest
from app.schemas.planning import PlanningDecisionAction, PlanningDecisionCreate
from app.schemas.task import TaskStatus
from app.services.implementation_store import SqlImplementationStore
from app.services.patch_service import PatchArtifactDraft
from app.services.planning_store import SqlPlanningStore
from app.services.test_runner import TestExecutionResult as ExecutionResult
from tests.test_approval_store_integration import _planned_task


@pytest.mark.asyncio
async def test_implementation_store_is_idempotent_through_test_result() -> None:
    async with session_factory() as session:
        task, _, planning_store = await _planned_task(session)
        task_id = task.id
        decision = await planning_store.create_decision(
            task_id,
            PlanningDecisionCreate(
                action=PlanningDecisionAction.APPROVE,
                expected_plan_version=1,
                idempotency_key=uuid4(),
            ),
        )
        await planning_store.apply_terminal_decision(
            decision.decision_id, "approve"
        )
        store = SqlImplementationStore(session)
        payload = ImplementationCreate(
            expected_plan_version=1, idempotency_key=uuid4()
        )
        try:
            first = await store.create_run(task_id, payload, "ollama", "qwen3:8b")
            repeated = await store.create_run(
                task_id, payload, "ollama", "qwen3:8b"
            )
            assert first.run.implementation_run_id == repeated.run.implementation_run_id

            run_id = first.run.implementation_run_id
            await store.set_generating(run_id, "tasks/task/implementations/run")
            patch_sha = await store.persist_patch(
                run_id,
                PatchArtifactDraft(
                    unified_diff="diff --git a/example.py b/example.py\n",
                    diff_sha256="a" * 64,
                    file_manifest=[
                        {
                            "path": "example.py",
                            "original_sha256": "b" * 64,
                            "patched_sha256": "c" * 64,
                        }
                    ],
                    file_count=1,
                    insertions=1,
                    deletions=1,
                ),
            )
            test_payload = RunRequest(
                expected_patch_sha256=patch_sha,
                idempotency_key=uuid4(),
            )
            test_response = await store.create_test(
                task_id,
                test_payload,
                "runner:m7",
            )
            assert test_response.test is not None
            test_id = test_response.test.test_run_id

            async def retry_request():
                async with session_factory() as retry_session:
                    return await SqlImplementationStore(
                        retry_session
                    ).create_test(task_id, test_payload, "runner:m7")

            async def start_worker() -> None:
                async with session_factory() as worker_session:
                    await SqlImplementationStore(worker_session).mark_testing(
                        test_id
                    )

            retried, _ = await asyncio.wait_for(
                asyncio.gather(retry_request(), start_worker()), timeout=5
            )
            assert retried.test is not None
            assert retried.test.test_run_id == test_id
            assert ("test", test_id) in await store.pending_work(10)
            await store.persist_test_result(
                test_id,
                ExecutionResult(
                    command_argv=["python", "-m", "pytest", "-q"],
                    runner_image="sha256:fixed",
                    exit_code=0,
                    timed_out=False,
                    duration_ms=10,
                    stdout="1 passed",
                    stderr="",
                    output_sha256="d" * 64,
                    output_truncated=False,
                ),
            )

            final = await store.load_response(task_id)
            assert final is not None
            assert final.run.status == "tested"
            assert final.test is not None and final.test.status == "passed"
            refreshed = await session.get(Task, task_id)
            assert refreshed is not None
            assert refreshed.status == TaskStatus.TESTED
        finally:
            await session.rollback()
            await session.execute(delete(Task).where(Task.id == task_id))
            await session.commit()
