"""WS API for the cover platform entity."""

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


class CoverOpenCommand(PlatformEntityCommand):
    """Cover open command."""

    command: Literal[APICommands.COVER_OPEN] = APICommands.COVER_OPEN
    platform: str = Platform.COVER


@decorators.websocket_command(CoverOpenCommand)
@decorators.async_response
async def open_cover(server: Server, client: Client, command: CoverOpenCommand) -> None:
    """Open the cover."""
    await execute_platform_entity_command(server, client, command, "async_open_cover")


class CoverCloseCommand(PlatformEntityCommand):
    """Cover close command."""

    command: Literal[APICommands.COVER_CLOSE] = APICommands.COVER_CLOSE
    platform: str = Platform.COVER


@decorators.websocket_command(CoverCloseCommand)
@decorators.async_response
async def close_cover(
    server: Server, client: Client, command: CoverCloseCommand
) -> None:
    """Close the cover."""
    await execute_platform_entity_command(server, client, command, "async_close_cover")


class CoverSetPositionCommand(PlatformEntityCommand):
    """Cover set position command."""

    command: Literal[APICommands.COVER_SET_POSITION] = APICommands.COVER_SET_POSITION
    platform: str = Platform.COVER
    position: int


@decorators.websocket_command(CoverSetPositionCommand)
@decorators.async_response
async def set_position(
    server: Server, client: Client, command: CoverSetPositionCommand
) -> None:
    """Set the cover position."""
    await execute_platform_entity_command(
        server, client, command, "async_set_cover_position"
    )


class CoverStopCommand(PlatformEntityCommand):
    """Cover stop command."""

    command: Literal[APICommands.COVER_STOP] = APICommands.COVER_STOP
    platform: str = Platform.COVER


@decorators.websocket_command(CoverStopCommand)
@decorators.async_response
async def stop_cover(server: Server, client: Client, command: CoverStopCommand) -> None:
    """Stop the cover."""
    await execute_platform_entity_command(server, client, command, "async_stop_cover")


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, open_cover)
    register_api_command(server, close_cover)
    register_api_command(server, set_position)
    register_api_command(server, stop_cover)
