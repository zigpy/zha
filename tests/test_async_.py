"""Tests for the gateway module."""

import asyncio
import functools
from unittest.mock import MagicMock, patch

from zha.application.gateway import ZHAGateway
from zha.async_ import AsyncUtilMixin, ZHAJob, create_eager_task
from zha.decorators import callback


async def test_async_add_zha_job_schedule_callback() -> None:
    """Test that we schedule callbacks and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))
    job = MagicMock()

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(callback(job)))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 1
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_add_zha_job_eager_start_coro_suspends(
    zha_gateway: ZHAGateway,
) -> None:
    """Test scheduling a coro as a task that will suspend with eager_start."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_add_zha_job(
        ZHAJob(callback(job_that_suspends)), eager_start=True
    )
    assert not task.done()
    assert task in zha_gateway._tracked_completable_tasks
    await task
    assert task not in zha_gateway._tracked_completable_tasks


async def test_async_run_zha_job_eager_start_coro_suspends(
    zha_gateway: ZHAGateway,
) -> None:
    """Test scheduling a coro as a task that will suspend with eager_start."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(ZHAJob(callback(job_that_suspends)))
    assert not task.done()
    assert task in zha_gateway._tracked_completable_tasks
    await task
    assert task not in zha_gateway._tracked_completable_tasks


async def test_async_add_zha_job_background(zha_gateway: ZHAGateway) -> None:
    """Test scheduling a coro as a background task with async_add_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_add_zha_job(
        ZHAJob(callback(job_that_suspends)), background=True
    )
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_run_zha_job_background(zha_gateway: ZHAGateway) -> None:
    """Test scheduling a coro as a background task with async_run_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(
        ZHAJob(callback(job_that_suspends)), background=True
    )
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_add_zha_job_eager_background(zha_gateway: ZHAGateway) -> None:
    """Test scheduling a coro as an eager background task with async_add_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_add_zha_job(
        ZHAJob(callback(job_that_suspends)), background=True
    )
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_run_zha_job_eager_background(zha_gateway: ZHAGateway) -> None:
    """Test scheduling a coro as an eager background task with async_run_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(
        ZHAJob(callback(job_that_suspends)), background=True
    )
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_run_zha_job_background_synchronous(
    zha_gateway: ZHAGateway,
) -> None:
    """Test scheduling a coro as an eager background task with async_run_zha_job."""

    async def job_that_does_not_suspends():
        pass

    task = zha_gateway.async_run_zha_job(
        ZHAJob(callback(job_that_does_not_suspends)),
        background=True,
    )
    assert task.done()
    assert task not in zha_gateway._background_tasks
    assert task not in zha_gateway._tracked_completable_tasks
    await task


async def test_async_run_zha_job_synchronous(zha_gateway: ZHAGateway) -> None:
    """Test scheduling a coro as an eager task with async_run_zha_job."""

    async def job_that_does_not_suspends():
        pass

    task = zha_gateway.async_run_zha_job(
        ZHAJob(callback(job_that_does_not_suspends)),
        background=False,
    )
    assert task.done()
    assert task not in zha_gateway._background_tasks
    assert task not in zha_gateway._tracked_completable_tasks
    await task


async def test_async_add_zha_job_coro_named(zha_gateway: ZHAGateway) -> None:
    """Test that we schedule coroutines and add jobs to the job pool with a name."""

    async def mycoro():
        pass

    job = ZHAJob(mycoro, "named coro")
    assert "named coro" in str(job)
    assert job.name == "named coro"
    task = AsyncUtilMixin.async_add_zha_job(zha_gateway, job)
    assert "named coro" in str(task)


async def test_async_add_zha_job_eager_start(zha_gateway: ZHAGateway) -> None:
    """Test eager_start with async_add_zha_job."""

    async def mycoro():
        pass

    job = ZHAJob(mycoro, "named coro")
    assert "named coro" in str(job)
    assert job.name == "named coro"
    task = AsyncUtilMixin.async_add_zha_job(zha_gateway, job, eager_start=True)
    assert "named coro" in str(task)


async def test_async_add_zha_job_schedule_partial_callback() -> None:
    """Test that we schedule partial coros and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))
    job = MagicMock()
    partial = functools.partial(callback(job))

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(partial))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 1
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_add_zha_job_schedule_coroutinefunction() -> None:
    """Test that we schedule coroutines and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))

    async def job():
        pass

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(job))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 0
    assert len(zha_gateway.loop.create_task.mock_calls) == 1
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_add_zha_job_schedule_corofunction_eager_start() -> None:
    """Test that we schedule coroutines and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))

    async def job():
        pass

    with patch(
        "zha.async_.create_eager_task", wraps=create_eager_task
    ) as mock_create_eager_task:
        hass_job = ZHAJob(job)
        task = AsyncUtilMixin.async_add_zha_job(zha_gateway, hass_job, eager_start=True)
        assert len(zha_gateway.loop.call_soon.mock_calls) == 0
        assert len(zha_gateway.add_job.mock_calls) == 0
        assert mock_create_eager_task.mock_calls
        await task


async def test_async_add_zha_job_schedule_partial_coroutinefunction(
    zha_gateway: ZHAGateway,
) -> None:
    """Test that we schedule partial coros and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))

    async def job():
        pass

    partial = functools.partial(job)

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(partial))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 0
    assert len(zha_gateway.loop.create_task.mock_calls) == 1
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_add_job_add_zha_threaded_job_to_pool() -> None:
    """Test that we schedule coroutines and add jobs to the job pool."""
    zha_gateway = MagicMock()

    def job():
        pass

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(job))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 0
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.loop.run_in_executor.mock_calls) == 2


async def test_async_create_task_schedule_coroutine() -> None:
    """Test that we schedule coroutines and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))

    async def job():
        pass

    AsyncUtilMixin.async_create_task(zha_gateway, job())
    assert len(zha_gateway.loop.call_soon.mock_calls) == 0
    assert len(zha_gateway.loop.create_task.mock_calls) == 1
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_create_task_eager_start_schedule_coroutine() -> None:
    """Test that we schedule coroutines and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))

    async def job():
        pass

    AsyncUtilMixin.async_create_task(zha_gateway, job(), eager_start=True)
    # Should create the task directly since 3.12 supports eager_start
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_create_task_schedule_coroutine_with_name() -> None:
    """Test that we schedule coroutines and add jobs to the job pool with a name."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))

    async def job():
        pass

    task = AsyncUtilMixin.async_create_task(zha_gateway, job(), "named task")
    assert len(zha_gateway.loop.call_soon.mock_calls) == 0
    assert len(zha_gateway.loop.create_task.mock_calls) == 1
    assert len(zha_gateway.add_job.mock_calls) == 0
    assert "named task" in str(task)


async def test_async_run_eager_zha_job_calls_callback() -> None:
    """Test that the callback annotation is respected."""
    zha_gateway = MagicMock()
    calls = []

    def job():
        asyncio.get_running_loop()  # ensure we are in the event loop
        calls.append(1)

    AsyncUtilMixin.async_run_zha_job(zha_gateway, ZHAJob(callback(job)))
    assert len(calls) == 1


async def test_async_run_eager_zha_job_calls_coro_function() -> None:
    """Test running coros from async_run_zha_job with eager_start."""
    zha_gateway = MagicMock()

    async def job():
        pass

    AsyncUtilMixin.async_run_zha_job(zha_gateway, ZHAJob(job))
    assert len(zha_gateway.async_add_zha_job.mock_calls) == 1


async def test_async_run_zha_job_calls_callback() -> None:
    """Test that the callback annotation is respected."""
    zha_gateway = MagicMock()
    calls = []

    def job():
        calls.append(1)

    AsyncUtilMixin.async_run_zha_job(zha_gateway, ZHAJob(callback(job)))
    assert len(calls) == 1
    assert len(zha_gateway.async_add_job.mock_calls) == 0


async def test_async_run_zha_job_delegates_non_async() -> None:
    """Test that the callback annotation is respected."""
    zha_gateway = MagicMock()
    calls = []

    def job():
        calls.append(1)

    AsyncUtilMixin.async_run_zha_job(zha_gateway, ZHAJob(job))
    assert len(calls) == 0
    assert len(zha_gateway.async_add_zha_job.mock_calls) == 1
