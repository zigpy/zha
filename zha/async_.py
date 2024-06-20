"""Async utilities for Zigbee Home Automation."""

from __future__ import annotations

import asyncio
from asyncio import AbstractEventLoop, Future, Semaphore, Task, gather, get_running_loop
from collections.abc import Awaitable, Callable, Collection, Coroutine, Iterable
import concurrent.futures
import contextlib
from dataclasses import dataclass
import enum
import functools
from functools import cached_property
import logging
import threading
import time
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Generic,
    ParamSpec,
    TypeVar,
    TypeVarTuple,
    cast,
    overload,
)

from zigpy.types.named import EUI64

from zha.decorators import callback

_T = TypeVar("_T")
_R = TypeVar("_R")
_R_co = TypeVar("_R_co", covariant=True)
_P = ParamSpec("_P")
_Ts = TypeVarTuple("_Ts")
BLOCK_LOG_TIMEOUT: Final[int] = 60

_SHUTDOWN_RUN_CALLBACK_THREADSAFE = "_zha_shutdown_run_callback_threadsafe"

_LOGGER = logging.getLogger(__name__)


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
        eager_start=True,
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


def run_callback_threadsafe(
    loop: AbstractEventLoop, callback_fn: Callable[[*_Ts], _T], *args: *_Ts
) -> concurrent.futures.Future[_T]:
    """Submit a callback object to a given event loop.

    Return a concurrent.futures.Future to access the result.
    """
    ident = loop.__dict__.get("_thread_ident")
    if ident is not None and ident == threading.get_ident():
        raise RuntimeError("Cannot be called from within the event loop")

    future: concurrent.futures.Future[_T] = concurrent.futures.Future()

    def run_callback() -> None:
        """Run callback and store result."""
        try:
            future.set_result(callback_fn(*args))
        except Exception as exc:  # pylint: disable=broad-except
            if future.set_running_or_notify_cancel():
                future.set_exception(exc)
            else:
                _LOGGER.warning("Exception on lost future: ", exc_info=True)

    loop.call_soon_threadsafe(run_callback)

    if hasattr(loop, _SHUTDOWN_RUN_CALLBACK_THREADSAFE):
        #
        # If the final `Gateway.async_block_till_done` in
        # `Gateway.shutdown` has already been called, the callback
        # will never run and, `future.result()` will block forever which
        # will prevent the thread running this code from shutting down which
        # will result in a deadlock when the main thread attempts to shutdown
        # the executor and `.join()` the thread running this code.
        #
        # To prevent this deadlock we do the following on shutdown:
        #
        # 1. Set the _SHUTDOWN_RUN_CALLBACK_THREADSAFE attr on this function
        #    by calling `shutdown_run_callback_threadsafe`
        # 2. Call `zha_gateway.async_block_till_done` at least once after shutdown
        #    to ensure all callbacks have run
        # 3. Raise an exception here to ensure `future.result()` can never be
        #    called and hit the deadlock since once `shutdown_run_callback_threadsafe`
        #    we cannot promise the callback will be executed.
        #
        raise RuntimeError("The event loop is in the process of shutting down.")

    return future


def shutdown_run_callback_threadsafe(loop: AbstractEventLoop) -> None:
    """Call when run_callback_threadsafe should prevent creating new futures.

    We must finish all callbacks before the executor is shutdown
    or we can end up in a deadlock state where:

    `executor.result()` is waiting for its `._condition`
    and the executor shutdown is trying to `.join()` the
    executor thread.

    This function is considered irreversible and should only ever
    be called when ZHA is going to shutdown and
    python is going to exit.
    """
    setattr(loop, _SHUTDOWN_RUN_CALLBACK_THREADSAFE, True)


def cancelling(task: Future[Any]) -> bool:
    """Return True if task is cancelling."""
    return bool((cancelling_ := getattr(task, "cancelling", None)) and cancelling_())


@enum.unique
class ZHAJobType(enum.Enum):
    """Represent a job type."""

    Coroutinefunction = 1
    Callback = 2
    Executor = 3


class ZHAJob(Generic[_P, _R_co]):
    """Represent a job to be run later.

    We check the callable type in advance
    so we can avoid checking it every time
    we run the job.
    """

    def __init__(
        self,
        target: Callable[_P, _R_co],
        name: str | None = None,
        *,
        cancel_on_shutdown: bool | None = None,
        job_type: ZHAJobType | None = None,
    ) -> None:
        """Create a job object."""
        self.target = target
        self.name = name
        self._cancel_on_shutdown = cancel_on_shutdown
        self._job_type = job_type

    @cached_property
    def job_type(self) -> ZHAJobType:
        """Return the job type."""
        return self._job_type or get_zhajob_callable_job_type(self.target)

    @property
    def cancel_on_shutdown(self) -> bool | None:
        """Return if the job should be cancelled on shutdown."""
        return self._cancel_on_shutdown

    def __repr__(self) -> str:
        """Return the job."""
        return f"<Job {self.name} {self.job_type} {self.target}>"


@dataclass(frozen=True)
class ZHAJobWithArgs:
    """Container for a ZHAJob and arguments."""

    job: ZHAJob[..., Coroutine[Any, Any, Any] | Any]
    args: Iterable[Any]


def get_zhajob_callable_job_type(target: Callable[..., Any]) -> ZHAJobType:
    """Determine the job type from the callable."""
    # Check for partials to properly determine if coroutine function
    check_target = target
    while isinstance(check_target, functools.partial):
        check_target = check_target.func

    if asyncio.iscoroutinefunction(check_target):
        return ZHAJobType.Coroutinefunction
    if is_callback(check_target):
        return ZHAJobType.Callback
    if asyncio.iscoroutine(check_target):
        raise ValueError("Coroutine not allowed to be passed to ZHAJob")
    return ZHAJobType.Executor


def is_callback(func: Callable[..., Any]) -> bool:
    """Check if function is safe to be called in the event loop."""
    return getattr(func, "_zha_callback", False) is True


class AsyncUtilMixin:
    """Mixin for dealing with async stuff."""

    def __init__(self, *args, **kw_args) -> None:
        """Initialize the async mixin."""
        self.loop = asyncio.get_running_loop()
        self._tracked_completable_tasks: set[asyncio.Task] = set()
        self._device_init_tasks: dict[EUI64, asyncio.Task] = {}
        self._background_tasks: set[asyncio.Future[Any]] = set()
        self._untracked_background_tasks: set[asyncio.Future[Any]] = set()
        super().__init__(*args, **kw_args)

    async def shutdown(self) -> None:
        """Shutdown the executor."""

        # Prevent run_callback_threadsafe from scheduling any additional
        # callbacks in the event loop as callbacks created on the futures
        # it returns will never run after the final `self.async_block_till_done`
        # which will cause the futures to block forever when waiting for
        # the `result()` which will cause a deadlock when shutting down the executor.
        shutdown_run_callback_threadsafe(self.loop)

        async def _cancel_tasks(tasks_to_cancel: Iterable) -> None:
            tasks = [t for t in tasks_to_cancel if not (t.done() or t.cancelled())]
            for task in tasks:
                _LOGGER.debug("Cancelling task: %s", task)
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)

        await _cancel_tasks(self._background_tasks)
        await _cancel_tasks(self._tracked_completable_tasks)
        await _cancel_tasks(self._device_init_tasks.values())
        await _cancel_tasks(self._untracked_background_tasks)
        self._cancel_cancellable_timers()

    async def async_block_till_done(self, wait_background_tasks: bool = False) -> None:
        """Block until all pending work is done."""
        # To flush out any call_soon_threadsafe
        await asyncio.sleep(0)
        start_time: float | None = None
        current_task = asyncio.current_task()
        while tasks := [
            task
            for task in (
                self._tracked_completable_tasks | self._background_tasks
                if wait_background_tasks
                else self._tracked_completable_tasks
            )
            if task is not current_task and not cancelling(task)
        ]:
            await self._await_and_log_pending(tasks)

            if start_time is None:
                # Avoid calling monotonic() until we know
                # we may need to start logging blocked tasks.
                start_time = 0
            elif start_time == 0:
                # If we have waited twice then we set the start
                # time
                start_time = time.monotonic()
            elif time.monotonic() - start_time > BLOCK_LOG_TIMEOUT:
                # We have waited at least three loops and new tasks
                # continue to block. At this point we start
                # logging all waiting tasks.
                for task in tasks:
                    _LOGGER.debug("Waiting for task: %s", task)

    async def _await_and_log_pending(
        self, pending: Collection[asyncio.Future[Any]]
    ) -> None:
        """Await and log tasks that take a long time."""
        wait_time = 0
        while pending:
            _, pending = await asyncio.wait(pending, timeout=BLOCK_LOG_TIMEOUT)
            if not pending:
                return
            wait_time += BLOCK_LOG_TIMEOUT
            for task in pending:
                _LOGGER.debug("Waited %s seconds for task: %s", wait_time, task)

    def track_task(self, task: asyncio.Task) -> None:
        """Create a tracked task."""
        self._tracked_completable_tasks.add(task)
        task.add_done_callback(self._tracked_completable_tasks.remove)

    def add_job(
        self, target: Callable[..., Any] | Coroutine[Any, Any, Any], *args: Any
    ) -> None:
        """Add a job to be executed by the event loop or by an executor.

        If the job is either a coroutine or decorated with @callback, it will be
        run by the event loop, if not it will be run by an executor.

        target: target to call.
        args: parameters for method to call.
        """
        if target is None:
            raise ValueError("Don't call add_job with None")
        if asyncio.iscoroutine(target):
            self.loop.call_soon_threadsafe(
                functools.partial(self.async_create_task, target, eager_start=True)
            )
            return
        if TYPE_CHECKING:
            target = cast(Callable[..., Any], target)
        self.loop.call_soon_threadsafe(
            functools.partial(
                self.async_add_zha_job, ZHAJob(target), *args, eager_start=True
            )
        )

    def _cancel_cancellable_timers(self) -> None:
        """Cancel timer handles marked as cancellable."""
        # pylint: disable-next=protected-access
        handles: Iterable[asyncio.TimerHandle] = self.loop._scheduled  # type: ignore[attr-defined]
        for handle in handles:
            if (
                not handle.cancelled()
                and (args := handle._args)  # pylint: disable=protected-access
                and type(job := args[0]) is ZHAJob
                and job.cancel_on_shutdown
            ):
                handle.cancel()

    @overload
    @callback
    def async_add_job(
        self,
        target: Callable[..., Coroutine[Any, Any, _R]],
        *args: Any,
        eager_start: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @overload
    @callback
    def async_add_job(
        self,
        target: Callable[..., Coroutine[Any, Any, _R] | _R],
        *args: Any,
        eager_start: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @overload
    @callback
    def async_add_job(
        self,
        target: Coroutine[Any, Any, _R],
        *args: Any,
        eager_start: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @callback
    def async_add_job(
        self,
        target: Callable[..., Coroutine[Any, Any, _R] | _R] | Coroutine[Any, Any, _R],
        *args: Any,
        eager_start: bool = False,
    ) -> asyncio.Future[_R] | None:
        """Add a job to be executed by the event loop or by an executor.

        If the job is either a coroutine or decorated with @callback, it will be
        run by the event loop, if not it will be run by an executor.

        This method must be run in the event loop.

        target: target to call.
        args: parameters for method to call.
        """
        if target is None:
            raise ValueError("Don't call async_add_job with None")

        if asyncio.iscoroutine(target):
            return self.async_create_task(target, eager_start=eager_start)

        # This code path is performance sensitive and uses
        # if TYPE_CHECKING to avoid the overhead of constructing
        # the type used for the cast. For history see:
        # https://github.com/home-assistant/core/pull/71960
        if TYPE_CHECKING:
            target = cast(Callable[..., Coroutine[Any, Any, _R] | _R], target)
        return self.async_add_zha_job(ZHAJob(target), *args, eager_start=eager_start)

    @overload
    @callback
    def async_add_zha_job(
        self,
        zhajob: ZHAJob[..., Coroutine[Any, Any, _R]],
        *args: Any,
        eager_start: bool = False,
        background: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @overload
    @callback
    def async_add_zha_job(
        self,
        zhajob: ZHAJob[..., Coroutine[Any, Any, _R] | _R],
        *args: Any,
        eager_start: bool = False,
        background: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @callback
    def async_add_zha_job(
        self,
        zhajob: ZHAJob[..., Coroutine[Any, Any, _R] | _R],
        *args: Any,
        eager_start: bool = False,
        background: bool = False,
    ) -> asyncio.Future[_R] | None:
        """Add a ZHAJob from within the event loop.

        If eager_start is True, coroutine functions will be scheduled eagerly.
        If background is True, the task will created as a background task.

        This method must be run in the event loop.
        zhajob: ZHAJob to call.
        args: parameters for method to call.
        """
        task: asyncio.Future[_R]
        # This code path is performance sensitive and uses
        # if TYPE_CHECKING to avoid the overhead of constructing
        # the type used for the cast. For history see:
        # https://github.com/home-assistant/core/pull/71960
        if zhajob.job_type is ZHAJobType.Coroutinefunction:
            if TYPE_CHECKING:
                zhajob.target = cast(
                    Callable[..., Coroutine[Any, Any, _R]], zhajob.target
                )
            # Use loop.create_task
            # to avoid the extra function call in asyncio.create_task.
            if eager_start:
                task = create_eager_task(
                    zhajob.target(*args),
                    name=zhajob.name,
                    loop=self.loop,
                )
                if task.done():
                    return task
            else:
                task = self.loop.create_task(zhajob.target(*args), name=zhajob.name)
        elif zhajob.job_type is ZHAJobType.Callback:
            if TYPE_CHECKING:
                zhajob.target = cast(Callable[..., _R], zhajob.target)
            self.loop.call_soon(zhajob.target, *args)
            return None
        else:
            if TYPE_CHECKING:
                zhajob.target = cast(Callable[..., _R], zhajob.target)
            task = self.loop.run_in_executor(None, zhajob.target, *args)

        task_bucket = (
            self._background_tasks if background else self._tracked_completable_tasks
        )
        task_bucket.add(task)
        task.add_done_callback(task_bucket.remove)

        return task

    def create_task(
        self, target: Coroutine[Any, Any, Any], name: str | None = None
    ) -> None:
        """Add task to the executor pool.

        target: target to call.
        """
        self.loop.call_soon_threadsafe(
            functools.partial(self.async_create_task, target, name, eager_start=True)
        )

    @callback
    def async_create_task(
        self,
        target: Coroutine[Any, Any, _R],
        name: str | None = None,
        eager_start: bool = False,
    ) -> asyncio.Task[_R]:
        """Create a task from within the event loop.

        This method must be run in the event loop. If you are using this in your
        integration, use the create task methods on the config entry instead.

        target: target to call.
        """
        if eager_start:
            task = create_eager_task(target, name=name, loop=self.loop)
            if task.done():
                return task
        else:
            # Use loop.create_task
            # to avoid the extra function call in asyncio.create_task.
            task = self.loop.create_task(target, name=name)
        self._tracked_completable_tasks.add(task)
        task.add_done_callback(self._tracked_completable_tasks.remove)
        return task

    @callback
    def async_create_background_task(
        self,
        target: Coroutine[Any, Any, _R],
        name: str,
        eager_start: bool = False,
        untracked: bool = False,
    ) -> asyncio.Task[_R]:
        """Create a task from within the event loop.

        This type of task is for background tasks that usually run for
        the lifetime of ZHA or an integration's setup.

        A background task is different from a normal task:

          - Will not block startup
          - Will be automatically cancelled on shutdown
          - Calls to async_block_till_done will not wait for completion

        If you are using this in your integration, use the create task
        methods on the config entry instead.

        This method must be run in the event loop.
        """
        if eager_start:
            task = create_eager_task(target, name=name, loop=self.loop)
            if task.done():
                return task
        else:
            # Use loop.create_task
            # to avoid the extra function call in asyncio.create_task.
            task = self.loop.create_task(target, name=name)

        task_bucket = (
            self._untracked_background_tasks if untracked else self._background_tasks
        )
        task_bucket.add(task)
        task.add_done_callback(task_bucket.remove)
        return task

    @callback
    def async_add_executor_job(
        self, target: Callable[..., _T], *args: Any
    ) -> asyncio.Future[_T]:
        """Add an executor job from within the event loop."""
        task = self.loop.run_in_executor(None, target, *args)
        tracked = asyncio.current_task() in self._tracked_completable_tasks
        task_bucket = (
            self._tracked_completable_tasks if tracked else self._background_tasks
        )
        task_bucket.add(task)
        task.add_done_callback(task_bucket.remove)
        return task

    @overload
    @callback
    def async_run_zha_job(
        self,
        zhajob: ZHAJob[..., Coroutine[Any, Any, _R]],
        *args: Any,
        background: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @overload
    @callback
    def async_run_zha_job(
        self,
        zhajob: ZHAJob[..., Coroutine[Any, Any, _R] | _R],
        *args: Any,
        background: bool = False,
    ) -> asyncio.Future[_R] | None: ...

    @callback
    def async_run_zha_job(
        self,
        zhajob: ZHAJob[..., Coroutine[Any, Any, _R] | _R],
        *args: Any,
        background: bool = False,
    ) -> asyncio.Future[_R] | None:
        """Run a ZHAJob from within the event loop.

        This method must be run in the event loop.

        If background is True, the task will created as a background task.

        zhajob: ZHAJob
        args: parameters for method to call.
        """
        # This code path is performance sensitive and uses
        # if TYPE_CHECKING to avoid the overhead of constructing
        # the type used for the cast. For history see:
        # https://github.com/home-assistant/core/pull/71960
        if zhajob.job_type is ZHAJobType.Callback:
            if TYPE_CHECKING:
                zhajob.target = cast(Callable[..., _R], zhajob.target)
            zhajob.target(*args)
            return None

        return self.async_add_zha_job(
            zhajob, *args, eager_start=True, background=background
        )

    @overload
    @callback
    def async_run_job(
        self, target: Callable[..., Coroutine[Any, Any, _R]], *args: Any
    ) -> asyncio.Future[_R] | None: ...

    @overload
    @callback
    def async_run_job(
        self, target: Callable[..., Coroutine[Any, Any, _R] | _R], *args: Any
    ) -> asyncio.Future[_R] | None: ...

    @overload
    @callback
    def async_run_job(
        self, target: Coroutine[Any, Any, _R], *args: Any
    ) -> asyncio.Future[_R] | None: ...

    @callback
    def async_run_job(
        self,
        target: Callable[..., Coroutine[Any, Any, _R] | _R] | Coroutine[Any, Any, _R],
        *args: Any,
    ) -> asyncio.Future[_R] | None:
        """Run a job from within the event loop.

        This method must be run in the event loop.

        target: target to call.
        args: parameters for method to call.
        """
        if asyncio.iscoroutine(target):
            return self.async_create_task(target, eager_start=True)

        # This code path is performance sensitive and uses
        # if TYPE_CHECKING to avoid the overhead of constructing
        # the type used for the cast. For history see:
        # https://github.com/home-assistant/core/pull/71960
        if TYPE_CHECKING:
            target = cast(Callable[..., Coroutine[Any, Any, _R] | _R], target)
        return self.async_run_zha_job(ZHAJob(target), *args)
