"""Client implementation for the zhaws.client."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import pprint
from types import TracebackType
from typing import Any

from aiohttp import ClientSession, ClientWebSocketResponse, client_exceptions
from aiohttp.http_websocket import WSMsgType
from async_timeout import timeout

from zha.event import EventBase
from zha.websocket.client.model.commands import CommandResponse, ErrorResponse
from zha.websocket.client.model.messages import Message
from zha.websocket.server.api.model import WebSocketCommand

SIZE_PARSE_JSON_EXECUTOR = 8192
_LOGGER = logging.getLogger(__package__)


class Client(EventBase):
    """Class to manage the IoT connection."""

    def __init__(
        self,
        ws_server_url: str,
        aiohttp_session: ClientSession | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the Client class."""
        super().__init__(*args, **kwargs)
        self.ws_server_url = ws_server_url

        # Create a session if none is provided
        if aiohttp_session is None:
            self.aiohttp_session = ClientSession()
            self._close_aiohttp_session: bool = True
        else:
            self.aiohttp_session = aiohttp_session
            self._close_aiohttp_session = False

        # The WebSocket client
        self._client: ClientWebSocketResponse | None = None
        self._loop = asyncio.get_running_loop()
        self._result_futures: dict[int, asyncio.Future] = {}
        self._listen_task: asyncio.Task | None = None

        self._message_id = 0

    def __repr__(self) -> str:
        """Return the representation."""
        prefix = "" if self.connected else "not "
        return f"{type(self).__name__}(ws_server_url={self.ws_server_url!r}, {prefix}connected)"

    @property
    def connected(self) -> bool:
        """Return if we're currently connected."""
        return self._client is not None and not self._client.closed

    def new_message_id(self) -> int:
        """Create a new message ID.

        XXX: JSON doesn't define limits for integers but JavaScript itself internally
        uses double precision floats for numbers (including in `JSON.parse`), setting
        a hard limit of `Number.MAX_SAFE_INTEGER == 2^53 - 1`.  We can be more
        conservative and just restrict it to the maximum value of a 32-bit signed int.
        """
        self._message_id = (self._message_id + 1) % 0x80000000
        return self._message_id

    async def async_send_command(
        self,
        command: WebSocketCommand,
    ) -> CommandResponse:
        """Send a command and get a response."""
        future: asyncio.Future[CommandResponse] = self._loop.create_future()
        message_id = command.message_id = self.new_message_id()
        self._result_futures[message_id] = future

        try:
            async with timeout(20):
                await self._send_json_message(
                    command.model_dump_json(exclude_none=True)
                )
                return await future
        except TimeoutError:
            _LOGGER.exception("Timeout waiting for response")
            return CommandResponse.model_validate(
                {"message_id": message_id, "success": False}
            )
        except Exception as err:
            _LOGGER.exception("Error sending command", exc_info=err)
            return CommandResponse.model_validate(
                {"message_id": message_id, "success": False}
            )
        finally:
            self._result_futures.pop(message_id)

    async def async_send_command_no_wait(self, command: WebSocketCommand) -> None:
        """Send a command without waiting for the response."""
        command.message_id = self.new_message_id()
        await self._send_json_message(command.model_dump_json(exclude_none=True))

    async def connect(self) -> None:
        """Connect to the websocket server."""

        _LOGGER.debug("Trying to connect")
        try:
            self._client = await self.aiohttp_session.ws_connect(
                self.ws_server_url,
                heartbeat=55,
                compress=15,
                max_msg_size=0,
            )
        except client_exceptions.ClientError as err:
            _LOGGER.exception("Error connecting to server", exc_info=err)
            raise err

    async def listen_loop(self) -> None:
        """Listen to the websocket."""
        assert self._client is not None
        while not self._client.closed:
            data = await self._receive_json_or_raise()
            self._handle_incoming_message(data)

    async def listen(self) -> None:
        """Start listening to the websocket."""
        if not self.connected:
            raise Exception("Not connected when start listening")  # noqa: TRY002

        assert self._client

        assert self._listen_task is None
        self._listen_task = asyncio.create_task(self.listen_loop())

    async def disconnect(self) -> None:
        """Disconnect the client."""
        _LOGGER.debug("Closing client connection")

        if self._listen_task is not None:
            self._listen_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task

            self._listen_task = None

        assert self._client is not None
        await self._client.close()

        if self._close_aiohttp_session:
            await self.aiohttp_session.close()

        _LOGGER.debug("Listen completed. Cleaning up")

        for future in self._result_futures.values():
            future.cancel()

        self._result_futures.clear()

    async def _receive_json_or_raise(self) -> dict:
        """Receive json or raise."""
        assert self._client
        msg = await self._client.receive()

        if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING):
            raise Exception("Connection was closed.")  # noqa: TRY002

        if msg.type == WSMsgType.ERROR:
            raise Exception()  # noqa: TRY002

        if msg.type != WSMsgType.TEXT:
            raise Exception(f"Received non-Text message: {msg.type}")  # noqa: TRY002

        try:
            if len(msg.data) > SIZE_PARSE_JSON_EXECUTOR:
                data: dict = await self._loop.run_in_executor(None, msg.json)
            else:
                data = msg.json()
        except ValueError as err:
            raise Exception("Received invalid JSON.") from err  # noqa: TRY002

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("Received message:\n%s\n", pprint.pformat(msg))

        return data

    def _handle_incoming_message(self, msg: dict) -> None:
        """Handle incoming message.

        Run all async tasks in a wrapper to log appropriately.
        """

        try:
            message = Message.model_validate(msg).root
        except Exception as err:
            _LOGGER.exception("Error parsing message: %s", msg, exc_info=err)
            if msg["message_type"] == "result":
                future = self._result_futures.get(msg["message_id"])
                if future is not None:
                    future.set_exception(err)
                    return
            return

        if message.message_type == "result":
            future = self._result_futures.get(message.message_id)

            if future is None:
                # no listener for this result
                return

            if message.success or isinstance(message, ErrorResponse):
                future.set_result(message)
                return

            if msg["error_code"] != "zigbee_error":
                error = Exception(msg["message_id"], msg["error_code"])
            else:
                error = Exception(
                    msg["message_id"],
                    msg["zigbee_error_code"],
                    msg["zigbee_error_message"],
                )

            future.set_exception(error)
            return

        if message.message_type != "event":
            # Can't handle
            _LOGGER.debug(
                "Received message with unknown type '%s': %s",
                msg["message_type"],
                msg,
            )
            return

        try:
            self.emit(message.event_type, message)
        except Exception as err:
            _LOGGER.exception("Error handling event", exc_info=err)

    async def _send_json_message(self, message: str) -> None:
        """Send a message.

        Raises NotConnected if client not connected.
        """
        if not self.connected:
            raise Exception()  # noqa: TRY002

        _LOGGER.debug("Publishing message:\n%s\n", pprint.pformat(message))

        assert self._client
        assert "message_id" in message

        await self._client.send_str(message)

    async def __aenter__(self) -> Client:
        """Connect to the websocket."""
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Disconnect from the websocket."""
        await self.disconnect()
