import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional
from uuid import UUID


logger = logging.getLogger(__name__)
WorkProcessor = Callable[[str, UUID], Awaitable[None]]


@dataclass(frozen=True)
class PlanningWorkItem:
    kind: str
    item_id: UUID


class PlanningQueueFullError(Exception):
    pass


class PlanningQueue:
    def __init__(
        self,
        capacity: int,
        processor: WorkProcessor,
        enabled: bool,
    ) -> None:
        self.enabled = enabled
        self._queue: asyncio.Queue[Optional[PlanningWorkItem]] = asyncio.Queue(
            capacity
        )
        self._processor = processor
        self._worker: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self.enabled and self._worker is None:
            self._worker = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._worker is None:
            return
        await self._queue.join()
        await self._queue.put(None)
        await self._worker
        self._worker = None

    def enqueue(self, decision_id: UUID) -> bool:
        return self._enqueue(PlanningWorkItem("decision", decision_id))

    def enqueue_task(self, task_id: UUID) -> bool:
        return self._enqueue(PlanningWorkItem("task", task_id))

    def _enqueue(self, item: PlanningWorkItem) -> bool:
        if not self.enabled:
            return False
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull as error:
            raise PlanningQueueFullError() from error
        return True

    async def join(self) -> None:
        await self._queue.join()

    async def _consume(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                await self._processor(item.kind, item.item_id)
            except Exception:
                logger.exception(
                    "Planning worker failed for %s %s", item.kind, item.item_id
                )
            finally:
                self._queue.task_done()
