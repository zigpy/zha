"""WS api for the number platform entity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from zha.application.discovery import Platform
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand
from zha.websocket.server.api.platforms.api import execute_platform_entity_command

if TYPE_CHECKING:
    from zha.websocket.server.client import Client
    from zha.websocket.server.gateway import WebSocketGateway as Server

ATTR_VALUE = "value"
COMMAND_SET_VALUE = "number_set_value"


class NumberSetValueCommand(PlatformEntityCommand):
    """Number set value command."""

    command: Literal[APICommands.NUMBER_SET_VALUE] = APICommands.NUMBER_SET_VALUE
    platform: str = Platform.NUMBER
    value: float


@decorators.websocket_command(NumberSetValueCommand)
@decorators.async_response
async def set_value(
    server: Server, client: Client, command: NumberSetValueCommand
) -> None:
    """Select an option."""
    await execute_platform_entity_command(server, client, command, "async_set_value")


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, set_value)
