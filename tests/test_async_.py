"""Tests for the gateway module."""

import asyncio
import functools
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from zha import async_ as zha_async
from zha.application.gateway import Gateway
from zha.async_ import AsyncUtilMixin, ZHAJob, ZHAJobType, create_eager_task
from zha.decorators import callback


async def test_zhajob_forbid_coroutine() -> None:
    """Test zhajob forbids coroutines."""

    async def bla():
        pass

    coro = bla()

    with pytest.raises(ValueError):
        _ = ZHAJob(coro).job_type

    # To avoid warning about unawaited coro
    await coro


@pytest.mark.parametrize("eager_start", [True, False])
async def test_cancellable_zhajob(zha_gateway: Gateway, eager_start: bool) -> None:
    """Simulate a shutdown, ensure cancellable jobs are cancelled."""
    job = MagicMock()

    @callback
    def run_job(job: ZHAJob) -> None:
        """Call the action."""
        zha_gateway.async_run_zha_job(job, eager_start=eager_start)

    timer1 = zha_gateway.loop.call_later(
        60, run_job, ZHAJob(callback(job), cancel_on_shutdown=True)
    )
    timer2 = zha_gateway.loop.call_later(60, run_job, ZHAJob(callback(job)))

    await zha_gateway.shutdown()

    assert timer1.cancelled()
    assert not timer2.cancelled()

    # Cleanup
    timer2.cancel()


async def test_async_add_zha_job_schedule_callback() -> None:
    """Test that we schedule callbacks and add jobs to the job pool."""
    zha_gateway = MagicMock(loop=MagicMock(wraps=asyncio.get_running_loop()))
    job = MagicMock()

    AsyncUtilMixin.async_add_zha_job(zha_gateway, ZHAJob(callback(job)))
    assert len(zha_gateway.loop.call_soon.mock_calls) == 1
    assert len(zha_gateway.loop.create_task.mock_calls) == 0
    assert len(zha_gateway.add_job.mock_calls) == 0


async def test_async_add_zha_job_eager_start_coro_suspends(
    zha_gateway: Gateway,
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
    zha_gateway: Gateway,
) -> None:
    """Test scheduling a coro as a task that will suspend with eager_start."""

    async def job_that_suspends():
        await asyncio.sleep(0)

    task = zha_gateway.async_run_zha_job(ZHAJob(callback(job_that_suspends)))
    assert not task.done()
    assert task in zha_gateway._tracked_completable_tasks
    await task
    assert task not in zha_gateway._tracked_completable_tasks


async def test_async_add_zha_job_background(zha_gateway: Gateway) -> None:
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


async def test_async_run_zha_job_background(zha_gateway: Gateway) -> None:
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


async def test_async_add_zha_job_eager_background(zha_gateway: Gateway) -> None:
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


async def test_async_run_zha_job_eager_background(zha_gateway: Gateway) -> None:
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
    zha_gateway: Gateway,
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


async def test_async_run_zha_job_synchronous(zha_gateway: Gateway) -> None:
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
        zha_job = ZHAJob(job)
        task = AsyncUtilMixin.async_add_zha_job(zha_gateway, zha_job, eager_start=True)
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


async def test_pending_scheduler(zha_gateway: Gateway) -> None:
    """Add a coro to pending tasks."""
    call_count = []

    async def test_coro():
        """Test Coro."""
        call_count.append("call")

    for _ in range(3):
        zha_gateway.async_add_job(test_coro())

    await asyncio.wait(zha_gateway._tracked_completable_tasks)

    assert len(zha_gateway._tracked_completable_tasks) == 0
    assert len(call_count) == 3


def test_add_job_pending_tasks_coro(zha_gateway: Gateway) -> None:
    """Add a coro to pending tasks."""

    async def test_coro():
        """Test Coro."""

    for _ in range(2):
        zha_gateway.add_job(test_coro())

    # Ensure add_job does not run immediately
    assert len(zha_gateway._tracked_completable_tasks) == 0


async def test_async_add_job_pending_tasks_coro(zha_gateway: Gateway) -> None:
    """Add a coro to pending tasks."""
    call_count = []

    async def test_coro():
        """Test Coro."""
        call_count.append("call")

    for _ in range(2):
        zha_gateway.async_add_job(test_coro())

    assert len(zha_gateway._tracked_completable_tasks) == 2
    await zha_gateway.async_block_till_done()
    assert len(call_count) == 2
    assert len(zha_gateway._tracked_completable_tasks) == 0


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


async def test_async_add_job_pending_tasks_executor(zha_gateway: Gateway) -> None:
    """Run an executor in pending tasks."""
    call_count = []

    def test_executor():
        """Test executor."""
        call_count.append("call")

    async def wait_finish_callback():
        """Wait until all stuff is scheduled."""
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    for _ in range(2):
        zha_gateway.async_add_job(test_executor)

    await wait_finish_callback()

    await zha_gateway.async_block_till_done()
    assert len(call_count) == 2


async def test_async_add_job_pending_tasks_callback(zha_gateway: Gateway) -> None:
    """Run a callback in pending tasks."""
    call_count = []

    @callback
    def test_callback():
        """Test callback."""
        call_count.append("call")

    async def wait_finish_callback():
        """Wait until all stuff is scheduled."""
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    for _ in range(2):
        zha_gateway.async_add_job(test_callback)

    await wait_finish_callback()

    await zha_gateway.async_block_till_done()

    assert len(zha_gateway._tracked_completable_tasks) == 0
    assert len(call_count) == 2


async def test_add_job_with_none(zha_gateway: Gateway) -> None:
    """Try to add a job with None as function."""
    with pytest.raises(ValueError):
        zha_gateway.async_add_job(None, "test_arg")

    with pytest.raises(ValueError):
        zha_gateway.add_job(None, "test_arg")


async def test_async_functions_with_callback(zha_gateway: Gateway) -> None:
    """Test we deal with async functions accidentally marked as callback."""
    runs = []

    @callback
    async def test():
        runs.append(True)

    await zha_gateway.async_add_job(test)
    assert len(runs) == 1

    zha_gateway.async_run_job(test)
    await zha_gateway.async_block_till_done()
    assert len(runs) == 2


async def test_async_run_job_starts_tasks_eagerly(zha_gateway: Gateway) -> None:
    """Test async_run_job starts tasks eagerly."""
    runs = []

    async def _test():
        runs.append(True)

    task = zha_gateway.async_run_job(_test)
    # No call to zha_gateway.async_block_till_done to ensure the task is run eagerly
    assert len(runs) == 1
    assert task.done()
    await task


async def test_async_run_job_starts_coro_eagerly(zha_gateway: Gateway) -> None:
    """Test async_run_job starts coros eagerly."""
    runs = []

    async def _test():
        runs.append(True)

    task = zha_gateway.async_run_job(_test())
    # No call to zha_gateway.async_block_till_done to ensure the task is run eagerly
    assert len(runs) == 1
    assert task.done()
    await task


@pytest.mark.parametrize("eager_start", [True, False])
async def test_background_task(zha_gateway: Gateway, eager_start: bool) -> None:
    """Test background tasks being quit."""
    result = asyncio.Future()

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

    @callback
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


@patch("concurrent.futures.Future")
@patch("threading.get_ident")
def test_run_callback_threadsafe_from_inside_event_loop(mock_ident, _) -> None:
    """Testing calling run_callback_threadsafe from inside an event loop."""
    callback_fn = MagicMock()

    loop = Mock(spec=["call_soon_threadsafe"])

    loop._thread_ident = None
    mock_ident.return_value = 5
    zha_async.run_callback_threadsafe(loop, callback_fn)
    assert len(loop.call_soon_threadsafe.mock_calls) == 1

    loop._thread_ident = 5
    mock_ident.return_value = 5
    with pytest.raises(RuntimeError):
        zha_async.run_callback_threadsafe(loop, callback_fn)
    assert len(loop.call_soon_threadsafe.mock_calls) == 1

    loop._thread_ident = 1
    mock_ident.return_value = 5
    zha_async.run_callback_threadsafe(loop, callback_fn)
    assert len(loop.call_soon_threadsafe.mock_calls) == 2


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


async def test_shutdown_run_callback_threadsafe(zha_gateway: Gateway) -> None:
    """Test we can shutdown run_callback_threadsafe."""
    zha_async.shutdown_run_callback_threadsafe(zha_gateway.loop)
    callback_fn = MagicMock()

    with pytest.raises(RuntimeError):
        zha_async.run_callback_threadsafe(zha_gateway.loop, callback_fn)


async def test_run_callback_threadsafe(zha_gateway: Gateway) -> None:
    """Test run_callback_threadsafe runs code in the event loop."""
    it_ran = False

    def callback_fn():
        nonlocal it_ran
        it_ran = True

    assert zha_async.run_callback_threadsafe(zha_gateway.loop, callback_fn)
    assert it_ran is False

    # Verify that async_block_till_done will flush
    # out the callback
    await zha_gateway.async_block_till_done()
    assert it_ran is True


async def test_run_callback_threadsafe_exception(zha_gateway: Gateway) -> None:
    """Test run_callback_threadsafe runs code in the event loop."""
    it_ran = False

    def callback_fn():
        nonlocal it_ran
        it_ran = True
        raise ValueError("Test")

    future = zha_async.run_callback_threadsafe(zha_gateway.loop, callback_fn)
    assert future
    assert it_ran is False

    # Verify that async_block_till_done will flush
    # out the callback
    await zha_gateway.async_block_till_done()
    assert it_ran is True

    with pytest.raises(ValueError):
        future.result()


async def test_callback_is_always_scheduled(zha_gateway: Gateway) -> None:
    """Test run_callback_threadsafe always calls call_soon_threadsafe before checking for shutdown."""
    # We have to check the shutdown state AFTER the callback is scheduled otherwise
    # the function could continue on and the caller call `future.result()` after
    # the point in the main thread where callbacks are no longer run.

    callback_fn = MagicMock()
    zha_async.shutdown_run_callback_threadsafe(zha_gateway.loop)

    with (
        patch.object(
            zha_gateway.loop, "call_soon_threadsafe"
        ) as mock_call_soon_threadsafe,
        pytest.raises(RuntimeError),
    ):
        zha_async.run_callback_threadsafe(zha_gateway.loop, callback_fn)

    mock_call_soon_threadsafe.assert_called_once()


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
