"""Decorators for zha."""

import asyncio
from collections.abc import Callable, Coroutine
import logging
import random
from typing import Any

_LOGGER = logging.getLogger(__name__)


def periodic(refresh_interval: tuple) -> Callable:
    """Make a method with periodic refresh."""

    def scheduler(func: Callable) -> Callable[[Any, Any], Coroutine[Any, Any, None]]:
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            sleep_time = random.randint(*refresh_interval)
            method_info = f"[{func.__module__}::{func.__qualname__}]"
            _LOGGER.debug(
                "Sleep time for periodic task: %s is %s seconds",
                method_info,
                sleep_time,
            )
            while True:
                try:
                    _LOGGER.debug(
                        "[%s] executing periodic task %s",
                        asyncio.current_task(),
                        method_info,
                    )
                    await func(*args, **kwargs)
                except asyncio.CancelledError:
                    _LOGGER.debug(
                        "[%s] Periodic task %s cancelled",
                        asyncio.current_task(),
                        method_info,
                    )
                    break
                except Exception as ex:  # pylint: disable=broad-except
                    _LOGGER.warning(
                        "[%s] Failed to poll using method %s",
                        asyncio.current_task(),
                        method_info,
                        exc_info=ex,
                    )
                await asyncio.sleep(sleep_time)

        return wrapper

    return scheduler
