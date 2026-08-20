from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.dependencies import (
    CodeIndexServiceDependency,
    ImplementationQueueDependency,
    ImplementationServiceDependency,
    PlanningServiceDependency,
    PlanningQueueDependency,
    RetrievalServiceDependency,
    RepositoryQueueDependency,
    RepositoryServiceDependency,
    TaskServiceDependency,
)
from app.schemas.code_index import CodeStructureResponse
from app.schemas.implementation import (
    ImplementationCreate,
    ImplementationResponse,
    TestRunCreate,
)
from app.schemas.planning import (
    PlanningDecisionCreate,
    PlanningDecisionResponse,
    PlanningResponse,
)
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


@router.post(
    "/{task_id}/planning/decisions",
    response_model=PlanningDecisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_planning_decision(
    task_id: UUID,
    payload: PlanningDecisionCreate,
    service: PlanningServiceDependency,
    planning_queue: PlanningQueueDependency,
    response: Response,
) -> PlanningDecisionResponse:
    decision = await service.submit_decision(task_id, payload)
    if decision.status == "pending":
        planning_queue.enqueue(decision.decision_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = (
        f"/api/v1/tasks/{task_id}/planning"
    )
    return decision


@router.post(
    "/{task_id}/implementation",
    response_model=ImplementationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_implementation(
    task_id: UUID,
    payload: ImplementationCreate,
    service: ImplementationServiceDependency,
    queue: ImplementationQueueDependency,
    response: Response,
) -> ImplementationResponse:
    implementation = await service.submit_implementation(task_id, payload)
    if implementation.run.status in {"pending", "generating_patch"}:
        queue.enqueue_implementation(implementation.run.implementation_run_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/tasks/{task_id}/implementation"
    return implementation


@router.get(
    "/{task_id}/implementation",
    response_model=ImplementationResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_implementation(
    task_id: UUID,
    service: ImplementationServiceDependency,
    response: Response,
) -> ImplementationResponse:
    implementation = await service.get_implementation(task_id)
    response.headers["Cache-Control"] = "no-store"
    return implementation


@router.post(
    "/{task_id}/implementation/tests",
    response_model=ImplementationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_implementation_test(
    task_id: UUID,
    payload: TestRunCreate,
    service: ImplementationServiceDependency,
    queue: ImplementationQueueDependency,
    response: Response,
) -> ImplementationResponse:
    implementation = await service.submit_test(task_id, payload)
    if implementation.test and implementation.test.status == "pending":
        queue.enqueue_test(implementation.test.test_run_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/tasks/{task_id}/implementation"
    return implementation
