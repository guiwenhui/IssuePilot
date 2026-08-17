import asyncio
from uuid import uuid4

import pytest

from app.workers.planning_queue import PlanningQueue, PlanningQueueFullError


@pytest.mark.asyncio
async def test_planning_queue_processes_decisions_with_one_consumer() -> None:
    processed = []

    async def processor(kind, item_id) -> None:
        processed.append((kind, item_id))

    queue = PlanningQueue(2, processor, enabled=True)
    decision_id = uuid4()
    await queue.start()
    queue.enqueue(decision_id)
    await asyncio.wait_for(queue.join(), timeout=1)
    await queue.stop()

    assert processed == [("decision", decision_id)]


def test_planning_queue_applies_backpressure_and_disabled_mode() -> None:
    async def processor(kind, item_id) -> None:
        return None

    queue = PlanningQueue(1, processor, enabled=True)
    queue.enqueue(uuid4())
    with pytest.raises(PlanningQueueFullError):
        queue.enqueue(uuid4())

    disabled = PlanningQueue(1, processor, enabled=False)
    assert disabled.enqueue(uuid4()) is False
