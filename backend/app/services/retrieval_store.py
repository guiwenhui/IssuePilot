import hashlib
import uuid
from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import delete, func, literal_column, select
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_index import CodeFile, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.retrieval import CodeChunk, RetrievalResult, RetrievalRun
from app.models.task import Task
from app.retrieval.chunker import CHUNKER_VERSION, CodeChunkDraft
from app.retrieval.ranking import (
    FUSION_VERSION,
    RERANKER_VERSION,
    Candidate,
    LaneHit,
    RankedCandidate,
    fuse_and_rerank,
    query_tokens,
    score_symbol_candidates,
)
from app.schemas.task import TaskStatus
from app.schemas.retrieval import (
    RetrievalCounts,
    RetrievalEmbedding,
    RetrievalResponse,
    RetrievalResultItem,
    RetrievalVersions,
)
from app.services.repository_service import WorkspaceInconsistentError
from app.services.retrieval_service import (
    RetrievalContext,
    RetrievalPersistenceError,
)
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError


class SqlRetrievalStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_context(self, task_id: UUID) -> RetrievalContext:
        try:
            task = await self._session.get(Task, task_id)
            if task is None:
                raise TaskNotFoundError()
            snapshot = await self._session.get(RepositorySnapshot, task_id)
            index = await self._session.get(CodeIndex, task_id)
            if snapshot is None or index is None:
                raise WorkspaceInconsistentError()
            files, symbols = await self._load_index_records(task_id)
            return RetrievalContext(task, snapshot, index, files, symbols)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error

    async def set_status(
        self,
        task: Task,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> None:
        task.status = status
        task.failure_code = failure_code
        task.failure_message = failure_message
        try:
            await self._session.commit()
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def load_retrieval(
        self, task_id: UUID
    ) -> Optional[RetrievalResponse]:
        try:
            task = await self._session.get(Task, task_id)
            if task is None:
                raise TaskNotFoundError()
            run = await self._session.scalar(
                select(RetrievalRun).where(RetrievalRun.task_id == task_id)
            )
            if run is None:
                return None
            rows = (
                await self._session.execute(
                    select(RetrievalResult, CodeChunk)
                    .join(CodeChunk, CodeChunk.id == RetrievalResult.chunk_id)
                    .where(RetrievalResult.run_id == run.id)
                    .order_by(RetrievalResult.rank)
                )
            ).all()
            return _retrieval_response(run, rows)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error

    async def persist_retrieval(
        self,
        context: RetrievalContext,
        chunks: Sequence[CodeChunkDraft],
        embeddings: Sequence[Sequence[float]],
        query_embedding: Sequence[float],
        provider_name: str,
        provider_model: str,
        provider_dimensions: int,
        candidate_limit: int,
        result_limit: int,
        success_status: TaskStatus = TaskStatus.RETRIEVED,
    ) -> None:
        _validate_vectors(chunks, embeddings, query_embedding, provider_dimensions)
        try:
            records = await self._replace_chunks(context, chunks, embeddings)
            lanes = await self._recall(
                context, records, query_embedding, candidate_limit
            )
            ranked = fuse_and_rerank(
                lanes, context.task.issue_text, result_limit
            )
            await self._add_run_and_results(
                context,
                records,
                lanes,
                ranked,
                provider_name,
                provider_model,
                provider_dimensions,
            )
            context.task.status = success_status
            context.task.failure_code = None
            context.task.failure_message = None
            await self._session.commit()
        except (
            DisconnectionError,
            InterfaceError,
            OperationalError,
            SQLAlchemyTimeoutError,
            OSError,
        ) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error
        except SQLAlchemyError as error:
            await self._session.rollback()
            raise RetrievalPersistenceError() from error
        except Exception:
            await self._session.rollback()
            raise

    async def _load_index_records(
        self, task_id: UUID
    ) -> Tuple[List[CodeFile], List[CodeSymbol]]:
        file_result = await self._session.execute(
            select(CodeFile)
            .where(CodeFile.task_id == task_id)
            .order_by(CodeFile.path)
        )
        files = list(file_result.scalars().all())
        if not files:
            return [], []
        symbol_result = await self._session.execute(
            select(CodeSymbol)
            .where(CodeSymbol.file_id.in_([item.id for item in files]))
            .order_by(CodeSymbol.start_line, CodeSymbol.qualified_name)
        )
        return files, list(symbol_result.scalars().all())

    async def _replace_chunks(
        self,
        context: RetrievalContext,
        drafts: Sequence[CodeChunkDraft],
        embeddings: Sequence[Sequence[float]],
    ) -> List[CodeChunk]:
        await self._session.execute(
            delete(RetrievalRun).where(RetrievalRun.task_id == context.task.id)
        )
        await self._session.execute(
            delete(CodeChunk).where(CodeChunk.task_id == context.task.id)
        )
        records = [
            _chunk_record(context, draft, embedding)
            for draft, embedding in zip(drafts, embeddings)
        ]
        self._session.add_all(records)
        await self._session.flush()
        return records

    async def _recall(
        self,
        context: RetrievalContext,
        records: Sequence[CodeChunk],
        query_embedding: Sequence[float],
        limit: int,
    ) -> Dict[str, List[LaneHit]]:
        candidates = _candidate_map(records, context.files)
        keyword = await self._keyword_lane(
            context.task.id, context.task.issue_text, candidates, limit
        )
        vector = await self._vector_lane(
            context.task.id, query_embedding, candidates, limit
        )
        symbol = score_symbol_candidates(
            list(candidates.values()), context.task.issue_text, limit
        )
        return {"keyword": keyword, "symbol": symbol, "vector": vector}

    async def _keyword_lane(
        self,
        task_id: UUID,
        query: str,
        candidates: Dict[UUID, Candidate],
        limit: int,
    ) -> List[LaneHit]:
        terms = query_tokens(query)
        query_text = " OR ".join(terms) if terms else query
        search_query = func.websearch_to_tsquery(
            literal_column("'simple'"), query_text
        )
        score = func.ts_rank_cd(CodeChunk.search_vector, search_query)
        result = await self._session.execute(
            select(CodeChunk.id, score.label("score"))
            .where(CodeChunk.task_id == task_id)
            .where(CodeChunk.search_vector.op("@@")(search_query))
            .order_by(score.desc(), CodeChunk.path, CodeChunk.start_line, CodeChunk.id)
            .limit(limit)
        )
        return [
            LaneHit(candidates[row.id], float(row.score)) for row in result.all()
        ]

    async def _vector_lane(
        self,
        task_id: UUID,
        query_embedding: Sequence[float],
        candidates: Dict[UUID, Candidate],
        limit: int,
    ) -> List[LaneHit]:
        distance = CodeChunk.embedding.cosine_distance(list(query_embedding))
        score = 1.0 - distance
        result = await self._session.execute(
            select(CodeChunk.id, score.label("score"))
            .where(CodeChunk.task_id == task_id)
            .order_by(distance, CodeChunk.path, CodeChunk.start_line, CodeChunk.id)
            .limit(limit)
        )
        return [
            LaneHit(candidates[row.id], float(row.score)) for row in result.all()
        ]

    async def _add_run_and_results(
        self,
        context: RetrievalContext,
        records: Sequence[CodeChunk],
        lanes: Dict[str, List[LaneHit]],
        ranked: Sequence[RankedCandidate],
        provider_name: str,
        provider_model: str,
        provider_dimensions: int,
    ) -> None:
        run = _run_record(
            context,
            len(records),
            lanes,
            len(ranked),
            provider_name,
            provider_model,
            provider_dimensions,
        )
        self._session.add(run)
        await self._session.flush()
        self._session.add_all([_result_record(run.id, item) for item in ranked])


def _validate_vectors(
    chunks: Sequence[CodeChunkDraft],
    embeddings: Sequence[Sequence[float]],
    query_embedding: Sequence[float],
    dimensions: int,
) -> None:
    if len(chunks) != len(embeddings) or len(query_embedding) != dimensions:
        raise ValueError("embedding count or dimensions do not match")
    if any(len(item) != dimensions for item in embeddings):
        raise ValueError("document embedding dimensions do not match")


def _chunk_record(
    context: RetrievalContext,
    draft: CodeChunkDraft,
    embedding: Sequence[float],
) -> CodeChunk:
    return CodeChunk(
        id=uuid.uuid4(),
        task_id=context.task.id,
        file_id=draft.file_id,
        symbol_id=draft.symbol_id,
        commit_sha=context.snapshot.commit_sha,
        path=draft.path,
        kind=draft.kind,
        symbol_name=draft.symbol_name,
        start_line=draft.start_line,
        end_line=draft.end_line,
        content=draft.content,
        content_sha256=draft.content_sha256,
        search_vector=func.to_tsvector(
            literal_column("'simple'"), draft.searchable_text
        ),
        embedding=list(embedding),
    )


def _candidate_map(
    chunks: Sequence[CodeChunk], files: Sequence[CodeFile]
) -> Dict[UUID, Candidate]:
    test_files = {item.id: item.is_test_file for item in files}
    return {
        item.id: Candidate(
            chunk_id=item.id,
            path=item.path,
            start_line=item.start_line,
            end_line=item.end_line,
            kind=item.kind,
            symbol_name=item.symbol_name,
            is_test=test_files.get(item.file_id, False),
        )
        for item in chunks
    }


def _run_record(
    context: RetrievalContext,
    chunk_count: int,
    lanes: Dict[str, List[LaneHit]],
    result_count: int,
    provider_name: str,
    provider_model: str,
    provider_dimensions: int,
) -> RetrievalRun:
    query = context.task.issue_text
    return RetrievalRun(
        id=uuid.uuid4(),
        task_id=context.task.id,
        commit_sha=context.snapshot.commit_sha,
        query=query,
        query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
        embedding_provider=provider_name,
        embedding_model=provider_model,
        embedding_dimensions=provider_dimensions,
        chunker_version=CHUNKER_VERSION,
        fusion_version=FUSION_VERSION,
        reranker_version=RERANKER_VERSION,
        chunk_count=chunk_count,
        keyword_candidate_count=len(lanes["keyword"]),
        symbol_candidate_count=len(lanes["symbol"]),
        vector_candidate_count=len(lanes["vector"]),
        result_count=result_count,
    )


def _result_record(run_id: UUID, item: RankedCandidate) -> RetrievalResult:
    return RetrievalResult(
        run_id=run_id,
        rank=item.rank,
        chunk_id=item.candidate.chunk_id,
        rrf_score=item.rrf_score,
        rerank_score=item.rerank_score,
        keyword_rank=item.channel_ranks.get("keyword"),
        symbol_rank=item.channel_ranks.get("symbol"),
        vector_rank=item.channel_ranks.get("vector"),
        keyword_score=item.channel_scores.get("keyword"),
        symbol_score=item.channel_scores.get("symbol"),
        vector_score=item.channel_scores.get("vector"),
        matched_channels=list(item.matched_channels),
    )


def _retrieval_response(
    run: RetrievalRun,
    rows: Sequence[Tuple[RetrievalResult, CodeChunk]],
) -> RetrievalResponse:
    return RetrievalResponse(
        task_id=run.task_id,
        commit_sha=run.commit_sha,
        query=run.query,
        embedding=RetrievalEmbedding(
            provider=run.embedding_provider,
            model=run.embedding_model,
            dimensions=run.embedding_dimensions,
        ),
        versions=RetrievalVersions(
            chunker=run.chunker_version,
            fusion=run.fusion_version,
            reranker=run.reranker_version,
        ),
        created_at=run.created_at,
        counts=RetrievalCounts(
            chunks=run.chunk_count,
            keyword_candidates=run.keyword_candidate_count,
            symbol_candidates=run.symbol_candidate_count,
            vector_candidates=run.vector_candidate_count,
            results=run.result_count,
        ),
        results=[_result_item(result, chunk) for result, chunk in rows],
    )


def _result_item(
    result: RetrievalResult, chunk: CodeChunk
) -> RetrievalResultItem:
    ranks = {
        key: value
        for key, value in (
            ("keyword", result.keyword_rank),
            ("symbol", result.symbol_rank),
            ("vector", result.vector_rank),
        )
        if value is not None
    }
    scores = {
        key: value
        for key, value in (
            ("keyword", result.keyword_score),
            ("symbol", result.symbol_score),
            ("vector", result.vector_score),
        )
        if value is not None
    }
    snippet = chunk.content[:2_000]
    return RetrievalResultItem(
        rank=result.rank,
        path=chunk.path,
        symbol=chunk.symbol_name,
        kind=chunk.kind,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        snippet=snippet,
        matched_channels=result.matched_channels,
        channel_ranks=ranks,
        channel_scores=scores,
        rrf_score=result.rrf_score,
        rerank_score=result.rerank_score,
    )
