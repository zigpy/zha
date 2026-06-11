"""Decorators for zha."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import logging
import random
from typing import Any, TypeVar

_LOGGER = logging.getLogger(__name__)
_TypeT = TypeVar("_TypeT", bound=type[Any])


class DictRegistry(dict[int | str, _TypeT]):
    """Dict Registry of items."""

    def register(self, name: int | str) -> Callable[[_TypeT], _TypeT]:
        """Return decorator to register an item with a specific name."""

        def decorator(cls: _TypeT) -> _TypeT:
            self[name] = cls
            return cls

        return decorator


class NestedDictRegistry(dict[int | str, dict[int | str | None, _TypeT]]):
    """Dict Registry of multiple items per key."""

    def register(
        self, name: int | str, sub_name: int | str | None = None
    ) -> Callable[[_TypeT], _TypeT]:
        """Return decorator to register an item under (name, sub_name)."""

        def decorator(cls: _TypeT) -> _TypeT:
            if name not in self:
                self[name] = {}
            self[name][sub_name] = cls
            return cls

        return decorator


class SetRegistry(set[int | str]):
    """Set Registry of items."""

    def register(self, name: int | str) -> Callable[[_TypeT], _TypeT]:
        """Return decorator to add a name to the set."""

        def decorator(cls: _TypeT) -> _TypeT:
            self.add(name)
            return cls

        return decorator


def periodic(refresh_interval: tuple, run_immediately: bool = False) -> Callable:
    """Make a method with periodic refresh."""

    def scheduler(func: Callable) -> Callable[[Any, Any], Coroutine[Any, Any, None]]:
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            sleep_time = random.randint(*refresh_interval)
            method_info = f"[{func.__module__}::{func.__qualname__}]"
            setattr(args[0], "__polling_interval", sleep_time)
            _LOGGER.debug(
                "Sleep time for periodic task: %s is %s seconds",
                method_info,
                sleep_time,
            )
            if not run_immediately:
                await asyncio.sleep(sleep_time)
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
