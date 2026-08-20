"""Add M7 implementation, patch, and test evidence.

Revision ID: 20260817_07
Revises: 20260817_06
Create Date: 2026-08-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260817_07"
down_revision: Union[str, None] = "20260817_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "implementation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "planning_run_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column(
            "idempotency_key", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("base_commit", sa.String(length=40), nullable=False),
        sa.Column("graph_version", sa.String(length=32), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("llm_provider", sa.String(length=64), nullable=False),
        sa.Column("llm_model", sa.String(length=256), nullable=False),
        sa.Column(
            "checkpoint_thread_id", sa.String(length=128), nullable=False
        ),
        sa.Column("worktree_relpath", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["planning_run_id"], ["planning_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["implementation_plans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_implementation_runs_task"),
        sa.UniqueConstraint(
            "task_id", "idempotency_key", name="uq_implementation_runs_key"
        ),
    )
    op.create_index(
        "ix_implementation_runs_status_created",
        "implementation_runs",
        ["status", "created_at"],
    )
    op.create_table(
        "patch_artifacts",
        sa.Column(
            "implementation_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("unified_diff", sa.Text(), nullable=False),
        sa.Column("diff_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("insertions", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["implementation_run_id"],
            ["implementation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("implementation_run_id"),
    )
    op.create_table(
        "test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "implementation_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "expected_patch_sha256", sa.String(length=64), nullable=False
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("command_argv", postgresql.JSONB(), nullable=False),
        sa.Column("runner_image", sa.String(length=512), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column(
            "timed_out", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("output_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "output_truncated",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["implementation_run_id"],
            ["implementation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "implementation_run_id", name="uq_test_runs_implementation"
        ),
        sa.UniqueConstraint(
            "implementation_run_id",
            "idempotency_key",
            name="uq_test_runs_key",
        ),
    )
    op.create_index(
        "ix_test_runs_status_created",
        "test_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'approved' WHERE status IN "
            "('implementation_pending', 'generating_patch', 'patch_ready', "
            "'test_pending', 'testing', 'tested', 'test_failed')"
        )
    )
    op.drop_index("ix_test_runs_status_created", table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_table("patch_artifacts")
    op.drop_index(
        "ix_implementation_runs_status_created",
        table_name="implementation_runs",
    )
    op.drop_table("implementation_runs")
