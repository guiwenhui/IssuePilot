from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import TaskServiceDependency
from app.schemas.task import ErrorResponse, TaskCreate, TaskResponse


router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post(
    "",
    response_model=TaskResponse,
    response_model_by_alias=False,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def create_task(
    payload: TaskCreate,
    service: TaskServiceDependency,
    response: Response,
) -> TaskResponse:
    task = await service.create_task(payload)
    response.headers["Location"] = f"/api/v1/tasks/{task.id}"
    return TaskResponse.model_validate(task)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    response_model_by_alias=False,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_task(
    task_id: UUID,
    service: TaskServiceDependency,
    response: Response,
) -> TaskResponse:
    task = await service.get_task(task_id)
    response.headers["Cache-Control"] = "no-store"
    return TaskResponse.model_validate(task)
