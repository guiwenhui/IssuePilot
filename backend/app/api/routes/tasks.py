from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import (
    CodeIndexServiceDependency,
    PlanningServiceDependency,
    RetrievalServiceDependency,
    RepositoryQueueDependency,
    RepositoryServiceDependency,
    TaskServiceDependency,
)
from app.schemas.code_index import CodeStructureResponse
from app.schemas.planning import PlanningResponse
from app.schemas.repository import RepositoryTreeResponse
from app.schemas.retrieval import RetrievalResponse
from app.schemas.task import ErrorResponse, TaskCreate, TaskResponse, TaskStatus
from app.workers.repository_queue import CloneQueueFullError


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
    repository_queue: RepositoryQueueDependency,
    response: Response,
) -> TaskResponse:
    task = await service.create_task(payload)
    if repository_queue.enabled:
        task = await service.set_status(task.id, TaskStatus.QUEUED)
        try:
            repository_queue.enqueue(task.id)
        except CloneQueueFullError:
            task = await service.set_status(
                task.id,
                TaskStatus.FAILED,
                failure_code="CLONE_QUEUE_FULL",
                failure_message="仓库克隆队列已满",
            )
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


@router.get(
    "/{task_id}/repository/tree",
    response_model=RepositoryTreeResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_repository_tree(
    task_id: UUID,
    service: RepositoryServiceDependency,
    response: Response,
) -> RepositoryTreeResponse:
    tree = await service.get_tree(task_id)
    response.headers["Cache-Control"] = "no-store"
    return tree


@router.get(
    "/{task_id}/code/structure",
    response_model=CodeStructureResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_code_structure(
    task_id: UUID,
    service: CodeIndexServiceDependency,
    response: Response,
) -> CodeStructureResponse:
    structure = await service.get_structure(task_id)
    response.headers["Cache-Control"] = "no-store"
    return structure


@router.get(
    "/{task_id}/retrieval",
    response_model=RetrievalResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_retrieval(
    task_id: UUID,
    service: RetrievalServiceDependency,
    response: Response,
) -> RetrievalResponse:
    retrieval = await service.get_retrieval(task_id)
    response.headers["Cache-Control"] = "no-store"
    return retrieval


@router.get(
    "/{task_id}/planning",
    response_model=PlanningResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_planning(
    task_id: UUID,
    service: PlanningServiceDependency,
    response: Response,
) -> PlanningResponse:
    planning = await service.get_planning(task_id)
    response.headers["Cache-Control"] = "no-store"
    return planning
