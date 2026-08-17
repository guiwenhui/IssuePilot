from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence
from uuid import UUID

from app.embeddings.base import EmbeddingProvider
from app.embeddings.ollama import (
    EmbeddingInvalidResponseError,
    EmbeddingUnavailableError,
)
from app.models.code_index import CodeFile, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.retrieval.chunker import (
    ChunkLimits,
    CodeChunkDraft,
    IndexedFile,
    IndexedSymbol,
    RetrievalChunkLimitError,
    UnsafeChunkSourceError,
    build_python_chunks,
)
from app.schemas.task import TaskStatus
from app.schemas.retrieval import RetrievalResponse
from app.services.git_client import GitClient
from app.services.repository_service import (
    WorkspaceInconsistentError,
    verify_workspace,
)
from app.services.task_service import DatabaseUnavailableError
from app.services.workspace import WorkspaceManager


FAILURE_MESSAGES = {
    "EMBEDDING_UNAVAILABLE": "本地 Embedding 服务暂时不可用",
    "EMBEDDING_INVALID_RESPONSE": "Embedding 服务返回了不合法的数据",
    "RETRIEVAL_LIMIT_EXCEEDED": "代码检索内容超过允许的资源限制",
    "WORKSPACE_INCONSISTENT": "仓库工作区与任务快照不一致",
    "RETRIEVAL_FAILED": "代码检索失败",
}


@dataclass(frozen=True)
class RetrievalContext:
    task: Task
    snapshot: RepositorySnapshot
    index: CodeIndex
    files: Sequence[CodeFile]
    symbols: Sequence[CodeSymbol]


class RetrievalStore(Protocol):
    async def load_context(self, task_id: UUID) -> RetrievalContext:
        ...

    async def set_status(
        self,
        task: Task,
        status: TaskStatus,
        failure_code: Optional[str] = None,
        failure_message: Optional[str] = None,
    ) -> None:
        ...

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
        ...

    async def load_retrieval(
        self, task_id: UUID
    ) -> Optional[RetrievalResponse]:
        ...


class RetrievalNotReadyError(Exception):
    pass


class RetrievalPersistenceError(Exception):
    pass


class RetrievalService:
    def __init__(
        self,
        store: RetrievalStore,
        git_client: GitClient,
        workspace: WorkspaceManager,
        provider: EmbeddingProvider,
        chunk_limits: ChunkLimits,
        candidate_limit: int,
        result_limit: int,
        success_status: TaskStatus = TaskStatus.RETRIEVED,
    ) -> None:
        self._store = store
        self._git = git_client
        self._workspace = workspace
        self._provider = provider
        self._chunk_limits = chunk_limits
        self._candidate_limit = candidate_limit
        self._result_limit = result_limit
        self._success_status = success_status

    async def retrieve_task(self, task_id: UUID) -> None:
        context = await self._store.load_context(task_id)
        if context.task.status not in {
            TaskStatus.INDEXED,
            TaskStatus.RETRIEVING,
        }:
            return
        if context.task.status == TaskStatus.INDEXED:
            await self._store.set_status(context.task, TaskStatus.RETRIEVING)
        try:
            chunks = await self._build_chunks(context)
            embeddings = await self._provider.embed_documents(
                [chunk.searchable_text for chunk in chunks]
            )
            query_embedding = await self._provider.embed_query(
                context.task.issue_text
            )
            await self._store.persist_retrieval(
                context,
                chunks,
                embeddings,
                query_embedding,
                self._provider.name,
                self._provider.model,
                self._provider.dimensions,
                self._candidate_limit,
                self._result_limit,
                self._success_status,
            )
        except DatabaseUnavailableError:
            raise
        except _known_retrieval_errors() as error:
            await self._fail_task(context.task, error)
        except Exception as error:
            await self._fail_task(context.task, error)

    async def get_retrieval(self, task_id: UUID) -> RetrievalResponse:
        response = await self._store.load_retrieval(task_id)
        if response is None:
            raise RetrievalNotReadyError()
        context = await self._store.load_context(task_id)
        if (
            context.snapshot.commit_sha != context.index.commit_sha
            or response.commit_sha != context.snapshot.commit_sha
        ):
            raise WorkspaceInconsistentError()
        repository = self._workspace.repository_path(task_id)
        await verify_workspace(self._git, repository, context.snapshot.commit_sha)
        return response

    async def _build_chunks(
        self, context: RetrievalContext
    ) -> List[CodeChunkDraft]:
        if context.snapshot.commit_sha != context.index.commit_sha:
            raise WorkspaceInconsistentError()
        repository = self._workspace.repository_path(context.task.id)
        await verify_workspace(self._git, repository, context.snapshot.commit_sha)
        entries = await self._git.tracked_entries(repository)
        tracked_paths = {
            entry.path
            for entry in entries
            if entry.kind == "file" and entry.path.endswith(".py")
        }
        chunks = build_python_chunks(
            repository,
            _indexed_files(context.files),
            _indexed_symbols(context.symbols),
            tracked_paths,
            self._chunk_limits,
        )
        if not chunks:
            raise RetrievalChunkLimitError("no retrievable Python chunks")
        return chunks

    async def _fail_task(self, task: Task, error: Exception) -> None:
        code = _failure_code(error)
        await self._store.set_status(
            task,
            TaskStatus.FAILED,
            failure_code=code,
            failure_message=FAILURE_MESSAGES[code],
        )


def _indexed_files(files: Sequence[CodeFile]) -> List[IndexedFile]:
    return [
        IndexedFile(
            id=item.id,
            path=item.path,
            source_sha256=item.source_sha256,
            parse_status=item.parse_status,
        )
        for item in files
    ]


def _indexed_symbols(symbols: Sequence[CodeSymbol]) -> List[IndexedSymbol]:
    return [
        IndexedSymbol(
            id=item.id,
            file_id=item.file_id,
            kind=item.kind,
            qualified_name=item.qualified_name,
            signature=item.signature,
            start_line=item.start_line,
            end_line=item.end_line,
        )
        for item in symbols
    ]


def _known_retrieval_errors() -> tuple:
    return (
        EmbeddingUnavailableError,
        EmbeddingInvalidResponseError,
        RetrievalPersistenceError,
        RetrievalChunkLimitError,
        UnsafeChunkSourceError,
        WorkspaceInconsistentError,
    )


def _failure_code(error: Exception) -> str:
    if isinstance(error, EmbeddingUnavailableError):
        return "EMBEDDING_UNAVAILABLE"
    if isinstance(error, EmbeddingInvalidResponseError):
        return "EMBEDDING_INVALID_RESPONSE"
    if isinstance(error, RetrievalChunkLimitError):
        return "RETRIEVAL_LIMIT_EXCEEDED"
    if isinstance(error, (UnsafeChunkSourceError, WorkspaceInconsistentError)):
        return "WORKSPACE_INCONSISTENT"
    return "RETRIEVAL_FAILED"
