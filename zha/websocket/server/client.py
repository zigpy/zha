"""Client classes for zhawss."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError
from websockets.server import WebSocketServerProtocol

from zha.websocket.const import (
    COMMAND,
    ERROR_CODE,
    ERROR_MESSAGE,
    EVENT_TYPE,
    MESSAGE_ID,
    MESSAGE_TYPE,
    SUCCESS,
    WEBSOCKET_API,
    ZIGBEE_ERROR_CODE,
    APICommands,
    EventTypes,
    MessageTypes,
)
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.model import WebSocketCommand

if TYPE_CHECKING:
    from zha.websocket.server.gateway import WebSocketGateway

_LOGGER = logging.getLogger(__name__)


class Client:
    """ZHAWSS client implementation."""

    def __init__(
        self,
        websocket: WebSocketServerProtocol,
        client_manager: ClientManager,
    ):
        """Initialize the client."""
        self._websocket: WebSocketServerProtocol = websocket
        self._client_manager: ClientManager = client_manager
        self.receive_events: bool = False
        self.receive_raw_zcl_events: bool = False

    @property
    def is_connected(self) -> bool:
        """Return True if the websocket connection is connected."""
        return self._websocket.open

    def disconnect(self) -> None:
        """Disconnect this client and close the websocket."""
        self._client_manager.server.track_ws_task(
            asyncio.create_task(self._websocket.close())
        )

    def send_event(self, message: dict[str, Any]) -> None:
        """Send event data to this client."""
        message[MESSAGE_TYPE] = MessageTypes.EVENT
        self._send_data(message)

    def send_result_success(
        self, command: WebSocketCommand, data: dict[str, Any] | None = None
    ) -> None:
        """Send success result prompted by a client request."""
        message = {
            SUCCESS: True,
            MESSAGE_ID: command.message_id,
            MESSAGE_TYPE: MessageTypes.RESULT,
            COMMAND: command.command,
        }
        if data:
            message.update(data)
        self._send_data(message)

    def send_result_error(
        self,
        command: WebSocketCommand,
        error_code: str,
        error_message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Send error result prompted by a client request."""
        message = {
            SUCCESS: False,
            MESSAGE_ID: command.message_id,
            MESSAGE_TYPE: MessageTypes.RESULT,
            COMMAND: f"error.{command.command}",
            ERROR_CODE: error_code,
            ERROR_MESSAGE: error_message,
        }
        if data:
            message.update(data)
        self._send_data(message)

    def send_result_zigbee_error(
        self,
        command: WebSocketCommand,
        error_message: str,
        zigbee_error_code: str,
    ) -> None:
        """Send zigbee error result prompted by a client zigbee request."""
        self.send_result_error(
            command,
            error_code="zigbee_error",
            error_message=error_message,
            data={ZIGBEE_ERROR_CODE: zigbee_error_code},
        )

    def _send_data(self, message: dict[str, Any] | BaseModel) -> None:
        """Send data to this client."""
        try:
            if isinstance(message, BaseModel):
                message_json = message.model_dump_json()
            else:
                message_json = json.dumps(message)
        except ValueError as exc:
            _LOGGER.exception("Couldn't serialize data: %s", message, exc_info=exc)
            raise exc
        else:
            self._client_manager.server.track_ws_task(
                asyncio.create_task(self._websocket.send(message_json))
            )

    async def _handle_incoming_message(self, message: str | bytes) -> None:
        """Handle an incoming message."""
        _LOGGER.info("Message received: %s", message)
        handlers: dict[str, tuple[Callable, WebSocketCommand]] = (
            self._client_manager.server.data[WEBSOCKET_API]
        )

        try:
            msg = WebSocketCommand.model_validate_json(message)
        except ValidationError as exception:
            _LOGGER.exception(
                "Received invalid command[unable to parse command]: %s on websocket: %s",
                message,
                self._websocket.id,
                exc_info=exception,
            )
            return

        if msg.command not in handlers:
            _LOGGER.error(
                "Received invalid command[command not registered]: %s", message
            )
            return

        handler, model = handlers[msg.command]

        try:
            handler(
                self._client_manager.server, self, model.model_validate_json(message)
            )
        except Exception as err:  # pylint: disable=broad-except
            # TODO Fix this - make real error codes with error messages
            _LOGGER.exception("Error handling message: %s", message, exc_info=err)
            self.send_result_error(message, "INTERNAL_ERROR", f"Internal error: {err}")

    async def listen(self) -> None:
        """Listen for incoming messages."""
        async for message in self._websocket:
            self._client_manager.server.track_ws_task(
                asyncio.create_task(self._handle_incoming_message(message))
            )

    def will_accept_message(self, message: dict[str, Any]) -> bool:
        """Determine if client accepts this type of message."""
        if not self.receive_events:
            return False

        if (
            message[EVENT_TYPE] == EventTypes.RAW_ZCL_EVENT
            and not self.receive_raw_zcl_events
        ):
            _LOGGER.info(
                "Client %s not accepting raw ZCL events: %s",
                self._websocket.id,
                message,
            )
            return False

        return True


class ClientListenRawZCLCommand(WebSocketCommand):
    """Listen to raw ZCL data."""

    command: Literal[APICommands.CLIENT_LISTEN_RAW_ZCL] = (
        APICommands.CLIENT_LISTEN_RAW_ZCL
    )


class ClientListenCommand(WebSocketCommand):
    """Listen for zhawss messages."""

    command: Literal[APICommands.CLIENT_LISTEN] = APICommands.CLIENT_LISTEN


class ClientDisconnectCommand(WebSocketCommand):
    """Disconnect this client."""

    command: Literal[APICommands.CLIENT_DISCONNECT] = APICommands.CLIENT_DISCONNECT


@decorators.websocket_command(ClientListenRawZCLCommand)
@decorators.async_response
async def listen_raw_zcl(
    server: WebSocketGateway, client: Client, command: WebSocketCommand
) -> None:
    """Listen for raw ZCL events."""
    client.receive_raw_zcl_events = True
    client.send_result_success(command)


@decorators.websocket_command(ClientListenCommand)
@decorators.async_response
async def listen(
    server: WebSocketGateway, client: Client, command: WebSocketCommand
) -> None:
    """Listen for events."""
    client.receive_events = True
    client.send_result_success(command)


@decorators.websocket_command(ClientDisconnectCommand)
@decorators.async_response
async def disconnect(
    server: WebSocketGateway, client: Client, command: WebSocketCommand
) -> None:
    """Disconnect the client."""
    client.disconnect()
    server.client_manager.remove_client(client)


def load_api(server: WebSocketGateway) -> None:
    """Load the api command handlers."""
    register_api_command(server, listen_raw_zcl)
    register_api_command(server, listen)
    register_api_command(server, disconnect)


class ClientManager:
    """ZHAWSS client manager implementation."""

    def __init__(self, server: WebSocketGateway):
        """Initialize the client."""
        self._server: WebSocketGateway = server
        self._clients: list[Client] = []

    @property
    def server(self) -> WebSocketGateway:
        """Return the server this ClientManager belongs to."""
        return self._server

    async def add_client(self, websocket: WebSocketServerProtocol) -> None:
        """Add a new client to the client manager."""
        client: Client = Client(websocket, self)
        self._clients.append(client)
        await client.listen()

    def remove_client(self, client: Client) -> None:
        """Remove a client from the client manager."""
        client.disconnect()
        self._clients.remove(client)

    def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        clients_to_remove = []

        for client in self._clients:
            if not client.is_connected:
                # XXX: We cannot remove elements from `_clients` while iterating over it
                clients_to_remove.append(client)
                continue

            if not client.will_accept_message(message):
                continue

            _LOGGER.info(
                "Broadcasting message: %s to client: %s",
                message,
                client._websocket.id,
            )
            # TODO use the receive flags on the client to determine if the client should receive the message
            client.send_event(message)

        for client in clients_to_remove:
            self.remove_client(client)
