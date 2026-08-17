from sqlalchemy.dialects.postgresql import JSONB

from app.models.planning import (
    ImplementationPlan,
    PlanningRun,
    RequirementAnalysis,
)


def test_planning_artifacts_have_stable_uniqueness_constraints() -> None:
    run_constraints = {
        constraint.name for constraint in PlanningRun.__table__.constraints
    }
    plan_constraints = {
        constraint.name
        for constraint in ImplementationPlan.__table__.constraints
    }

    assert "uq_planning_runs_task" in run_constraints
    assert "uq_planning_runs_retrieval" in run_constraints
    assert "uq_implementation_plans_run_version" in plan_constraints


def test_planning_structured_fields_use_jsonb() -> None:
    analysis_fields = (
        "acceptance_criteria",
        "constraints",
        "assumptions",
        "affected_areas",
        "risks",
    )
    plan_fields = ("steps", "test_strategy", "risk_notes")

    for field in analysis_fields:
        assert isinstance(RequirementAnalysis.__table__.c[field].type, JSONB)
    for field in plan_fields:
        assert isinstance(ImplementationPlan.__table__.c[field].type, JSONB)
