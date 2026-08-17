import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


JsonObjects = List[Dict[str, Any]]


class PlanningRun(Base):
    __tablename__ = "planning_runs"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_planning_runs_task"),
        UniqueConstraint(
            "retrieval_run_id", name="uq_planning_runs_retrieval"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    retrieval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(32), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(256), nullable=False)
    analysis_prompt_version: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    plan_prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RequirementAnalysis(Base):
    __tablename__ = "requirement_analyses"

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria: Mapped[JsonObjects] = mapped_column(
        JSONB, nullable=False
    )
    constraints: Mapped[JsonObjects] = mapped_column(JSONB, nullable=False)
    assumptions: Mapped[JsonObjects] = mapped_column(JSONB, nullable=False)
    affected_areas: Mapped[JsonObjects] = mapped_column(JSONB, nullable=False)
    risks: Mapped[JsonObjects] = mapped_column(JSONB, nullable=False)


class ImplementationPlan(Base):
    __tablename__ = "implementation_plans"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "version", name="uq_implementation_plans_run_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supersedes_plan_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("implementation_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_feedback: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    steps: Mapped[JsonObjects] = mapped_column(JSONB, nullable=False)
    test_strategy: Mapped[JsonObjects] = mapped_column(JSONB, nullable=False)
    risk_notes: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlanningDecision(Base):
    __tablename__ = "planning_decisions"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "idempotency_key", name="uq_planning_decisions_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("implementation_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    failure_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
