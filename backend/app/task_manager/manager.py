"""Semaphore 동시 실행 제한과 취소를 지원하는 프로세스 내부 작업 Registry."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID


class TaskManager:
    def __init__(self, max_concurrency: int = 2) -> None:
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def submit(self, run_id: UUID, job: Callable[[], Awaitable[None]]) -> bool:
        if run_id in self._tasks:
            return False
        task = asyncio.create_task(self._execute(run_id, job))
        self._tasks[run_id] = task
        return True

    async def _execute(
        self,
        run_id: UUID,
        job: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            async with self._semaphore:
                await job()
        finally:
            self._tasks.pop(run_id, None)

    def cancel(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        return True

    def is_running(self, run_id: UUID) -> bool:
        return run_id in self._tasks

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
