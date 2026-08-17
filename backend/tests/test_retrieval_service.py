import hashlib
from pathlib import Path
from typing import List, Optional, Sequence
from uuid import uuid4

import pytest

from app.embeddings.ollama import EmbeddingUnavailableError
from app.models.code_index import CodeFile, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.retrieval.chunker import ChunkLimits, CodeChunkDraft
from app.schemas.task import TaskStatus
from app.services.git_client import TrackedEntry
from app.services.retrieval_service import (
    RetrievalContext,
    RetrievalPersistenceError,
    RetrievalService,
)
from app.services.workspace import WorkspaceLimits, WorkspaceManager


class FakeGit:
    sha = "a" * 40
    clean = True

    async def head_sha(self, repository: Path) -> str:
        return self.sha

    async def is_clean(self, repository: Path) -> bool:
        return self.clean

    async def tracked_entries(self, repository: Path) -> List[TrackedEntry]:
        return [TrackedEntry("service.py", "file", 40)]


class FakeProvider:
    name = "fake"
    model = "fake-embedding-v1"
    dimensions = 1024

    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.documents: List[str] = []
        self.query = ""

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> List[List[float]]:
        if self.error:
            raise self.error
        self.documents = list(texts)
        return [[0.1] * self.dimensions for _ in texts]

    async def embed_query(self, text: str) -> List[float]:
        if self.error:
            raise self.error
        self.query = text
        return [0.2] * self.dimensions


class FakeStore:
    def __init__(
        self,
        context: RetrievalContext,
        persist_error: Optional[Exception] = None,
    ) -> None:
        self.context = context
        self.persist_error = persist_error
        self.persisted: List[CodeChunkDraft] = []

    async def load_context(self, task_id: object) -> RetrievalContext:
        return self.context

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
        success_status: TaskStatus,
    ) -> None:
        if self.persist_error is not None:
            raise self.persist_error
        assert len(chunks) == len(embeddings)
        assert len(query_embedding) == provider_dimensions
        assert candidate_limit == 50
        assert result_limit == 10
        self.persisted = list(chunks)
        context.task.status = success_status


def make_context(tmp_path: Path) -> tuple[RetrievalContext, WorkspaceManager]:
    task_id = uuid4()
    workspace = WorkspaceManager(
        tmp_path / "workspaces", WorkspaceLimits(10_000, 100, 100, 10)
    )
    repository = workspace.repository_path(task_id)
    repository.mkdir(parents=True)
    source = repository / "service.py"
    source.write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    file_id = uuid4()
    task = Task(
        id=task_id,
        repository_url="https://github.com/example/project.git",
        issue_text="Fix run behavior",
        status=TaskStatus.INDEXED,
    )
    snapshot = RepositorySnapshot(
        task_id=task_id,
        canonical_url=task.repository_url,
        commit_sha="a" * 40,
        file_count=1,
        total_bytes=source.stat().st_size,
        tree_manifest=[],
    )
    index = CodeIndex(
        task_id=task_id,
        commit_sha="a" * 40,
        parser_version="py-ast-v1",
        python_version="3.9.6",
        file_count=1,
        parsed_file_count=1,
        symbol_count=1,
        import_count=0,
        test_count=0,
        parse_error_count=0,
    )
    code_file = CodeFile(
        id=file_id,
        task_id=task_id,
        path="service.py",
        module_name="service",
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        line_count=2,
        size_bytes=source.stat().st_size,
        is_test_file=False,
        parse_status="parsed",
    )
    symbol = CodeSymbol(
        id=uuid4(),
        file_id=file_id,
        kind="function",
        name="run",
        qualified_name="run",
        start_line=1,
        end_line=2,
        signature="run()",
        decorators=[],
        is_async=False,
        is_test=False,
        is_fixture=False,
    )
    return RetrievalContext(task, snapshot, index, [code_file], [symbol]), workspace


def make_service(
    context: RetrievalContext,
    workspace: WorkspaceManager,
    provider: FakeProvider,
) -> tuple[RetrievalService, FakeStore]:
    store = FakeStore(context)
    service = RetrievalService(
        store,
        FakeGit(),
        workspace,
        provider,
        ChunkLimits(100, 120, 160, 20, 16_384),
        50,
        10,
    )
    return service, store


@pytest.mark.asyncio
async def test_retrieve_task_builds_embeddings_and_retrieved_artifact(
    tmp_path: Path,
) -> None:
    context, workspace = make_context(tmp_path)
    provider = FakeProvider()
    service, store = make_service(context, workspace, provider)

    await service.retrieve_task(context.task.id)

    assert context.task.status == TaskStatus.RETRIEVED
    assert provider.query == context.task.issue_text
    assert len(provider.documents) == len(store.persisted) == 1
    assert store.persisted[0].symbol_name == "run"


@pytest.mark.asyncio
async def test_retrieve_task_can_transition_directly_to_analyzing(
    tmp_path: Path,
) -> None:
    context, workspace = make_context(tmp_path)
    service = RetrievalService(
        FakeStore(context),
        FakeGit(),
        workspace,
        FakeProvider(),
        ChunkLimits(100, 120, 160, 20, 16_384),
        50,
        10,
        TaskStatus.ANALYZING,
    )

    await service.retrieve_task(context.task.id)

    assert context.task.status == TaskStatus.ANALYZING


@pytest.mark.asyncio
async def test_retrieve_task_rejects_index_snapshot_mismatch(tmp_path: Path) -> None:
    context, workspace = make_context(tmp_path)
    context.index.commit_sha = "b" * 40
    service, store = make_service(context, workspace, FakeProvider())

    await service.retrieve_task(context.task.id)

    assert context.task.status == TaskStatus.FAILED
    assert context.task.failure_code == "WORKSPACE_INCONSISTENT"
    assert store.persisted == []


@pytest.mark.asyncio
async def test_retrieve_task_maps_embedding_outage_to_failure(tmp_path: Path) -> None:
    context, workspace = make_context(tmp_path)
    provider = FakeProvider(EmbeddingUnavailableError("offline"))
    service, _ = make_service(context, workspace, provider)

    await service.retrieve_task(context.task.id)

    assert context.task.status == TaskStatus.FAILED
    assert context.task.failure_code == "EMBEDDING_UNAVAILABLE"
    assert context.task.failure_message == "本地 Embedding 服务暂时不可用"


@pytest.mark.asyncio
async def test_retrieve_task_maps_persistence_error_to_stable_failure(
    tmp_path: Path,
) -> None:
    context, workspace = make_context(tmp_path)
    store = FakeStore(context, RetrievalPersistenceError("duplicate chunk"))
    service = RetrievalService(
        store,
        FakeGit(),
        workspace,
        FakeProvider(),
        ChunkLimits(100, 120, 160, 20, 16_384),
        50,
        10,
    )

    await service.retrieve_task(context.task.id)

    assert context.task.status == TaskStatus.FAILED
    assert context.task.failure_code == "RETRIEVAL_FAILED"
    assert context.task.failure_message == "代码检索失败"


@pytest.mark.asyncio
async def test_retrieve_task_ignores_unrelated_terminal_state(tmp_path: Path) -> None:
    context, workspace = make_context(tmp_path)
    context.task.status = TaskStatus.FAILED
    provider = FakeProvider()
    service, store = make_service(context, workspace, provider)

    await service.retrieve_task(context.task.id)

    assert provider.documents == []
    assert store.persisted == []
