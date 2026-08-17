import hashlib
import json
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.agents.planning_state import PlanningEvidenceBundle
from app.db.session import session_factory
from app.models.task import Task
from app.schemas.planning import (
    EvidenceItem,
    PlanningDecisionAction,
    PlanningDecisionCreate,
)
from app.schemas.task import TaskStatus
from app.services.planning_service import PlanningConflictError
from app.services.planning_store import SqlPlanningStore
from tests.test_planning_store_integration import _seed_context, analysis, plan


@pytest.mark.asyncio
async def test_approval_store_is_idempotent_and_applies_approve() -> None:
    async with session_factory() as session:
        task, bundle, store = await _planned_task(session)
        key = uuid4()
        payload = PlanningDecisionCreate(
            action=PlanningDecisionAction.APPROVE,
            expected_plan_version=1,
            idempotency_key=key,
        )
        try:
            first = await store.create_decision(task.id, payload)
            repeated = await store.create_decision(task.id, payload)
            assert first.decision_id == repeated.decision_id
            assert first.task_status == TaskStatus.DECISION_PENDING

            await store.apply_terminal_decision(first.decision_id, "approve")
            response = await store.load_planning(task.id)
            assert response is not None
            assert response.plan.status == "approved"
            assert response.decisions[0].status == "applied"
            refreshed = await session.get(Task, task.id)
            assert refreshed is not None
            assert refreshed.status == TaskStatus.APPROVED
        finally:
            await _clean(session, task.id)


@pytest.mark.asyncio
async def test_approval_store_rejects_stale_version_and_persists_revision() -> None:
    async with session_factory() as session:
        task, bundle, store = await _planned_task(session)
        task_id = task.id
        try:
            with pytest.raises(PlanningConflictError) as stale:
                await store.create_decision(
                    task_id,
                    PlanningDecisionCreate(
                        action=PlanningDecisionAction.APPROVE,
                        expected_plan_version=2,
                        idempotency_key=uuid4(),
                    ),
                )
            assert stale.value.code == "PLAN_VERSION_CONFLICT"

            decision = await store.create_decision(
                task_id,
                PlanningDecisionCreate(
                    action=PlanningDecisionAction.REQUEST_CHANGES,
                    expected_plan_version=1,
                    idempotency_key=uuid4(),
                    comment="Add focused coverage.",
                ),
            )
            version = await store.persist_revision(
                decision.decision_id,
                bundle,
                plan(),
                "Add focused coverage.",
            )
            response = await store.load_planning(task_id)
            assert response is not None
            assert version == 2
            assert response.plan.version == 2
            assert response.plan.status == "proposed"
            assert response.plan.supersedes_plan_id is not None
            assert response.plan.revision_feedback == "Add focused coverage."
            assert response.decisions[0].status == "applied"
        finally:
            await _clean(session, task_id)


@pytest.mark.asyncio
async def test_concurrent_same_idempotency_key_returns_one_decision() -> None:
    async with session_factory() as seed_session:
        task, _, _ = await _planned_task(seed_session)
        task_id = task.id
        key = uuid4()
    payload = PlanningDecisionCreate(
        action=PlanningDecisionAction.APPROVE,
        expected_plan_version=1,
        idempotency_key=key,
    )

    async def submit():
        async with session_factory() as session:
            return await SqlPlanningStore(session).create_decision(
                task_id, payload
            )

    try:
        first, second = await asyncio.gather(submit(), submit())
        assert first.decision_id == second.decision_id
    finally:
        async with session_factory() as cleanup_session:
            await _clean(cleanup_session, task_id)


async def _planned_task(session):
    task, retrieval = await _seed_context(session)
    store = SqlPlanningStore(session)
    context = await store.load_context(task.id)
    record = context.evidence[0]
    evidence = [
        EvidenceItem(
            rank=record.rank,
            path=record.path,
            symbol=record.symbol,
            kind=record.kind,
            start_line=record.start_line,
            end_line=record.end_line,
            snippet=record.content,
            matched_channels=list(record.matched_channels),
        )
    ]
    canonical = json.dumps(
        [item.model_dump(mode="json") for item in evidence],
        sort_keys=True,
        separators=(",", ":"),
    )
    bundle = PlanningEvidenceBundle(
        task_id=task.id,
        issue=context.issue,
        commit_sha=context.snapshot_sha,
        retrieval_run_id=retrieval.id,
        evidence_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
        evidence_truncated=False,
        evidence=evidence,
    )
    await store.persist_planning(
        bundle, analysis(), plan(), "ollama", "qwen3:8b"
    )
    return task, bundle, store


async def _clean(session, task_id) -> None:
    await session.rollback()
    await session.execute(delete(Task).where(Task.id == task_id))
    await session.commit()
