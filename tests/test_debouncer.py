"""Tests for debouncer implementation."""

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from zha.application.gateway import Gateway
from zha.debounce import Debouncer
from zha.decorators import callback

_LOGGER = logging.getLogger(__name__)


@pytest.mark.looptime
async def test_immediate_works(zha_gateway: Gateway) -> None:
    """Test immediate works."""
    calls = []
    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=AsyncMock(side_effect=lambda: calls.append(None)),
    )

    # Call when nothing happening
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Call when cooldown active setting execute at end to True
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True
    assert debouncer._job.target == debouncer.function

    # Canceling debounce in cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    before_job = debouncer._job

    # Call and let timer run out
    await debouncer.async_call()
    assert len(calls) == 2
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function
    assert debouncer._job == before_job

    # Test calling doesn't execute/cooldown if currently executing.
    await debouncer._execute_lock.acquire()
    await debouncer.async_call()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


@pytest.mark.looptime
async def test_immediate_works_with_schedule_call(zha_gateway: Gateway) -> None:
    """Test immediate works with scheduled calls."""
    calls = []
    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=AsyncMock(side_effect=lambda: calls.append(None)),
    )

    # Call when nothing happening
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Call when cooldown active setting execute at end to True
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True
    assert debouncer._job.target == debouncer.function

    # Canceling debounce in cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    before_job = debouncer._job

    # Call and let timer run out
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function
    assert debouncer._job == before_job

    # Test calling doesn't execute/cooldown if currently executing.
    await debouncer._execute_lock.acquire()
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


async def test_immediate_works_with_callback_function(zha_gateway: Gateway) -> None:
    """Test immediate works with callback function."""
    calls = []
    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=callback(Mock(side_effect=lambda: calls.append(None))),
    )

    # Call when nothing happening
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    debouncer.async_cancel()


async def test_immediate_works_with_executor_function(zha_gateway: Gateway) -> None:
    """Test immediate works with executor function."""
    calls = []
    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=Mock(side_effect=lambda: calls.append(None)),
    )

    # Call when nothing happening
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    debouncer.async_cancel()


@pytest.mark.looptime
async def test_immediate_works_with_passed_callback_function_raises(
    zha_gateway: Gateway,
) -> None:
    """Test immediate works with a callback function that raises."""
    calls = []

    @callback
    def _append_and_raise() -> None:
        calls.append(None)
        raise RuntimeError("forced_raise")

    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=_append_and_raise,
    )

    # Call when nothing happening
    with pytest.raises(RuntimeError, match="forced_raise"):
        await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Call when cooldown active setting execute at end to True
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True
    assert debouncer._job.target == debouncer.function

    # Canceling debounce in cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    before_job = debouncer._job

    # Call and let timer run out
    with pytest.raises(RuntimeError, match="forced_raise"):
        await debouncer.async_call()
    assert len(calls) == 2
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function
    assert debouncer._job == before_job

    # Test calling doesn't execute/cooldown if currently executing.
    await debouncer._execute_lock.acquire()
    await debouncer.async_call()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


@pytest.mark.looptime
async def test_immediate_works_with_passed_coroutine_raises(
    zha_gateway: Gateway,
) -> None:
    """Test immediate works with a coroutine that raises."""
    calls = []

    async def _append_and_raise() -> None:
        calls.append(None)
        raise RuntimeError("forced_raise")

    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=_append_and_raise,
    )

    # Call when nothing happening
    with pytest.raises(RuntimeError, match="forced_raise"):
        await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Call when cooldown active setting execute at end to True
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True
    assert debouncer._job.target == debouncer.function

    # Canceling debounce in cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    before_job = debouncer._job

    # Call and let timer run out
    with pytest.raises(RuntimeError, match="forced_raise"):
        await debouncer.async_call()
    assert len(calls) == 2
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function
    assert debouncer._job == before_job

    # Test calling doesn't execute/cooldown if currently executing.
    await debouncer._execute_lock.acquire()
    await debouncer.async_call()
    assert len(calls) == 2
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


@pytest.mark.looptime
async def test_not_immediate_works(zha_gateway: Gateway) -> None:
    """Test immediate works."""
    calls = []
    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.8,
        immediate=False,
        function=AsyncMock(side_effect=lambda: calls.append(None)),
    )

    # Call when nothing happening
    await debouncer.async_call()
    assert len(calls) == 0
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True

    # Call while still on cooldown
    await debouncer.async_call()
    assert len(calls) == 0
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True

    # Canceling while on cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False

    # Call and let timer run out
    await debouncer.async_call()
    assert len(calls) == 0
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Reset debouncer
    debouncer.async_cancel()

    # Test calling doesn't schedule if currently executing.
    await debouncer._execute_lock.acquire()
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


@pytest.mark.looptime
async def test_not_immediate_works_schedule_call(zha_gateway: Gateway) -> None:
    """Test immediate works with schedule call."""
    calls = []
    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.8,
        immediate=False,
        function=AsyncMock(side_effect=lambda: calls.append(None)),
    )

    # Call when nothing happening
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 0
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True

    # Call while still on cooldown
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 0
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True

    # Canceling while on cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False

    # Call and let timer run out
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 0
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Reset debouncer
    debouncer.async_cancel()

    # Test calling doesn't schedule if currently executing.
    await debouncer._execute_lock.acquire()
    debouncer.async_schedule_call()
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


@pytest.mark.looptime
async def test_immediate_works_with_function_swapped(zha_gateway: Gateway) -> None:
    """Test immediate works and we can change out the function."""
    calls = []

    one_function = AsyncMock(side_effect=lambda: calls.append(1))
    two_function = AsyncMock(side_effect=lambda: calls.append(2))

    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=True,
        function=one_function,
    )

    # Call when nothing happening
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    # Call when cooldown active setting execute at end to True
    await debouncer.async_call()
    assert len(calls) == 1
    assert debouncer._timer_task is not None
    assert debouncer._execute_at_end_of_timer is True
    assert debouncer._job.target == debouncer.function

    # Canceling debounce in cooldown
    debouncer.async_cancel()
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function

    before_job = debouncer._job
    debouncer.function = two_function

    # Call and let timer run out
    await debouncer.async_call()
    assert len(calls) == 2
    assert calls == [1, 2]
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 2
    assert calls == [1, 2]
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    assert debouncer._job.target == debouncer.function
    assert debouncer._job != before_job

    # Test calling doesn't execute/cooldown if currently executing.
    await debouncer._execute_lock.acquire()
    await debouncer.async_call()
    assert len(calls) == 2
    assert calls == [1, 2]
    assert debouncer._timer_task is None
    assert debouncer._execute_at_end_of_timer is False
    debouncer._execute_lock.release()
    assert debouncer._job.target == debouncer.function


async def test_shutdown(zha_gateway: Gateway, caplog: pytest.LogCaptureFixture) -> None:
    """Test shutdown."""
    calls = []
    future = asyncio.Future()

    async def _func() -> None:
        await future
        calls.append(None)

    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.01,
        immediate=False,
        function=_func,
    )

    # Ensure shutdown during a run doesn't create a cooldown timer
    zha_gateway.async_create_task(debouncer.async_call())
    await asyncio.sleep(0.01)
    debouncer.async_shutdown()
    future.set_result(True)
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    assert debouncer._timer_task is None

    assert "Debouncer call ignored as shutdown has been requested." not in caplog.text
    await debouncer.async_call()
    assert "Debouncer call ignored as shutdown has been requested." in caplog.text

    assert len(calls) == 1
    assert debouncer._timer_task is None


@pytest.mark.looptime
async def test_background(zha_gateway: Gateway) -> None:
    """Test background tasks are created when background is True."""
    calls = []

    async def _func() -> None:
        await asyncio.sleep(0.5)
        calls.append(None)

    debouncer = Debouncer(
        zha_gateway,
        _LOGGER,
        cooldown=0.8,
        immediate=True,
        function=_func,
        background=True,
    )

    await debouncer.async_call()
    assert len(calls) == 1

    debouncer.async_schedule_call()
    assert len(calls) == 1

    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done(wait_background_tasks=False)
    assert len(calls) == 1

    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 2

    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done(wait_background_tasks=False)
    assert len(calls) == 2
