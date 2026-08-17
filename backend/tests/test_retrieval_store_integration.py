import hashlib
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.db.session import session_factory
from app.models.code_index import CodeFile, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.retrieval import CodeChunk, RetrievalResult, RetrievalRun
from app.models.task import Task
from app.retrieval.chunker import CodeChunkDraft
from app.schemas.task import TaskStatus
from app.services.retrieval_service import (
    RetrievalContext,
    RetrievalPersistenceError,
)
from app.services.retrieval_store import SqlRetrievalStore


def embedding(first: float, second: float) -> list[float]:
    return [first, second] + [0.0] * 1022


@pytest.mark.asyncio
async def test_integrity_error_is_not_reported_as_database_unavailable() -> None:
    session = Mock()
    session.rollback = AsyncMock()
    store = SqlRetrievalStore(session)
    store._replace_chunks = AsyncMock(  # type: ignore[method-assign]
        side_effect=IntegrityError("insert", {}, ValueError("duplicate"))
    )
    context = Mock()

    with pytest.raises(RetrievalPersistenceError):
        await store.persist_retrieval(
            context,
            [],
            [],
            [0.0] * 1024,
            "fake",
            "fake-v1",
            1024,
            50,
            10,
        )

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_persists_pgvector_lanes_and_rank_evidence() -> None:
    async with session_factory() as session:
        task = Task(
            repository_url="https://github.com/example/project.git",
            issue_text="Fix escape html output",
            status=TaskStatus.RETRIEVING,
        )
        session.add(task)
        await session.flush()
        task_id = task.id
        snapshot = RepositorySnapshot(
            task_id=task.id,
            canonical_url=task.repository_url,
            commit_sha="a" * 40,
            file_count=2,
            total_bytes=100,
            tree_manifest=[],
        )
        index = CodeIndex(
            task_id=task.id,
            commit_sha="a" * 40,
            parser_version="py-ast-v1",
            python_version="3.9.6",
            file_count=2,
            parsed_file_count=2,
            symbol_count=1,
            import_count=0,
            test_count=0,
            parse_error_count=0,
        )
        session.add_all([snapshot, index])
        await session.flush()
        escape_file = CodeFile(
            id=uuid4(),
            task_id=task.id,
            path="src/escape.py",
            module_name="src.escape",
            source_sha256="b" * 64,
            line_count=2,
            size_bytes=30,
            is_test_file=False,
            parse_status="parsed",
        )
        parser_file = CodeFile(
            id=uuid4(),
            task_id=task.id,
            path="src/parser.py",
            module_name="src.parser",
            source_sha256="c" * 64,
            line_count=2,
            size_bytes=30,
            is_test_file=False,
            parse_status="parsed",
        )
        session.add_all([escape_file, parser_file])
        await session.flush()
        symbol = CodeSymbol(
            id=uuid4(),
            file_id=escape_file.id,
            kind="function",
            name="escape",
            qualified_name="escape",
            start_line=1,
            end_line=2,
            signature="escape(value)",
            decorators=[],
            is_async=False,
            is_test=False,
            is_fixture=False,
        )
        session.add(symbol)
        await session.commit()

        chunks = [
            CodeChunkDraft(
                file_id=escape_file.id,
                symbol_id=symbol.id,
                path=escape_file.path,
                kind="function",
                symbol_name="escape",
                start_line=1,
                end_line=2,
                content="def escape(value):\n    return html(value)",
                content_sha256=hashlib.sha256(b"escape").hexdigest(),
                searchable_text="src/escape.py escape html output",
            ),
            CodeChunkDraft(
                file_id=parser_file.id,
                symbol_id=None,
                path=parser_file.path,
                kind="module",
                symbol_name=None,
                start_line=1,
                end_line=2,
                content="VALUE = parse()",
                content_sha256=hashlib.sha256(b"parser").hexdigest(),
                searchable_text="src/parser.py parser value",
            ),
        ]
        context = RetrievalContext(
            task, snapshot, index, [escape_file, parser_file], [symbol]
        )
        store = SqlRetrievalStore(session)

        try:
            await store.persist_retrieval(
                context,
                chunks,
                [embedding(1.0, 0.0), embedding(0.0, 1.0)],
                embedding(0.0, 1.0),
                "fake",
                "fake-v1",
                1024,
                50,
                10,
            )

            await session.refresh(task)
            run = await session.scalar(
                select(RetrievalRun).where(RetrievalRun.task_id == task.id)
            )
            results = list(
                (
                    await session.execute(
                        select(RetrievalResult)
                        .where(RetrievalResult.run_id == run.id)
                        .order_by(RetrievalResult.rank)
                    )
                )
                .scalars()
                .all()
            )
            assert task.status == TaskStatus.RETRIEVED
            assert await session.scalar(
                select(func.count())
                .select_from(CodeChunk)
                .where(CodeChunk.task_id == task.id)
            ) == 2
            assert run.chunk_count == 2
            assert run.chunker_version == "python-symbol-v2"
            assert run.keyword_candidate_count >= 1
            assert run.symbol_candidate_count == 1
            assert run.vector_candidate_count == 2
            assert len(results) == 2
            assert set(results[0].matched_channels) >= {"keyword", "symbol"}
            assert results[0].symbol_rank == 1
            assert results[0].symbol_score == 3.0
            response = await store.load_retrieval(task.id)
            assert response is not None
            assert response.results[0].path == "src/escape.py"
            assert response.results[0].channel_scores["symbol"] == 3.0
        finally:
            await session.rollback()
            await session.execute(delete(Task).where(Task.id == task_id))
            await session.commit()
