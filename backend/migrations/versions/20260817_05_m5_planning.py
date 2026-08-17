"""Add M5 planning artifacts.

Revision ID: 20260817_05
Revises: 20260816_04
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260817_05"
down_revision: Union[str, None] = "20260816_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "planning_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "retrieval_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("graph_version", sa.String(length=32), nullable=False),
        sa.Column("llm_provider", sa.String(length=64), nullable=False),
        sa.Column("llm_model", sa.String(length=256), nullable=False),
        sa.Column(
            "analysis_prompt_version", sa.String(length=32), nullable=False
        ),
        sa.Column("plan_prompt_version", sa.String(length=32), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("evidence_truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["retrieval_run_id"],
            ["retrieval_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_planning_runs_task"),
        sa.UniqueConstraint(
            "retrieval_run_id", name="uq_planning_runs_retrieval"
        ),
    )
    op.create_table(
        "requirement_analyses",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", postgresql.JSONB(), nullable=False),
        sa.Column("constraints", postgresql.JSONB(), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False),
        sa.Column("affected_areas", postgresql.JSONB(), nullable=False),
        sa.Column("risks", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["planning_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "implementation_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=False),
        sa.Column("test_strategy", postgresql.JSONB(), nullable=False),
        sa.Column("risk_notes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["planning_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "version", name="uq_implementation_plans_run_version"
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'retrieved' "
            "WHERE status IN ('analyzing', 'waiting_approval')"
        )
    )
    op.drop_table("implementation_plans")
    op.drop_table("requirement_analyses")
    op.drop_table("planning_runs")
