"""WS api for the select platform entity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from zha.application.discovery import Platform
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand
from zha.websocket.server.api.platforms.api import execute_platform_entity_command

if TYPE_CHECKING:
    from zha.application.gateway import WebSocketGateway as Server
    from zha.websocket.server.client import Client


class SelectSelectOptionCommand(PlatformEntityCommand):
    """Select select option command."""

    command: Literal[APICommands.SELECT_SELECT_OPTION] = (
        APICommands.SELECT_SELECT_OPTION
    )
    platform: str = Platform.SELECT
    option: str


@decorators.websocket_command(SelectSelectOptionCommand)
@decorators.async_response
async def select_option(
    server: Server, client: Client, command: SelectSelectOptionCommand
) -> None:
    """Select an option."""
    await execute_platform_entity_command(
        server, client, command, "async_select_option"
    )


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, select_option)
