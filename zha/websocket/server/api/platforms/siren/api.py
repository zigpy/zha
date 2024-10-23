"""WS api for the siren platform entity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Union

from zha.application.discovery import Platform
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand
from zha.websocket.server.api.platforms.api import execute_platform_entity_command

if TYPE_CHECKING:
    from zha.application.gateway import WebSocketServerGateway as Server
    from zha.websocket.server.client import Client


class SirenTurnOnCommand(PlatformEntityCommand):
    """Siren turn on command."""

    command: Literal[APICommands.SIREN_TURN_ON] = APICommands.SIREN_TURN_ON
    platform: str = Platform.SIREN
    duration: Union[int, None] = None
    tone: Union[int, None] = None
    level: Union[int, None] = None


@decorators.websocket_command(SirenTurnOnCommand)
@decorators.async_response
async def turn_on(server: Server, client: Client, command: SirenTurnOnCommand) -> None:
    """Turn on the siren."""
    await execute_platform_entity_command(server, client, command, "async_turn_on")


class SirenTurnOffCommand(PlatformEntityCommand):
    """Siren turn off command."""

    command: Literal[APICommands.SIREN_TURN_OFF] = APICommands.SIREN_TURN_OFF
    platform: str = Platform.SIREN


@decorators.websocket_command(SirenTurnOffCommand)
@decorators.async_response
async def turn_off(
    server: Server, client: Client, command: SirenTurnOffCommand
) -> None:
    """Turn on the siren."""
    await execute_platform_entity_command(server, client, command, "async_turn_off")


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, turn_on)
    register_api_command(server, turn_off)
