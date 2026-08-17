import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, literal_column, select

from app.agents.planning_state import PlanningEvidenceBundle
from app.db.session import session_factory
from app.models.code_index import CodeFile, CodeIndex
from app.models.planning import (
    ImplementationPlan,
    PlanningRun,
    RequirementAnalysis,
)
from app.models.repository_snapshot import RepositorySnapshot
from app.models.retrieval import CodeChunk, RetrievalResult, RetrievalRun
from app.models.task import Task
from app.schemas.planning import (
    AcceptanceCriterion,
    AffectedArea,
    EvidenceItem,
    ImplementationPlanDraft,
    PlanStep,
    RequirementAnalysisDraft,
    TestStrategyItem as StrategyItem,
)
from app.schemas.task import TaskStatus
from app.services.planning_store import SqlPlanningStore
from app.services.repository_service import WorkspaceInconsistentError


def analysis() -> RequirementAnalysisDraft:
    return RequirementAnalysisDraft(
        summary="Handle None without changing non-null escaping.",
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC1",
                description="None becomes empty output.",
                evidence_ranks=[1],
            )
        ],
        constraints=[],
        assumptions=[],
        affected_areas=[
            AffectedArea(
                path="src/escape.py",
                symbol="escape_silent",
                reason="Existing implementation point.",
                evidence_ranks=[1],
            )
        ],
        risks=[],
    )


def plan() -> ImplementationPlanDraft:
    return ImplementationPlanDraft(
        steps=[
            PlanStep(
                order=1,
                title="Adjust nullable behavior",
                description="Preserve all non-null inputs.",
                paths=["src/escape.py"],
                symbols=["escape_silent"],
                evidence_ranks=[1],
            )
        ],
        test_strategy=[
            StrategyItem(
                description="Run focused regression coverage.",
                target_paths=["src/escape.py"],
                evidence_ranks=[1],
            )
        ],
        risk_notes=[],
    )


@pytest.mark.asyncio
async def test_store_atomically_persists_and_reads_planning_artifacts() -> None:
    async with session_factory() as session:
        task, retrieval = await _seed_context(session)
        task_id = task.id
        store = SqlPlanningStore(session)
        context = await store.load_context(task_id)
        item = context.evidence[0]
        bundle = PlanningEvidenceBundle(
            task_id=task_id,
            issue=context.issue,
            commit_sha=context.snapshot_sha,
            retrieval_run_id=retrieval.id,
            evidence_sha256="e" * 64,
            evidence_truncated=False,
            evidence=[
                EvidenceItem(
                    rank=item.rank,
                    path=item.path,
                    symbol=item.symbol,
                    kind=item.kind,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    snippet=item.content,
                    matched_channels=list(item.matched_channels),
                )
            ],
        )

        try:
            run_id = await store.persist_planning(
                bundle, analysis(), plan(), "ollama", "qwen3:8b"
            )

            await session.refresh(task)
            response = await store.load_planning(task_id)
            assert task.status == TaskStatus.WAITING_APPROVAL
            assert response is not None
            assert response.run.id == run_id
            assert response.run.model == "qwen3:8b"
            assert response.analysis.affected_areas[0].path == "src/escape.py"
            assert response.plan.version == 1
            assert await _count(session, PlanningRun, task_id) == 1
            assert await _count_by_run(session, RequirementAnalysis, run_id) == 1
            assert await _count_by_run(session, ImplementationPlan, run_id) == 1
        finally:
            await session.rollback()
            await session.execute(delete(Task).where(Task.id == task_id))
            await session.commit()


@pytest.mark.asyncio
async def test_store_rolls_back_when_retrieval_context_changed() -> None:
    async with session_factory() as session:
        task, _ = await _seed_context(session)
        task_id = task.id
        store = SqlPlanningStore(session)
        context = await store.load_context(task_id)
        item = context.evidence[0]
        bundle = PlanningEvidenceBundle(
            task_id=task_id,
            issue=context.issue,
            commit_sha=context.snapshot_sha,
            retrieval_run_id=uuid4(),
            evidence_sha256="e" * 64,
            evidence_truncated=False,
            evidence=[
                EvidenceItem(
                    rank=item.rank,
                    path=item.path,
                    symbol=item.symbol,
                    kind=item.kind,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    snippet=item.content,
                    matched_channels=list(item.matched_channels),
                )
            ],
        )

        try:
            with pytest.raises(WorkspaceInconsistentError):
                await store.persist_planning(
                    bundle, analysis(), plan(), "ollama", "qwen3:8b"
                )
            assert await _count(session, PlanningRun, task_id) == 0
            await session.refresh(task)
            assert task.status == TaskStatus.ANALYZING
        finally:
            await session.rollback()
            await session.execute(delete(Task).where(Task.id == task_id))
            await session.commit()


async def _seed_context(session) -> tuple[Task, RetrievalRun]:
    task = Task(
        id=uuid4(),
        repository_url="https://github.com/example/project.git",
        issue_text="Fix nullable escaping",
        status=TaskStatus.ANALYZING,
    )
    session.add(task)
    await session.flush()
    snapshot = RepositorySnapshot(
        task_id=task.id,
        canonical_url=task.repository_url,
        commit_sha="a" * 40,
        file_count=1,
        total_bytes=50,
        tree_manifest=[],
    )
    index = CodeIndex(
        task_id=task.id,
        commit_sha="a" * 40,
        parser_version="py-ast-v1",
        python_version="3.13.15",
        file_count=1,
        parsed_file_count=1,
        symbol_count=1,
        import_count=0,
        test_count=0,
        parse_error_count=0,
    )
    session.add_all([snapshot, index])
    await session.flush()
    code_file = CodeFile(
        id=uuid4(),
        task_id=task.id,
        path="src/escape.py",
        module_name="src.escape",
        source_sha256="b" * 64,
        line_count=2,
        size_bytes=50,
        is_test_file=False,
        parse_status="parsed",
    )
    session.add(code_file)
    await session.flush()
    chunk = CodeChunk(
        id=uuid4(),
        task_id=task.id,
        file_id=code_file.id,
        symbol_id=None,
        commit_sha="a" * 40,
        path=code_file.path,
        kind="function",
        symbol_name="escape_silent",
        start_line=1,
        end_line=2,
        content="def escape_silent(value): return value",
        content_sha256=hashlib.sha256(b"escape").hexdigest(),
        search_vector=func.to_tsvector(
            literal_column("'simple'"), "escape silent"
        ),
        embedding=[0.0] * 1024,
    )
    retrieval = RetrievalRun(
        id=uuid4(),
        task_id=task.id,
        commit_sha="a" * 40,
        query=task.issue_text,
        query_sha256=hashlib.sha256(task.issue_text.encode()).hexdigest(),
        embedding_provider="ollama",
        embedding_model="qwen3-embedding:0.6b",
        embedding_dimensions=1024,
        chunker_version="python-symbol-v1",
        fusion_version="rrf-v1",
        reranker_version="rules-v1",
        chunk_count=1,
        keyword_candidate_count=1,
        symbol_candidate_count=1,
        vector_candidate_count=1,
        result_count=1,
    )
    session.add_all([chunk, retrieval])
    await session.flush()
    session.add(
        RetrievalResult(
            run_id=retrieval.id,
            rank=1,
            chunk_id=chunk.id,
            rrf_score=0.1,
            rerank_score=0.2,
            keyword_rank=1,
            symbol_rank=1,
            vector_rank=1,
            keyword_score=1.0,
            symbol_score=1.0,
            vector_score=1.0,
            matched_channels=["keyword", "symbol", "vector"],
        )
    )
    await session.commit()
    return task, retrieval


async def _count(session, model, task_id) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.task_id == task_id)
        )
    )


async def _count_by_run(session, model, run_id) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(model).where(model.run_id == run_id)
        )
    )
