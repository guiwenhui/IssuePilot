import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.tasks import router as tasks_router
from app.core.config import Settings, get_settings
from app.db.session import session_factory
from app.parsers.python_ast import ParserLimits
from app.services.parser_client import ParserClient
from app.services.git_client import GitClient
from app.services.code_index_service import CodeIndexNotReadyError
from app.services.repository_service import (
    RepositoryNotReadyError,
    RepositoryService,
    WorkspaceInconsistentError,
)
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError
from app.services.workspace import WorkspaceLimits, WorkspaceManager
from app.workers.repository_queue import RepositoryQueue
from app.workers.repository_pipeline import RepositoryPipeline


logger = logging.getLogger(__name__)


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Optional[List[Dict[str, Any]]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
    )


def validation_details(error: RequestValidationError) -> List[Dict[str, Any]]:
    details = []
    for item in error.errors():
        location = [str(part) for part in item["loc"] if part != "body"]
        details.append(
            {"field": ".".join(location) or "request", "message": item["msg"]}
        )
    return details


def create_repository_runtime(
    settings: Settings,
) -> Tuple[
    GitClient,
    WorkspaceManager,
    ParserClient,
    ParserLimits,
    RepositoryQueue,
]:
    workspace = WorkspaceManager(
        Path(settings.repository_workspace_root),
        WorkspaceLimits(
            settings.max_workspace_bytes,
            settings.max_tracked_files,
            settings.max_tree_entries,
            settings.max_tree_depth,
        ),
    )
    git_client = GitClient(settings.clone_timeout_seconds)
    parser_client = ParserClient(settings.parser_timeout_seconds)
    parser_limits = ParserLimits(
        settings.max_python_files,
        settings.max_python_file_bytes,
        settings.max_python_total_bytes,
        settings.max_code_entities,
    )
    pipeline = RepositoryPipeline(
        git_client,
        workspace,
        parser_client,
        parser_limits,
        settings.max_code_preview_entries,
    )

    async def process_repository(task_id: UUID) -> None:
        async with session_factory() as session:
            await pipeline.process(session, task_id)

    queue = RepositoryQueue(
        settings.clone_queue_capacity,
        process_repository,
        settings.repository_clone_enabled,
    )
    return git_client, workspace, parser_client, parser_limits, queue


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    await application.state.repository_queue.start()
    yield
    await application.state.repository_queue.stop()


async def handle_validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    del request
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "请求参数不合法",
        validation_details(error),
    )


async def handle_task_not_found(
    request: Request, error: TaskNotFoundError
) -> JSONResponse:
    del request, error
    return error_response(status.HTTP_404_NOT_FOUND, "TASK_NOT_FOUND", "任务不存在")


async def handle_database_unavailable(
    request: Request, error: DatabaseUnavailableError
) -> JSONResponse:
    del request, error
    return error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "DATABASE_UNAVAILABLE",
        "任务存储暂时不可用",
    )


async def handle_repository_not_ready(
    request: Request, error: RepositoryNotReadyError
) -> JSONResponse:
    del request, error
    return error_response(
        status.HTTP_409_CONFLICT,
        "REPOSITORY_NOT_READY",
        "仓库尚未克隆完成",
    )


async def handle_workspace_inconsistent(
    request: Request, error: WorkspaceInconsistentError
) -> JSONResponse:
    del request, error
    return error_response(
        status.HTTP_409_CONFLICT,
        "WORKSPACE_INCONSISTENT",
        "仓库工作区与任务快照不一致",
    )


async def handle_code_index_not_ready(
    request: Request, error: CodeIndexNotReadyError
) -> JSONResponse:
    del request, error
    return error_response(
        status.HTTP_409_CONFLICT,
        "CODE_INDEX_NOT_READY",
        "Python 代码结构索引尚未完成",
    )


async def handle_internal_error(request: Request, error: Exception) -> JSONResponse:
    logger.error(
        "Unhandled API error for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(error), error, error.__traceback__),
    )
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "服务发生未预期错误",
    )


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(TaskNotFoundError, handle_task_not_found)
    application.add_exception_handler(
        DatabaseUnavailableError, handle_database_unavailable
    )
    application.add_exception_handler(
        RepositoryNotReadyError, handle_repository_not_ready
    )
    application.add_exception_handler(
        WorkspaceInconsistentError, handle_workspace_inconsistent
    )
    application.add_exception_handler(
        CodeIndexNotReadyError, handle_code_index_not_ready
    )
    application.add_exception_handler(Exception, handle_internal_error)


def create_app() -> FastAPI:
    settings = get_settings()
    git_client, workspace, parser_client, parser_limits, queue = (
        create_repository_runtime(settings)
    )
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.state.git_client = git_client
    application.state.workspace = workspace
    application.state.parser_client = parser_client
    application.state.parser_limits = parser_limits
    application.state.max_code_preview_entries = settings.max_code_preview_entries
    application.state.repository_queue = queue
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(tasks_router)
    register_exception_handlers(application)
    return application


app = create_app()
