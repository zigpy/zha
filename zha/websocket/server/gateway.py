"""ZHAWSS websocket server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from time import monotonic
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Literal

import websockets

from zha.application.discovery import PLATFORMS
from zha.application.gateway import Gateway
from zha.application.helpers import ZHAData
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.model import WebSocketCommand
from zha.websocket.server.api.platforms.api import load_platform_entity_apis
from zha.websocket.server.client import ClientManager
from zha.websocket.server.gateway_api import load_api as load_zigbee_controller_api

if TYPE_CHECKING:
    from zha.websocket.server.client import Client

BLOCK_LOG_TIMEOUT: Final[int] = 60
_LOGGER = logging.getLogger(__name__)


class WebSocketGateway(Gateway):
    """ZHAWSS server implementation."""

    def __init__(self, config: ZHAData) -> None:
        """Initialize the websocket gateway."""
        super().__init__(config)
        self._ws_server: websockets.WebSocketServer | None = None
        self._client_manager: ClientManager = ClientManager(self)
        self._stopped_event: asyncio.Event = asyncio.Event()
        self._tracked_ws_tasks: set[asyncio.Task] = set()
        self.data: dict[Any, Any] = {}
        for platform in PLATFORMS:
            self.data.setdefault(platform, [])
        self._register_api_commands()

    @property
    def is_serving(self) -> bool:
        """Return whether or not the websocket server is serving."""
        return self._ws_server is not None and self._ws_server.is_serving

    @property
    def client_manager(self) -> ClientManager:
        """Return the zigbee application controller."""
        return self._client_manager

    async def start_server(self) -> None:
        """Start the websocket server."""
        assert self._ws_server is None
        self._stopped_event.clear()
        self._ws_server = await websockets.serve(
            self.client_manager.add_client,
            self.config.server_config.host,
            self.config.server_config.port,
            logger=_LOGGER,
        )
        if self.config.server_config.network_auto_start:
            await self.async_initialize()
            await self.async_initialize_devices_and_entities()

    async def async_initialize(self) -> None:
        """Initialize controller and connect radio."""
        await super().async_initialize()
        self.on_all_events(self.client_manager.broadcast)

    async def stop_server(self) -> None:
        """Stop the websocket server."""
        if self._ws_server is None:
            self._stopped_event.set()
            return

        assert self._ws_server is not None

        await self.shutdown()

        self._ws_server.close()
        await self._ws_server.wait_closed()
        self._ws_server = None

        self._stopped_event.set()

    async def wait_closed(self) -> None:
        """Wait until the server is not running."""
        await self._stopped_event.wait()
        _LOGGER.info("Server stopped. Completing remaining tasks...")
        tasks = [t for t in self._tracked_ws_tasks if not (t.done() or t.cancelled())]
        for task in tasks:
            _LOGGER.debug("Cancelling task: %s", task)
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

        tasks = [
            t
            for t in self._tracked_completable_tasks
            if not (t.done() or t.cancelled())
        ]
        for task in tasks:
            _LOGGER.debug("Cancelling task: %s", task)
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    def track_ws_task(self, task: asyncio.Task) -> None:
        """Create a tracked ws task."""
        self._tracked_ws_tasks.add(task)
        task.add_done_callback(self._tracked_ws_tasks.remove)

    async def async_block_till_done(self, wait_background_tasks=False):
        """Block until all pending work is done."""
        # To flush out any call_soon_threadsafe
        await asyncio.sleep(0.001)
        start_time: float | None = None

        while self._tracked_ws_tasks:
            pending = [task for task in self._tracked_ws_tasks if not task.done()]
            self._tracked_ws_tasks.clear()
            if pending:
                await self._await_and_log_pending(pending)

                if start_time is None:
                    # Avoid calling monotonic() until we know
                    # we may need to start logging blocked tasks.
                    start_time = 0
                elif start_time == 0:
                    # If we have waited twice then we set the start
                    # time
                    start_time = monotonic()
                elif monotonic() - start_time > BLOCK_LOG_TIMEOUT:
                    # We have waited at least three loops and new tasks
                    # continue to block. At this point we start
                    # logging all waiting tasks.
                    for task in pending:
                        _LOGGER.debug("Waiting for task: %s", task)
            else:
                await asyncio.sleep(0.001)
        await super().async_block_till_done(wait_background_tasks=wait_background_tasks)

    async def __aenter__(self) -> WebSocketGateway:
        """Enter the context manager."""
        await self.start_server()
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Exit the context manager."""
        await self.stop_server()
        await self.wait_closed()

    def _register_api_commands(self) -> None:
        """Load server API commands."""
        # pylint: disable=import-outside-toplevel
        from zha.websocket.server.client import load_api as load_client_api

        register_api_command(self, stop_server)
        load_zigbee_controller_api(self)
        load_platform_entity_apis(self)
        load_client_api(self)


class StopServerCommand(WebSocketCommand):
    """Stop the server."""

    command: Literal[APICommands.STOP_SERVER] = APICommands.STOP_SERVER


@decorators.websocket_command(StopServerCommand)
@decorators.async_response
async def stop_server(
    server: WebSocketGateway, client: Client, command: WebSocketCommand
) -> None:
    """Stop the Zigbee network."""
    client.send_result_success(command)
    await server.stop_server()
