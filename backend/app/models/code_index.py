import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
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


class CodeIndex(Base):
    __tablename__ = "code_indexes"

    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    python_version: Mapped[str] = mapped_column(String(32), nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parsed_file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol_count: Mapped[int] = mapped_column(Integer, nullable=False)
    import_count: Mapped[int] = mapped_column(Integer, nullable=False)
    test_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parse_error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CodeFile(Base):
    __tablename__ = "code_files"
    __table_args__ = (
        UniqueConstraint("task_id", "path", name="uq_code_files_task_path"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_indexes.task_id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(4096), nullable=False)
    module_name: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_test_file: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    parse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CodeSymbol(Base):
    __tablename__ = "code_symbols"
    __table_args__ = (
        Index("ix_code_symbols_file_qualified", "file_id", "qualified_name"),
        Index("ix_code_symbols_name", "name"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    qualified_name: Mapped[str] = mapped_column(String(2048), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decorators: Mapped[List[str]] = mapped_column(JSONB, nullable=False)
    is_async: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CodeImport(Base):
    __tablename__ = "code_imports"
    __table_args__ = (
        Index("ix_code_imports_file", "file_id"),
        Index("ix_code_imports_module", "module"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    module: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    imported_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    alias: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    relative_level: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    line: Mapped[int] = mapped_column(Integer, nullable=False)
