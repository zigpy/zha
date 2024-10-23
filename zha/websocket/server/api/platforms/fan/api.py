"""WS API for the fan platform entity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal, Union

from pydantic import Field

from zha.application.discovery import Platform
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand
from zha.websocket.server.api.platforms.api import execute_platform_entity_command

if TYPE_CHECKING:
    from zha.application.gateway import WebSocketServerGateway as Server
    from zha.websocket.server.client import Client


class FanTurnOnCommand(PlatformEntityCommand):
    """Fan turn on command."""

    command: Literal[APICommands.FAN_TURN_ON] = APICommands.FAN_TURN_ON
    platform: str = Platform.FAN
    speed: Union[str, None]
    percentage: Union[Annotated[int, Field(ge=0, le=100)], None]
    preset_mode: Union[str, None]


@decorators.websocket_command(FanTurnOnCommand)
@decorators.async_response
async def turn_on(server: Server, client: Client, command: FanTurnOnCommand) -> None:
    """Turn fan on."""
    await execute_platform_entity_command(server, client, command, "async_turn_on")


class FanTurnOffCommand(PlatformEntityCommand):
    """Fan turn off command."""

    command: Literal[APICommands.FAN_TURN_OFF] = APICommands.FAN_TURN_OFF
    platform: str = Platform.FAN


@decorators.websocket_command(FanTurnOffCommand)
@decorators.async_response
async def turn_off(server: Server, client: Client, command: FanTurnOffCommand) -> None:
    """Turn fan off."""
    await execute_platform_entity_command(server, client, command, "async_turn_off")


class FanSetPercentageCommand(PlatformEntityCommand):
    """Fan set percentage command."""

    command: Literal[APICommands.FAN_SET_PERCENTAGE] = APICommands.FAN_SET_PERCENTAGE
    platform: str = Platform.FAN
    percentage: Annotated[int, Field(ge=0, le=100)]


@decorators.websocket_command(FanSetPercentageCommand)
@decorators.async_response
async def set_percentage(
    server: Server, client: Client, command: FanSetPercentageCommand
) -> None:
    """Set the fan speed percentage."""
    await execute_platform_entity_command(
        server, client, command, "async_set_percentage"
    )


class FanSetPresetModeCommand(PlatformEntityCommand):
    """Fan set preset mode command."""

    command: Literal[APICommands.FAN_SET_PRESET_MODE] = APICommands.FAN_SET_PRESET_MODE
    platform: str = Platform.FAN
    preset_mode: str


@decorators.websocket_command(FanSetPresetModeCommand)
@decorators.async_response
async def set_preset_mode(
    server: Server, client: Client, command: FanSetPresetModeCommand
) -> None:
    """Set the fan preset mode."""
    await execute_platform_entity_command(
        server, client, command, "async_set_preset_mode"
    )


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, turn_on)
    register_api_command(server, turn_off)
    register_api_command(server, set_percentage)
    register_api_command(server, set_preset_mode)
