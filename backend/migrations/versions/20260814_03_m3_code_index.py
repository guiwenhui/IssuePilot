"""Add M3 structured Python code indexes.

Revision ID: 20260814_03
Revises: 20260814_02
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260814_03"
down_revision: Union[str, None] = "20260814_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "code_indexes",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("python_version", sa.String(length=32), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("parsed_file_count", sa.Integer(), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("import_count", sa.Integer(), nullable=False),
        sa.Column("test_count", sa.Integer(), nullable=False),
        sa.Column("parse_error_count", sa.Integer(), nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_table(
        "code_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("module_name", sa.String(length=2048), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("is_test_file", sa.Boolean(), nullable=False),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["task_id"], ["code_indexes.task_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "path", name="uq_code_files_task_path"),
    )
    op.create_table(
        "code_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("qualified_name", sa.String(length=2048), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("decorators", postgresql.JSONB(), nullable=False),
        sa.Column("is_async", sa.Boolean(), nullable=False),
        sa.Column("is_test", sa.Boolean(), nullable=False),
        sa.Column("is_fixture", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["code_files.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["code_symbols.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_code_symbols_file_qualified",
        "code_symbols",
        ["file_id", "qualified_name"],
        unique=False,
    )
    op.create_index(
        "ix_code_symbols_name", "code_symbols", ["name"], unique=False
    )
    op.create_table(
        "code_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("module", sa.String(length=2048), nullable=True),
        sa.Column("imported_name", sa.String(length=512), nullable=True),
        sa.Column("alias", sa.String(length=512), nullable=True),
        sa.Column("relative_level", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=2048), nullable=True),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["code_files.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_imports_file", "code_imports", ["file_id"])
    op.create_index("ix_code_imports_module", "code_imports", ["module"])


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'cloned' "
            "WHERE status IN ('indexing', 'indexed')"
        )
    )
    op.drop_index("ix_code_imports_module", table_name="code_imports")
    op.drop_index("ix_code_imports_file", table_name="code_imports")
    op.drop_table("code_imports")
    op.drop_index("ix_code_symbols_name", table_name="code_symbols")
    op.drop_index(
        "ix_code_symbols_file_qualified", table_name="code_symbols"
    )
    op.drop_table("code_symbols")
    op.drop_table("code_files")
    op.drop_table("code_indexes")
