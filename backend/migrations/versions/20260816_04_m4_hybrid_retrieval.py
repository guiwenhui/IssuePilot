"""Add M4 hybrid retrieval artifacts and pgvector.

Revision ID: 20260816_04
Revises: 20260814_03
Create Date: 2026-08-16
"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260816_04"
down_revision: Union[str, None] = "20260814_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "code_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("symbol_name", sa.String(length=2048), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["code_indexes.task_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["code_files.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["symbol_id"], ["code_symbols.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "path",
            "start_line",
            "end_line",
            "content_sha256",
            name="uq_code_chunks_location_content",
        ),
    )
    op.create_index(
        "ix_code_chunks_task_path", "code_chunks", ["task_id", "path"]
    )
    op.create_index("ix_code_chunks_symbol", "code_chunks", ["symbol_id"])
    op.create_index(
        "ix_code_chunks_search",
        "code_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_table(
        "retrieval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=256), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(length=32), nullable=False),
        sa.Column("fusion_version", sa.String(length=32), nullable=False),
        sa.Column("reranker_version", sa.String(length=32), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("keyword_candidate_count", sa.Integer(), nullable=False),
        sa.Column("symbol_candidate_count", sa.Integer(), nullable=False),
        sa.Column("vector_candidate_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_retrieval_runs_task"),
    )
    op.create_table(
        "retrieval_results",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rrf_score", sa.Float(), nullable=False),
        sa.Column("rerank_score", sa.Float(), nullable=False),
        sa.Column("keyword_rank", sa.Integer(), nullable=True),
        sa.Column("symbol_rank", sa.Integer(), nullable=True),
        sa.Column("vector_rank", sa.Integer(), nullable=True),
        sa.Column("keyword_score", sa.Float(), nullable=True),
        sa.Column("symbol_score", sa.Float(), nullable=True),
        sa.Column("vector_score", sa.Float(), nullable=True),
        sa.Column("matched_channels", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["retrieval_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["code_chunks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("run_id", "rank"),
        sa.UniqueConstraint(
            "run_id", "chunk_id", name="uq_retrieval_results_run_chunk"
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tasks SET status = 'indexed' "
            "WHERE status IN ('retrieving', 'retrieved')"
        )
    )
    op.drop_table("retrieval_results")
    op.drop_table("retrieval_runs")
    op.drop_index("ix_code_chunks_search", table_name="code_chunks")
    op.drop_index("ix_code_chunks_symbol", table_name="code_chunks")
    op.drop_index("ix_code_chunks_task_path", table_name="code_chunks")
    op.drop_table("code_chunks")
    op.execute("DROP EXTENSION IF EXISTS vector")
