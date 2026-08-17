import asyncio
import logging
from typing import Awaitable, Callable, Optional
from uuid import UUID


logger = logging.getLogger(__name__)
TaskProcessor = Callable[[UUID], Awaitable[None]]
FailureHandler = Callable[[UUID, Exception], Awaitable[None]]


class CloneQueueFullError(Exception):
    pass


class RepositoryQueue:
    def __init__(
        self,
        capacity: int,
        processor: TaskProcessor,
        enabled: bool,
        failure_handler: Optional[FailureHandler] = None,
    ) -> None:
        self.enabled = enabled
        self._queue: asyncio.Queue[Optional[UUID]] = asyncio.Queue(capacity)
        self._processor = processor
        self._failure_handler = failure_handler
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

    def enqueue(self, task_id: UUID) -> bool:
        if not self.enabled:
            return False
        try:
            self._queue.put_nowait(task_id)
        except asyncio.QueueFull as error:
            raise CloneQueueFullError() from error
        return True

    async def join(self) -> None:
        await self._queue.join()

    async def _consume(self) -> None:
        while True:
            task_id = await self._queue.get()
            try:
                if task_id is None:
                    return
                await self._processor(task_id)
            except Exception as error:
                logger.exception("Repository worker failed for task %s", task_id)
                await self._handle_failure(task_id, error)
            finally:
                self._queue.task_done()

    async def _handle_failure(self, task_id: UUID, error: Exception) -> None:
        if self._failure_handler is None:
            return
        try:
            await self._failure_handler(task_id, error)
        except Exception:
            logger.exception(
                "Repository failure handler failed for task %s", task_id
            )
