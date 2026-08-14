from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RepositorySnapshot(Base):
    __tablename__ = "repository_snapshots"

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tree_manifest: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB, nullable=False
    )
    cloned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
