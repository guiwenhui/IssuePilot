from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_planning_service
from app.main import create_app
from app.schemas.planning import (
    AcceptanceCriterion,
    AffectedArea,
    ImplementationPlanDraft,
    PlanStep,
    PlanningAnalysis,
    PlanningPlan,
    PlanningResponse,
    PlanningRunMetadata,
    TestStrategyItem as StrategyItem,
)
from app.services.planning_service import PlanningNotReadyError
from app.services.repository_service import WorkspaceInconsistentError
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError


class StubPlanningService:
    def __init__(self, task_id: UUID) -> None:
        self.error: Optional[Exception] = None
        now = datetime.now(timezone.utc)
        self.response = PlanningResponse(
            task_id=task_id,
            commit_sha="a" * 40,
            run=PlanningRunMetadata(
                id=uuid4(),
                graph_version="planning-graph-v1",
                provider="ollama",
                model="qwen3:8b",
                analysis_prompt_version="analysis-v1",
                plan_prompt_version="plan-v1",
                evidence_count=2,
                evidence_truncated=False,
                created_at=now,
            ),
            analysis=PlanningAnalysis(
                summary="Handle nullable escaping.",
                acceptance_criteria=[
                    AcceptanceCriterion(
                        id="AC1",
                        description="None becomes empty output.",
                        evidence_ranks=[1],
                    )
                ],
                constraints=[],
                assumptions=[],
                affected_areas=[
                    AffectedArea(
                        path="src/module.py",
                        symbol="escape_silent",
                        reason="Existing implementation point.",
                        evidence_ranks=[1],
                    )
                ],
                risks=[],
            ),
            plan=PlanningPlan(
                version=1,
                status="proposed",
                steps=[
                    PlanStep(
                        order=1,
                        title="Adjust behavior",
                        description="Preserve other inputs.",
                        paths=["src/module.py"],
                        symbols=["escape_silent"],
                        evidence_ranks=[1],
                    )
                ],
                test_strategy=[
                    StrategyItem(
                        description="Run focused tests.",
                        target_paths=["tests/test_module.py"],
                        evidence_ranks=[2],
                    )
                ],
                risk_notes=[],
                created_at=now,
            ),
        )

    async def get_planning(self, task_id: UUID) -> PlanningResponse:
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
async def planning_client() -> AsyncIterator[
    tuple[AsyncClient, StubPlanningService, UUID]
]:
    task_id = uuid4()
    service = StubPlanningService(task_id)
    app = create_app()
    app.dependency_overrides[get_planning_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, service, task_id


@pytest.mark.asyncio
async def test_planning_returns_structured_plan_and_disables_cache(
    planning_client: tuple[AsyncClient, StubPlanningService, UUID],
) -> None:
    client, _, task_id = planning_client

    response = await client.get(f"/api/v1/tasks/{task_id}/planning")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["plan"]["status"] == "proposed"
    assert response.json()["run"]["model"] == "qwen3:8b"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "expected_code"),
    [
        (PlanningNotReadyError(), 409, "PLANNING_NOT_READY"),
        (WorkspaceInconsistentError(), 409, "WORKSPACE_INCONSISTENT"),
        (TaskNotFoundError(), 404, "TASK_NOT_FOUND"),
        (DatabaseUnavailableError(), 503, "DATABASE_UNAVAILABLE"),
    ],
)
async def test_planning_returns_structured_errors(
    planning_client: tuple[AsyncClient, StubPlanningService, UUID],
    error: Exception,
    status_code: int,
    expected_code: str,
) -> None:
    client, service, task_id = planning_client
    service.error = error

    response = await client.get(f"/api/v1/tasks/{task_id}/planning")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == expected_code


@pytest.mark.asyncio
async def test_planning_rejects_invalid_uuid(
    planning_client: tuple[AsyncClient, StubPlanningService, UUID],
) -> None:
    client, _, _ = planning_client

    response = await client.get("/api/v1/tasks/not-a-uuid/planning")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
