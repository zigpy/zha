"""WS API for the button platform entity."""

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


class ButtonPressCommand(PlatformEntityCommand):
    """Button press command."""

    command: Literal[APICommands.BUTTON_PRESS] = APICommands.BUTTON_PRESS
    platform: str = Platform.BUTTON


@decorators.websocket_command(ButtonPressCommand)
@decorators.async_response
async def press(server: Server, client: Client, command: PlatformEntityCommand) -> None:
    """Turn on the button."""
    await execute_platform_entity_command(server, client, command, "async_press")


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, press)
