"""WS api for the switch platform entity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from zha.application.discovery import Platform
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand
from zha.websocket.server.api.platforms.api import execute_platform_entity_command

if TYPE_CHECKING:
    from zha.application.gateway import WebSocketServerGateway as Server
    from zha.websocket.server.client import Client


class SwitchTurnOnCommand(PlatformEntityCommand):
    """Switch turn on command."""

    command: Literal[APICommands.SWITCH_TURN_ON] = APICommands.SWITCH_TURN_ON
    platform: str = Platform.SWITCH


@decorators.websocket_command(SwitchTurnOnCommand)
@decorators.async_response
async def turn_on(server: Server, client: Client, command: SwitchTurnOnCommand) -> None:
    """Turn on the switch."""
    await execute_platform_entity_command(server, client, command, "async_turn_on")


class SwitchTurnOffCommand(PlatformEntityCommand):
    """Switch turn off command."""

    command: Literal[APICommands.SWITCH_TURN_OFF] = APICommands.SWITCH_TURN_OFF
    platform: str = Platform.SWITCH


@decorators.websocket_command(SwitchTurnOffCommand)
@decorators.async_response
async def turn_off(
    server: Server, client: Client, command: SwitchTurnOffCommand
) -> None:
    """Turn on the switch."""
    await execute_platform_entity_command(server, client, command, "async_turn_off")


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, turn_on)
    register_api_command(server, turn_off)
