import asyncio
from uuid import uuid4

import pytest

from app.workers.repository_queue import CloneQueueFullError, RepositoryQueue


@pytest.mark.asyncio
async def test_repository_queue_processes_tasks_with_one_consumer() -> None:
    processed = []

    async def processor(task_id: object) -> None:
        processed.append(task_id)

    queue = RepositoryQueue(capacity=2, processor=processor, enabled=True)
    task_id = uuid4()

    await queue.start()
    queue.enqueue(task_id)
    await asyncio.wait_for(queue.join(), timeout=1)
    await queue.stop()

    assert processed == [task_id]


def test_repository_queue_applies_backpressure() -> None:
    async def processor(task_id: object) -> None:
        return None

    queue = RepositoryQueue(capacity=1, processor=processor, enabled=True)
    queue.enqueue(uuid4())

    with pytest.raises(CloneQueueFullError):
        queue.enqueue(uuid4())


def test_disabled_repository_queue_preserves_m1_behavior() -> None:
    async def processor(task_id: object) -> None:
        return None

    queue = RepositoryQueue(capacity=1, processor=processor, enabled=False)

    assert queue.enqueue(uuid4()) is False


@pytest.mark.asyncio
async def test_repository_queue_reports_unhandled_worker_failure() -> None:
    task_id = uuid4()
    failure = RuntimeError("unexpected")
    handled = []

    async def processor(current_task_id: object) -> None:
        assert current_task_id == task_id
        raise failure

    async def failure_handler(
        current_task_id: object, error: Exception
    ) -> None:
        handled.append((current_task_id, error))

    queue = RepositoryQueue(
        capacity=1,
        processor=processor,
        enabled=True,
        failure_handler=failure_handler,
    )

    await queue.start()
    queue.enqueue(task_id)
    await asyncio.wait_for(queue.join(), timeout=1)
    await queue.stop()

    assert handled == [(task_id, failure)]
