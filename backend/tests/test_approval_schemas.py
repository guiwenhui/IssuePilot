from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.planning import (
    PlanningDecisionAction,
    PlanningDecisionCreate,
    PlanningDecisionResponse,
)


def test_decision_request_accepts_approve_without_comment() -> None:
    payload = PlanningDecisionCreate(
        action=PlanningDecisionAction.APPROVE,
        expected_plan_version=1,
        idempotency_key=uuid4(),
    )

    assert payload.comment is None


@pytest.mark.parametrize(
    "action",
    [PlanningDecisionAction.REQUEST_CHANGES, PlanningDecisionAction.REJECT],
)
def test_decision_request_requires_reason_for_change_or_reject(action) -> None:
    with pytest.raises(ValidationError):
        PlanningDecisionCreate(
            action=action,
            expected_plan_version=1,
            idempotency_key=uuid4(),
        )


def test_decision_request_strips_and_bounds_comment() -> None:
    payload = PlanningDecisionCreate(
        action=PlanningDecisionAction.REQUEST_CHANGES,
        expected_plan_version=2,
        idempotency_key=uuid4(),
        comment="  focus the regression test  ",
    )

    assert payload.comment == "focus the regression test"
    with pytest.raises(ValidationError):
        PlanningDecisionCreate(
            action=PlanningDecisionAction.REJECT,
            expected_plan_version=1,
            idempotency_key=uuid4(),
            comment="x" * 2001,
        )


def test_decision_response_is_strict_and_versioned() -> None:
    now = datetime.now(timezone.utc)
    response = PlanningDecisionResponse(
        decision_id=uuid4(),
        task_id=uuid4(),
        action=PlanningDecisionAction.APPROVE,
        status="pending",
        plan_version=1,
        task_status="decision_pending",
        comment=None,
        created_at=now,
        applied_at=None,
    )

    assert response.plan_version == 1
    assert response.status == "pending"
