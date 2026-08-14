import uuid
from collections import defaultdict
from typing import DefaultDict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_index import CodeFile, CodeImport, CodeIndex, CodeSymbol
from app.models.repository_snapshot import RepositorySnapshot
from app.models.task import Task
from app.parsers.python_ast import (
    NoPythonFilesError,
    ParserLimits,
    PythonSourceLimitError,
    UnsafePythonPathError,
)
from app.schemas.code_index import (
    CodeStructureCounts,
    CodeStructureFile,
    CodeStructureResponse,
    ParsedFile,
    ParsedImport,
    ParsedSymbol,
    ParserResult,
)
from app.schemas.task import TaskStatus
from app.services.git_client import GitClient
from app.services.parser_client import (
    ParserClient,
    ParserClientError,
    ParserProtocolError,
    ParserTimeoutError,
)
from app.services.repository_service import (
    WorkspaceInconsistentError,
    verify_workspace,
)
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError
from app.services.workspace import WorkspaceManager


FAILURE_MESSAGES = {
    "NO_PYTHON_FILES": "仓库中没有可解析的 Python 文件",
    "PYTHON_SOURCE_LIMIT_EXCEEDED": "Python 源码超过允许的解析限制",
    "CODE_INDEX_TIMEOUT": "Python 代码结构解析超时",
    "CODE_INDEX_FAILED": "Python 代码结构解析失败",
    "WORKSPACE_INCONSISTENT": "仓库工作区与任务快照不一致",
}


class CodeIndexNotReadyError(Exception):
    pass


class CodeIndexService:
    def __init__(
        self,
        session: AsyncSession,
        git_client: GitClient,
        workspace: WorkspaceManager,
        parser_client: ParserClient,
        parser_limits: ParserLimits,
        max_preview_entries: int,
    ) -> None:
        self._session = session
        self._git = git_client
        self._workspace = workspace
        self._parser = parser_client
        self._limits = parser_limits
        self._max_preview_entries = max_preview_entries

    async def index_task(self, task_id: UUID) -> None:
        task = await self._get_task(task_id)
        if task.status not in {TaskStatus.CLONED, TaskStatus.INDEXING}:
            return
        if task.status == TaskStatus.CLONED:
            await self._set_task_status(task, TaskStatus.INDEXING)
        try:
            snapshot = await self._get_snapshot(task_id)
            repository = self._workspace.repository_path(task_id)
            await verify_workspace(self._git, repository, snapshot.commit_sha)
            entries = await self._git.tracked_entries(repository)
            paths = [
                entry.path
                for entry in entries
                if entry.kind == "file" and entry.path.endswith(".py")
            ]
            result = await self._parser.parse(repository, paths, self._limits)
            await self._persist_result(task, snapshot, result)
        except _known_index_errors() as error:
            code = _failure_code(error)
            await self._set_task_status(
                task,
                TaskStatus.FAILED,
                failure_code=code,
                failure_message=FAILURE_MESSAGES[code],
            )

    async def get_structure(self, task_id: UUID) -> CodeStructureResponse:
        await self._get_task(task_id)
        snapshot = await self._get_snapshot(task_id)
        index = await self._get_index(task_id)
        if index is None:
            raise CodeIndexNotReadyError()
        if index.commit_sha != snapshot.commit_sha:
            raise WorkspaceInconsistentError()
        repository = self._workspace.repository_path(task_id)
        await verify_workspace(self._git, repository, snapshot.commit_sha)
        files, symbols, imports = await self._load_records(task_id)
        return self._structure_response(index, files, symbols, imports)

    async def _get_task(self, task_id: UUID) -> Task:
        try:
            task = await self._session.get(Task, task_id)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error
        if task is None:
            raise TaskNotFoundError()
        return task

    async def _get_snapshot(self, task_id: UUID) -> RepositorySnapshot:
        try:
            snapshot = await self._session.get(RepositorySnapshot, task_id)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error
        if snapshot is None:
            raise WorkspaceInconsistentError()
        return snapshot

    async def _get_index(self, task_id: UUID) -> Optional[CodeIndex]:
        try:
            return await self._session.get(CodeIndex, task_id)
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error

    async def _load_records(
        self, task_id: UUID
    ) -> Tuple[List[CodeFile], List[CodeSymbol], List[CodeImport]]:
        try:
            file_result = await self._session.execute(
                select(CodeFile)
                .where(CodeFile.task_id == task_id)
                .order_by(CodeFile.path)
            )
            files = list(file_result.scalars().all())
            file_ids = [item.id for item in files]
            if not file_ids:
                return files, [], []
            symbol_result = await self._session.execute(
                select(CodeSymbol)
                .where(CodeSymbol.file_id.in_(file_ids))
                .order_by(CodeSymbol.start_line, CodeSymbol.qualified_name)
            )
            import_result = await self._session.execute(
                select(CodeImport)
                .where(CodeImport.file_id.in_(file_ids))
                .order_by(CodeImport.line, CodeImport.module)
            )
            return (
                files,
                list(symbol_result.scalars().all()),
                list(import_result.scalars().all()),
            )
        except (SQLAlchemyError, OSError) as error:
            raise DatabaseUnavailableError() from error

    def _structure_response(
        self,
        index: CodeIndex,
        files: Sequence[CodeFile],
        symbols: Sequence[CodeSymbol],
        imports: Sequence[CodeImport],
    ) -> CodeStructureResponse:
        symbols_by_file: DefaultDict[UUID, List[CodeSymbol]] = defaultdict(list)
        imports_by_file: DefaultDict[UUID, List[CodeImport]] = defaultdict(list)
        for symbol in symbols:
            symbols_by_file[symbol.file_id].append(symbol)
        for item in imports:
            imports_by_file[item.file_id].append(item)
        preview, used = self._preview_files(
            files, symbols_by_file, imports_by_file
        )
        total_entries = len(files) + len(symbols) + len(imports)
        return CodeStructureResponse(
            task_id=index.task_id,
            commit_sha=index.commit_sha,
            parser_version=index.parser_version,
            python_version=index.python_version,
            indexed_at=index.indexed_at,
            counts=CodeStructureCounts(
                files=index.file_count,
                parsed_files=index.parsed_file_count,
                symbols=index.symbol_count,
                imports=index.import_count,
                tests=index.test_count,
                parse_errors=index.parse_error_count,
            ),
            truncated=used < total_entries,
            files=preview,
        )

    def _preview_files(
        self,
        files: Sequence[CodeFile],
        symbols_by_file: DefaultDict[UUID, List[CodeSymbol]],
        imports_by_file: DefaultDict[UUID, List[CodeImport]],
    ) -> Tuple[List[CodeStructureFile], int]:
        preview: List[CodeStructureFile] = []
        used = 0
        for code_file in files:
            if used >= self._max_preview_entries:
                break
            used += 1
            symbol_models = _preview_symbols(
                symbols_by_file[code_file.id],
                self._max_preview_entries - used,
            )
            used += len(symbol_models)
            import_models = [
                _parsed_import(item)
                for item in imports_by_file[code_file.id][
                    : self._max_preview_entries - used
                ]
            ]
            used += len(import_models)
            preview.append(
                CodeStructureFile(
                    path=code_file.path,
                    module_name=code_file.module_name,
                    is_test_file=code_file.is_test_file,
                    parse_status=code_file.parse_status,
                    parse_error=code_file.parse_error,
                    symbols=symbol_models,
                    imports=import_models,
                )
            )
        return preview, used

    async def _persist_result(
        self,
        task: Task,
        snapshot: RepositorySnapshot,
        result: ParserResult,
    ) -> None:
        try:
            await self._session.execute(
                delete(CodeIndex).where(CodeIndex.task_id == task.id)
            )
            self._session.add(_index_record(task.id, snapshot.commit_sha, result))
            await self._session.flush()
            for parsed_file in result.files:
                await self._add_file(task.id, parsed_file)
            task.status = TaskStatus.INDEXED
            task.failure_code = None
            task.failure_message = None
            await self._session.commit()
        except ParserProtocolError:
            await self._session.rollback()
            raise
        except (SQLAlchemyError, OSError) as error:
            await self._session.rollback()
            raise DatabaseUnavailableError() from error

    async def _add_file(self, task_id: UUID, parsed: ParsedFile) -> None:
        file_id = uuid.uuid4()
        self._session.add(
            CodeFile(
                id=file_id,
                task_id=task_id,
                path=parsed.path,
                module_name=parsed.module_name,
                source_sha256=parsed.source_sha256,
                line_count=parsed.line_count,
                size_bytes=parsed.size_bytes,
                is_test_file=parsed.is_test_file,
                parse_status=parsed.parse_status,
                parse_error=parsed.parse_error,
            )
        )
        await self._session.flush()
        symbol_ids = {
            symbol.local_id: uuid.uuid4() for symbol in parsed.symbols
        }
        persisted_local_ids = set()
        remaining = list(parsed.symbols)
        while remaining:
            ready = [
                symbol
                for symbol in remaining
                if symbol.parent_local_id is None
                or symbol.parent_local_id in persisted_local_ids
            ]
            if not ready:
                raise ParserProtocolError("invalid symbol hierarchy")
            for symbol in ready:
                self._session.add(
                    CodeSymbol(
                        id=symbol_ids[symbol.local_id],
                        file_id=file_id,
                        parent_id=symbol_ids.get(symbol.parent_local_id),
                        kind=symbol.kind,
                        name=symbol.name,
                        qualified_name=symbol.qualified_name,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        signature=symbol.signature,
                        decorators=symbol.decorators,
                        is_async=symbol.is_async,
                        is_test=symbol.is_test,
                        is_fixture=symbol.is_fixture,
                    )
                )
            await self._session.flush()
            persisted_local_ids.update(symbol.local_id for symbol in ready)
            ready_ids = {symbol.local_id for symbol in ready}
            remaining = [
                symbol
                for symbol in remaining
                if symbol.local_id not in ready_ids
            ]
        for item in parsed.imports:
            self._session.add(
                CodeImport(
                    file_id=file_id,
                    kind=item.kind,
                    module=item.module,
                    imported_name=item.imported_name,
                    alias=item.alias,
                    relative_level=item.relative_level,
                    scope=item.scope,
                    line=item.line,
                )
            )

    async def _set_task_status(
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


def _index_record(
    task_id: UUID, commit_sha: str, result: ParserResult
) -> CodeIndex:
    return CodeIndex(
        task_id=task_id,
        commit_sha=commit_sha,
        parser_version=result.parser_version,
        python_version=result.python_version,
        file_count=len(result.files),
        parsed_file_count=result.parsed_file_count,
        symbol_count=result.symbol_count,
        import_count=result.import_count,
        test_count=result.test_count,
        parse_error_count=result.parse_error_count,
    )


def _known_index_errors() -> tuple:
    return (
        NoPythonFilesError,
        PythonSourceLimitError,
        UnsafePythonPathError,
        ParserTimeoutError,
        ParserProtocolError,
        ParserClientError,
        WorkspaceInconsistentError,
    )


def _failure_code(error: Exception) -> str:
    if isinstance(error, NoPythonFilesError):
        return "NO_PYTHON_FILES"
    if isinstance(error, PythonSourceLimitError):
        return "PYTHON_SOURCE_LIMIT_EXCEEDED"
    if isinstance(error, ParserTimeoutError):
        return "CODE_INDEX_TIMEOUT"
    if isinstance(error, WorkspaceInconsistentError):
        return "WORKSPACE_INCONSISTENT"
    return "CODE_INDEX_FAILED"


def _preview_symbols(
    symbols: Sequence[CodeSymbol], limit: int
) -> List[ParsedSymbol]:
    selected = list(symbols[:limit])
    local_ids = {symbol.id: index + 1 for index, symbol in enumerate(selected)}
    return [
        ParsedSymbol(
            local_id=local_ids[symbol.id],
            parent_local_id=local_ids.get(symbol.parent_id),
            kind=symbol.kind,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            signature=symbol.signature,
            decorators=symbol.decorators,
            is_async=symbol.is_async,
            is_test=symbol.is_test,
            is_fixture=symbol.is_fixture,
        )
        for symbol in selected
    ]


def _parsed_import(item: CodeImport) -> ParsedImport:
    return ParsedImport(
        kind=item.kind,
        module=item.module,
        imported_name=item.imported_name,
        alias=item.alias,
        relative_level=item.relative_level,
        scope=item.scope,
        line=item.line,
    )
