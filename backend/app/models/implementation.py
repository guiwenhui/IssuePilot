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


class ImplementationRun(Base):
    __tablename__ = "implementation_runs"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_implementation_runs_task"),
        UniqueConstraint(
            "task_id",
            "idempotency_key",
            name="uq_implementation_runs_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    planning_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("implementation_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    base_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(256), nullable=False)
    checkpoint_thread_id: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    worktree_relpath: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    failure_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PatchArtifact(Base):
    __tablename__ = "patch_artifacts"

    implementation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("implementation_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    unified_diff: Mapped[str] = mapped_column(Text, nullable=False)
    diff_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_manifest: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    insertions: Mapped[int] = mapped_column(Integer, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TestRun(Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        UniqueConstraint(
            "implementation_run_id",
            name="uq_test_runs_implementation",
        ),
        UniqueConstraint(
            "implementation_run_id",
            "idempotency_key",
            name="uq_test_runs_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    implementation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("implementation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    idempotency_key: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), nullable=False
    )
    expected_patch_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    command_argv: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    runner_image: Mapped[str] = mapped_column(String(512), nullable=False)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    output_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
