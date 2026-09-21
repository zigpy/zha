"""Event tests for ZHA."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from zha.event import EventBase, EventListener


class EventGenerator(EventBase):
    """Event generator for testing."""


class Event:
    """Event class for testing."""

    event = "test"
    event_type = "testing"


def test_event_base_unsubs():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._global_listeners

    callback = MagicMock()

    unsub = event.on_event("test", callback)
    assert event._listeners == {
        "test": [EventListener(callback=callback, with_context=False)]
    }
    unsub()
    assert event._listeners == {"test": []}

    unsub = event.on_all_events(callback)
    assert event._global_listeners == [
        EventListener(callback=callback, with_context=False)
    ]
    unsub()
    assert not event._global_listeners

    unsub = event.once("test", callback)
    assert "test" in event._listeners
    assert len(event._listeners["test"]) == 1
    unsub()
    assert event._listeners == {"test": []}


def test_event_base_emit():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._global_listeners

    callback = MagicMock()

    event.once("test", callback)
    event.emit("test")
    assert callback.called

    callback.reset_mock()
    event.emit("test")
    assert not callback.called

    unsub = event.on_event("test", callback)
    event.emit("test")
    assert callback.called
    unsub()

    callback.reset_mock()
    unsub = event.on_all_events(callback)
    event.emit("test")
    assert callback.called
    unsub()

    assert "test" in event._listeners
    assert event._listeners == {"test": []}
    assert not event._global_listeners


def test_event_base_emit_data():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._global_listeners

    callback = MagicMock()

    event.once("test", callback)
    event.emit("test", "data")
    assert callback.called
    assert callback.call_args[0] == ("data",)

    callback.reset_mock()
    event.emit("test", "data")
    assert not callback.called

    unsub = event.on_event("test", callback)
    event.emit("test", "data")
    assert callback.called
    assert callback.call_args[0] == ("data",)
    unsub()

    callback.reset_mock()
    unsub = event.on_all_events(callback)
    event.emit("test", "data")
    assert callback.called
    assert callback.call_args[0] == ("data",)
    unsub()

    assert "test" in event._listeners
    assert event._listeners == {"test": []}
    assert not event._global_listeners


async def test_event_base_emit_coro():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._global_listeners

    callback = AsyncMock()

    event.once("test", callback)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    assert callback.await_count == 1
    assert callback.mock_calls == [call("data")]
    assert not event._event_tasks

    callback.reset_mock()

    unsub = event.on_event("test", callback)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    assert callback.await_count == 1
    assert callback.mock_calls == [call("data")]
    unsub()
    assert not event._event_tasks

    callback.reset_mock()

    unsub = event.on_all_events(callback)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    assert callback.await_count == 1
    assert callback.mock_calls == [call("data")]
    unsub()
    assert not event._event_tasks

    test_event = Event()
    event.on_event(test_event.event, event._handle_event_protocol)
    event.handle_test = AsyncMock()

    event.emit(test_event.event, test_event)

    await asyncio.gather(*event._event_tasks)

    assert event.handle_test.await_count == 1
    assert event.handle_test.mock_calls == [call(test_event)]
    assert not event._event_tasks


async def test_event_emit_with_context():
    """Test event emitting with context."""

    event = EventGenerator()
    async_callback = AsyncMock()
    sync_callback = MagicMock()

    event.once("test", sync_callback, with_context=True)
    event.once("test", async_callback, with_context=True)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    sync_callback.assert_called_once_with("test", "data")
    async_callback.assert_awaited_once_with("test", "data")


async def test_event_base_once_async_multiple_emits_same_tick() -> None:
    """Test an async once listener runs once for back-to-back emits."""
    event = EventGenerator()
    callback = AsyncMock()

    event.once("test", callback)
    event.emit("test", "first")
    event.emit("test", "second")

    assert event._listeners == {"test": []}
    assert len(event._event_tasks) == 1

    await asyncio.gather(*event._event_tasks)

    assert callback.await_args_list == [call("first")]
    assert not event._event_tasks


def test_event_base_once_reentrant_emit() -> None:
    """Test a once listener runs once when an earlier listener re-emits."""
    event = EventGenerator()
    reentered = False

    def reentrant_listener(data: str) -> None:
        nonlocal reentered
        if not reentered:
            reentered = True
            event.emit("test", "inner")

    event.on_event("test", reentrant_listener)
    callback = MagicMock()
    event.once("test", callback)

    event.emit("test", "outer")

    callback.assert_called_once_with("inner")


async def test_event_base_emit_async_callable_object() -> None:
    """Test an async callable listener is scheduled and tracked."""

    class AsyncCallable:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def __call__(self, data: str) -> None:
            self.calls.append(data)

    event = EventGenerator()
    callback = AsyncCallable()
    event.on_event("test", callback)

    event.emit("test", "payload")

    assert len(event._event_tasks) == 1
    await asyncio.gather(*event._event_tasks)

    assert callback.calls == ["payload"]
    assert not event._event_tasks


@pytest.mark.parametrize("use_task", [False, True], ids=["future", "task"])
async def test_event_base_emit_sync_listener_returning_future(
    use_task: bool,
) -> None:
    """Test a Future returned by a sync listener is tracked unchanged."""
    event = EventGenerator()
    release = asyncio.Event()
    if use_task:
        future: asyncio.Future[None] = asyncio.create_task(release.wait())
    else:
        future = asyncio.get_running_loop().create_future()
    callback = MagicMock(return_value=future)
    event.on_event("test", callback)

    event.emit("test", "payload")

    try:
        callback.assert_called_once_with("payload")
        assert event._event_tasks == [future]
    finally:
        if use_task:
            release.set()
            await future
        else:
            future.set_result(None)
        await asyncio.sleep(0)

    assert not event._event_tasks


def test_handle_event_protocol():
    """Test event base class."""

    event_handler = EventGenerator()
    event_handler.handle_test = MagicMock()
    event_handler.on_event("test", event_handler._handle_event_protocol)

    event = Event()
    event_handler.emit(event.event, event)

    assert event_handler.handle_test.called
    assert event_handler.handle_test.call_args[0] == (event,)


def test_handle_event_protocol_no_event(caplog: pytest.LogCaptureFixture):
    """Test event base class."""

    event_handler = EventGenerator()
    event_handler.on_event("not_test", event_handler._handle_event_protocol)
    event = Event()
    event_handler.emit("not_test", event)

    assert "Received unknown event:" in caplog.text
