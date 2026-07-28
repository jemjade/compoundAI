"""TaskManager 동시 실행 제한, 중복 방지, 정리를 검증한다."""

import asyncio
from uuid import uuid4

from app.task_manager.manager import TaskManager


async def test_task_manager_limits_concurrency() -> None:
    manager = TaskManager(max_concurrency=1)
    active = 0
    maximum = 0

    async def job() -> None:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02)
        active -= 1

    manager.submit(uuid4(), job)
    manager.submit(uuid4(), job)
    await asyncio.gather(*list(manager._tasks.values()))  # noqa: SLF001

    assert maximum == 1
