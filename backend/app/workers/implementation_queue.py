import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional
from uuid import UUID


logger = logging.getLogger(__name__)
WorkProcessor = Callable[[str, UUID], Awaitable[None]]


@dataclass(frozen=True)
class ImplementationWorkItem:
    kind: str
    item_id: UUID


class ImplementationQueueFullError(Exception):
    pass


class ImplementationQueue:
    def __init__(
        self, capacity: int, processor: WorkProcessor, enabled: bool
    ) -> None:
        self.enabled = enabled
        self._queue: asyncio.Queue[Optional[ImplementationWorkItem]] = (
            asyncio.Queue(capacity)
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

    def enqueue_implementation(self, run_id: UUID) -> bool:
        return self._enqueue(ImplementationWorkItem("implementation", run_id))

    def enqueue_test(self, test_id: UUID) -> bool:
        return self._enqueue(ImplementationWorkItem("test", test_id))

    def enqueue_work(self, kind: str, item_id: UUID) -> bool:
        if kind not in {"implementation", "test"}:
            raise ValueError("unsupported implementation work kind")
        return self._enqueue(ImplementationWorkItem(kind, item_id))

    def _enqueue(self, item: ImplementationWorkItem) -> bool:
        if not self.enabled:
            return False
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull as error:
            raise ImplementationQueueFullError() from error
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
                    "Implementation worker failed for %s %s",
                    item.kind,
                    item.item_id,
                )
            finally:
                self._queue.task_done()
