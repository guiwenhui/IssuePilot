"""Add M2 repository clone state and snapshots.

Revision ID: 20260814_02
Revises: 20260813_01
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260814_02"
down_revision: Union[str, None] = "20260813_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks", sa.Column("failure_code", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("failure_message", sa.Text(), nullable=True)
    )
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)
    op.create_table(
        "repository_snapshots",
        sa.Column(
            "task_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("tree_manifest", postgresql.JSONB(), nullable=False),
        sa.Column(
            "cloned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'created' "
            "WHERE status IN ('queued', 'cloning', 'cloned', 'failed')"
        )
    )
    op.drop_table("repository_snapshots")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_column("tasks", "failure_message")
    op.drop_column("tasks", "failure_code")
