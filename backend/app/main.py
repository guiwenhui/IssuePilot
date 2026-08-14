import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.tasks import router as tasks_router
from app.core.config import get_settings
from app.services.task_service import DatabaseUnavailableError, TaskNotFoundError


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
            {
                "field": ".".join(location) or "request",
                "message": item["msg"],
            }
        )
    return details


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title=settings.app_name)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(tasks_router)

    @application.exception_handler(RequestValidationError)
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

    @application.exception_handler(TaskNotFoundError)
    async def handle_task_not_found(
        request: Request, error: TaskNotFoundError
    ) -> JSONResponse:
        del request, error
        return error_response(
            status.HTTP_404_NOT_FOUND,
            "TASK_NOT_FOUND",
            "任务不存在",
        )

    @application.exception_handler(DatabaseUnavailableError)
    async def handle_database_unavailable(
        request: Request, error: DatabaseUnavailableError
    ) -> JSONResponse:
        del request, error
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DATABASE_UNAVAILABLE",
            "任务存储暂时不可用",
        )

    @application.exception_handler(Exception)
    async def handle_internal_error(
        request: Request, error: Exception
    ) -> JSONResponse:
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

    return application


app = create_app()
