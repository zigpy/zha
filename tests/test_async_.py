"""Tests for the gateway module."""

import asyncio
import functools
import time
from unittest.mock import MagicMock, patch

import pytest

from zha import async_ as zha_async
from zha.application.gateway import Gateway
from zha.async_ import AsyncUtilMixin, ZHAJob, ZHAJobType, create_eager_task


@pytest.mark.parametrize("eager_start", [True, False])
async def test_cancellable_zhajob(zha_gateway: Gateway, eager_start: bool) -> None:
    """Simulate a shutdown, ensure cancellable jobs are cancelled."""
    job = MagicMock()

    def run_job(job: ZHAJob) -> None:
        """Call the action."""
        zha_gateway.async_run_zha_job(job, eager_start=eager_start)

    timer1 = zha_gateway.loop.call_later(
        60, run_job, ZHAJob(job, cancel_on_shutdown=True)
    )
    timer2 = zha_gateway.loop.call_later(60, run_job, ZHAJob(job))

    await zha_gateway.shutdown()

    assert timer1.cancelled()
    assert not timer2.cancelled()

    # Cleanup
    timer2.cancel()


async def test_async_add_zha_job_schedule_callback() -> None:
    """Test that we schedule callbacks and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))
    job = MagicMock()

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(job))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 1
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_add_zha_job_eager_start_coro_suspends(
    zha_gateway: Gateway,
) -> None:
    """Test scheduling a coro as a task that will suspend with eager_start."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_add_zha_job(ZHAJob(job_that_suspends), eager_start=True)
    assert not task.done()
    assert task in zha_gateway._tracked_completable_tasks
    await task
    assert task not in zha_gateway._tracked_completable_tasks


async def test_async_run_zha_job_eager_start_coro_suspends(
    zha_gateway: Gateway,
) -> None:
    """Test scheduling a coro as a task that will suspend with eager_start."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(ZHAJob(job_that_suspends))
    assert not task.done()
    assert task in zha_gateway._tracked_completable_tasks
    await task
    assert task not in zha_gateway._tracked_completable_tasks


async def test_async_add_zha_job_background(zha_gateway: Gateway) -> None:
    """Test scheduling a coro as a background task with async_add_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_add_zha_job(ZHAJob(job_that_suspends), background=True)
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_run_zha_job_background(zha_gateway: Gateway) -> None:
    """Test scheduling a coro as a background task with async_run_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(ZHAJob(job_that_suspends), background=True)
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_add_zha_job_eager_background(zha_gateway: Gateway) -> None:
    """Test scheduling a coro as an eager background task with async_add_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_add_zha_job(ZHAJob(job_that_suspends), background=True)
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


async def test_async_run_zha_job_eager_background(zha_gateway: Gateway) -> None:
    """Test scheduling a coro as an eager background task with async_run_zha_job."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(ZHAJob(job_that_suspends), background=True)
    assert not task.done()
    assert task in zha_gateway._background_tasks
    await task
    assert task not in zha_gateway._background_tasks


@pytest.mark.parametrize("background", [True, False])
async def test_async_run_zha_job_background_no_suspend(
    zha_gateway: Gateway,
    background: bool,
) -> None:
    """Test scheduling a coro as an eager background task with async_run_zha_job."""

    async def job_that_does_not_suspends():
        pass

    task = zha_gateway.async_run_zha_job(
        ZHAJob(job_that_does_not_suspends),
        background=background,
    )
    assert task is not None
    assert task.done()
    assert task not in zha_gateway._background_tasks
    assert task not in zha_gateway._tracked_completable_tasks
    await task


async def test_async_add_zha_job_coro_named(zha_gateway: Gateway) -> None:
    """Test that we schedule coroutines and add jobs to the job pool with a name."""

    async def mycoro():
        pass

    job = ZHAJob(mycoro, "named coro")
    assert "named coro" in str(job)
    assert job.name == "named coro"
    task = AsyncUtilMixin.async_add_zha_job(zha_gateway, job)
    assert "named coro" in str(task)


async def test_async_add_zha_job_eager_start(zha_gateway: Gateway) -> None:
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
    partial = functools.partial(job)

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
        zha_job = ZHAJob(job)
        task = AsyncUtilMixin.async_add_zha_job(zha_gateway, zha_job, eager_start=True)
        assert task is not None
        assert len(zha_gateway.loop.call_soon.mock_calls) == 0
        assert len(zha_gateway.add_job.mock_calls) == 0
        assert mock_create_eager_task.mock_calls
        await task


async def test_async_add_zha_job_schedule_partial_coroutinefunction(
    zha_gateway: Gateway,
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
    assert len(zha_gateway.loop.call_soon.mock_calls) == 1
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.loop.run_in_executor.mock_calls) == 0


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

    AsyncUtilMixin.async_run_zha_job(zha_gateway, ZHAJob(job))
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

    AsyncUtilMixin.async_run_zha_job(zha_gateway, ZHAJob(job))
    assert len(calls) == 1
    assert len(zha_gateway.async_add_job.mock_calls) == 0


async def test_async_create_task_pending_tasks_coro(zha_gateway: Gateway) -> None:
    """Add a coro to pending tasks."""
    call_count = []

    async def test_coro():
        """Test Coro."""
        call_count.append("call")

    for _ in range(2):
        zha_gateway.async_create_task(test_coro())

    assert len(zha_gateway._tracked_completable_tasks) == 2
    await zha_gateway.async_block_till_done()
    assert len(call_count) == 2
    assert len(zha_gateway._tracked_completable_tasks) == 0


@pytest.mark.parametrize("eager_start", [True, False])
async def test_background_task(zha_gateway: Gateway, eager_start: bool) -> None:
    """Test background tasks being quit."""
    result = asyncio.get_running_loop().create_future()

    async def test_task():
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            result.set_result("Foo")
            raise

    task = zha_gateway.async_create_background_task(
        test_task(), "happy task", eager_start=eager_start
    )
    assert "happy task" in str(task)
    await asyncio.sleep(0)
    await zha_gateway.shutdown()
    assert result.result() == "Foo"


def test_ZHAJob_passing_job_type():
    """Test passing the job type to ZHAJob when we already know it."""

    def callback_func():
        pass

    def not_callback_func():
        pass

    assert (
        ZHAJob(callback_func, job_type=ZHAJobType.Callback).job_type
        == ZHAJobType.Callback
    )

    # We should trust the job_type passed in
    assert (
        ZHAJob(not_callback_func, job_type=ZHAJobType.Callback).job_type
        == ZHAJobType.Callback
    )


async def test_async_add_executor_job_background(zha_gateway: Gateway) -> None:
    """Test running an executor job in the background."""
    calls = []

    def job():
        time.sleep(0.01)
        calls.append(1)

    async def _async_add_executor_job():
        await zha_gateway.async_add_executor_job(job)

    task = zha_gateway.async_create_background_task(
        _async_add_executor_job(), "background", eager_start=True
    )
    await zha_gateway.async_block_till_done()
    assert len(calls) == 0
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert len(calls) == 1
    await task


async def test_async_add_executor_job(zha_gateway: Gateway) -> None:
    """Test running an executor job."""
    calls = []

    def job():
        time.sleep(0.01)
        calls.append(1)

    async def _async_add_executor_job():
        await zha_gateway.async_add_executor_job(job)

    task = zha_gateway.async_create_task(
        _async_add_executor_job(), "background", eager_start=True
    )
    await zha_gateway.async_block_till_done()
    assert len(calls) == 1
    await task


async def test_gather_with_limited_concurrency() -> None:
    """Test gather_with_limited_concurrency limits the number of running tasks."""

    runs = 0
    now_time = time.time()

    async def _increment_runs_if_in_time():
        if time.time() - now_time > 0.1:
            return -1

        nonlocal runs
        runs += 1
        await asyncio.sleep(0.1)
        return runs

    results = await zha_async.gather_with_limited_concurrency(
        2, *(_increment_runs_if_in_time() for i in range(4))
    )

    assert results == [2, 2, -1, -1]


async def test_create_eager_task_312(zha_gateway: Gateway) -> None:  # pylint: disable=unused-argument
    """Test create_eager_task schedules a task eagerly in the event loop.

    For Python 3.12+, the task is scheduled eagerly in the event loop.
    """
    events = []

    async def _normal_task():
        events.append("normal")

    async def _eager_task():
        events.append("eager")

    task1 = zha_async.create_eager_task(_eager_task())
    task2 = asyncio.create_task(_normal_task())

    assert events == ["eager"]

    await asyncio.sleep(0)
    assert events == ["eager", "normal"]
    await task1
    await task2
