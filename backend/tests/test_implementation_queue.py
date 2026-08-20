import asyncio
from uuid import uuid4

import pytest

from app.workers.implementation_queue import (
    ImplementationQueue,
    ImplementationQueueFullError,
)


@pytest.mark.asyncio
async def test_implementation_queue_processes_patch_and_test_serially() -> None:
    processed = []

    async def processor(kind, item_id) -> None:
        processed.append((kind, item_id))

    first, second = uuid4(), uuid4()
    queue = ImplementationQueue(2, processor, True)
    await queue.start()
    queue.enqueue_implementation(first)
    queue.enqueue_test(second)
    await asyncio.wait_for(queue.join(), timeout=1)
    await queue.stop()

    assert processed == [("implementation", first), ("test", second)]


def test_implementation_queue_backpressure_and_disabled_mode() -> None:
    async def processor(kind, item_id) -> None:
        return None

    queue = ImplementationQueue(1, processor, True)
    queue.enqueue_implementation(uuid4())
    with pytest.raises(ImplementationQueueFullError):
        queue.enqueue_test(uuid4())
    assert ImplementationQueue(1, processor, False).enqueue_implementation(
        uuid4()
    ) is False
