"""Async utilities for Zigbee Home Automation."""

from asyncio import AbstractEventLoop, Semaphore, Task, gather, get_running_loop
from collections.abc import Awaitable, Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")


def create_eager_task(
    coro: Coroutine[Any, Any, _T],
    *,
    name: str | None = None,
    loop: AbstractEventLoop | None = None,
) -> Task[_T]:
    """Create a task from a coroutine and schedule it to run immediately."""
    return Task(
        coro,
        loop=loop or get_running_loop(),
        name=name,
        eager_start=True,  # type: ignore[call-arg]
    )


async def gather_with_limited_concurrency(
    limit: int, *tasks: Any, return_exceptions: bool = False
) -> Any:
    """Wrap asyncio.gather to limit the number of concurrent tasks.

    From: https://stackoverflow.com/a/61478547/9127614
    """
    semaphore = Semaphore(limit)

    async def sem_task(task: Awaitable[Any]) -> Any:
        async with semaphore:
            return await task

    return await gather(
        *(create_eager_task(sem_task(task)) for task in tasks),
        return_exceptions=return_exceptions,
    )
