import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CodeChunk(Base):
    __tablename__ = "code_chunks"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "path",
            "start_line",
            "end_line",
            "content_sha256",
            name="uq_code_chunks_location_content",
        ),
        Index("ix_code_chunks_task_path", "task_id", "path"),
        Index("ix_code_chunks_symbol", "symbol_id"),
        Index("ix_code_chunks_search", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_indexes.task_id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False
    )
    symbol_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(String(4096), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol_name: Mapped[Optional[str]] = mapped_column(
        String(2048), nullable=True
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    embedding: Mapped[List[float]] = mapped_column(Vector(1024), nullable=False)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_retrieval_runs_task"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fusion_version: Mapped[str] = mapped_column(String(32), nullable=False)
    reranker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    keyword_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "chunk_id", name="uq_retrieval_results_run_chunk"
        ),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_chunks.id", ondelete="CASCADE"), nullable=False
    )
    rrf_score: Mapped[float] = mapped_column(Float, nullable=False)
    rerank_score: Mapped[float] = mapped_column(Float, nullable=False)
    keyword_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symbol_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vector_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    keyword_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    symbol_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vector_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    matched_channels: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
