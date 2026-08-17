"""Add M6 checkpointed planning approval business records.

Revision ID: 20260817_06
Revises: 20260817_05
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260817_06"
down_revision: Union[str, None] = "20260817_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "implementation_plans",
        sa.Column(
            "supersedes_plan_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "implementation_plans",
        sa.Column("revision_feedback", sa.Text(), nullable=True),
    )
    op.add_column(
        "implementation_plans",
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_implementation_plans_supersedes",
        "implementation_plans",
        "implementation_plans",
        ["supersedes_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_implementation_plans_one_proposed",
        "implementation_plans",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'proposed'"),
    )
    op.create_table(
        "planning_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "idempotency_key", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["planning_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["implementation_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "idempotency_key", name="uq_planning_decisions_key"
        ),
    )
    op.create_index(
        "ix_planning_decisions_status_created",
        "planning_decisions",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'waiting_approval' "
            "WHERE status IN ('decision_pending', 'revising', 'approved', "
            "'rejected', 'recovery_blocked')"
        )
    )
    op.drop_index(
        "ix_planning_decisions_status_created",
        table_name="planning_decisions",
    )
    op.drop_table("planning_decisions")
    op.drop_index(
        "uq_implementation_plans_one_proposed",
        table_name="implementation_plans",
    )
    op.drop_constraint(
        "fk_implementation_plans_supersedes",
        "implementation_plans",
        type_="foreignkey",
    )
    op.drop_column("implementation_plans", "decided_at")
    op.drop_column("implementation_plans", "revision_feedback")
    op.drop_column("implementation_plans", "supersedes_plan_id")
