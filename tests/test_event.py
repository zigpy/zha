"""Event tests for ZHA."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from zha.event import EventBase


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
    assert not event._golbal_listeners

    callback = MagicMock()

    unsub = event.on_event("test", callback)
    assert event._listeners == {"test": [callback]}
    unsub()
    assert event._listeners == {"test": []}

    unsub = event.on_all_events(callback)
    assert event._golbal_listeners == [callback]
    unsub()
    assert not event._golbal_listeners

    unsub = event.once("test", callback)
    assert "test" in event._listeners
    assert len(event._listeners["test"]) == 1
    unsub()
    assert event._listeners == {"test": []}


def test_event_base_emit():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._golbal_listeners

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
    assert not event._golbal_listeners


def test_event_base_emit_data():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._golbal_listeners

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
    assert not event._golbal_listeners


async def test_event_base_emit_coro():
    """Test event base class."""
    event = EventGenerator()
    assert not event._listeners
    assert not event._golbal_listeners

    callback = AsyncMock()

    event.once("test", callback)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    assert callback.await_count == 1
    assert callback.await_args[0] == ("data",)
    assert not event._event_tasks

    callback.reset_mock()

    unsub = event.on_event("test", callback)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    assert callback.await_count == 1
    assert callback.await_args[0] == ("data",)
    unsub()
    assert not event._event_tasks

    callback.reset_mock()

    unsub = event.on_all_events(callback)
    event.emit("test", "data")

    await asyncio.gather(*event._event_tasks)

    assert callback.await_count == 1
    assert callback.await_args[0] == ("data",)
    unsub()
    assert not event._event_tasks

    test_event = Event()
    event.on_event(test_event.event, event._handle_event_protocol)
    event.handle_test = AsyncMock()

    event.emit(test_event.event, test_event)

    await asyncio.gather(*event._event_tasks)

    assert event.handle_test.await_count == 1
    assert event.handle_test.await_args[0] == (test_event,)
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
