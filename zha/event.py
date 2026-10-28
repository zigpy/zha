"""Provide Event base classes for zhaws."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
import contextlib
from contextvars import ContextVar
import dataclasses
import functools
import inspect
import logging
from typing import Any

_LOGGER = logging.getLogger(__package__)

_suppress_events: ContextVar[bool] = ContextVar("suppress_events", default=False)


@contextlib.contextmanager
def suppress_events() -> Generator[None, None, None]:
    """Context manager to suppress event emission."""
    token = _suppress_events.set(True)

    try:
        yield
    finally:
        _suppress_events.reset(token)


@dataclasses.dataclass(frozen=True, slots=True)
class EventListener:
    """Listener for an event."""

    callback: Callable
    with_context: bool


class EventBase:
    """Base class for event handling and emitting objects."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize event base."""
        super().__init__(*args, **kwargs)
        self._listeners: dict[str, list[EventListener]] = {}
        self._event_tasks: list[asyncio.Task] = []
        self._global_listeners: list[EventListener] = []

    def on_event(  # pylint: disable=invalid-name
        self, event_name: str, callback: Callable, with_context: bool = False
    ) -> Callable:
        """Register an event callback."""
        listener = EventListener(callback=callback, with_context=with_context)

        listeners: list = self._listeners.setdefault(event_name, [])
        listeners.append(listener)

        def unsubscribe() -> None:
            """Unsubscribe listeners."""
            if listener in listeners:
                listeners.remove(listener)

        return unsubscribe

    def on_all_events(  # pylint: disable=invalid-name
        self, callback: Callable, with_context: bool = False
    ) -> Callable:
        """Register a callback for all events."""
        listener = EventListener(callback=callback, with_context=with_context)
        self._global_listeners.append(listener)

        def unsubscribe() -> None:
            """Unsubscribe listeners."""
            if listener in self._global_listeners:
                self._global_listeners.remove(listener)

        return unsubscribe

    def _handle_event_task_done(
        self, event_name: str, callback: Callable, task: asyncio.Task
    ) -> None:
        """Drop a finished listener task, logging an exception instead of losing it."""
        self._event_tasks.remove(task)

        if task.cancelled():
            return

        if (exc := task.exception()) is not None:
            _LOGGER.error(
                "Error calling listener %r for event %s",
                callback,
                event_name,
                exc_info=exc,
            )

    def _create_event_task(
        self, event_name: str, callback: Callable, coro: Any
    ) -> None:
        """Run a listener coroutine, keeping a reference until it finishes."""
        task = asyncio.create_task(coro)
        self._event_tasks.append(task)
        task.add_done_callback(
            functools.partial(self._handle_event_task_done, event_name, callback)
        )

    def once(
        self, event_name: str, callback: Callable, with_context: bool = False
    ) -> Callable:
        """Listen for an event exactly once."""
        if inspect.iscoroutinefunction(callback):

            async def async_event_listener(*args, **kwargs) -> None:
                unsub()
                self._create_event_task(event_name, callback, callback(*args, **kwargs))

            unsub = self.on_event(
                event_name, async_event_listener, with_context=with_context
            )
            return unsub

        def event_listener(*args, **kwargs) -> None:
            unsub()
            callback(*args, **kwargs)

        unsub = self.on_event(event_name, event_listener, with_context=with_context)
        return unsub

    def emit(self, event_name: str, data=None) -> None:
        """Run all callbacks for an event."""
        if _suppress_events.get():
            return

        listeners = [*self._listeners.get(event_name, []), *self._global_listeners]
        _LOGGER.debug(
            "Emitting event %s with data %r (%d listeners)",
            event_name,
            data,
            len(listeners),
        )

        for listener in listeners:
            # A listener that raises must not stop the remaining listeners from
            # running, nor propagate back into the code that emitted the event.
            try:
                if listener.with_context:
                    call = listener.callback(event_name, data)
                else:
                    call = listener.callback(data)
            except Exception:
                _LOGGER.exception(
                    "Error calling listener %r for event %s",
                    listener.callback,
                    event_name,
                )
                continue

            if inspect.iscoroutinefunction(listener.callback):
                self._create_event_task(event_name, listener.callback, call)

    def _handle_event_protocol(self, event) -> None:
        """Process an event based on event protocol."""
        _LOGGER.debug(
            "(%s) handling event protocol for event: %s", self.__class__.__name__, event
        )
        handler = getattr(self, f"handle_{event.event.replace(' ', '_')}", None)
        if handler is None:
            # Listeners registered with `on_all_events` receive every event, so
            # events without a handler are expected and ignored
            return
        if inspect.iscoroutinefunction(handler):
            self._create_event_task(event.event, handler, handler(event))
        else:
            handler(event)
