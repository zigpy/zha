"""WS API for the light platform entity."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Literal, Union

from pydantic import Field, ValidationInfo, field_validator

from zha.application.discovery import Platform
from zha.websocket.const import APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand
from zha.websocket.server.api.platforms.api import execute_platform_entity_command

if TYPE_CHECKING:
    from zha.websocket.server.client import Client
    from zha.websocket.server.gateway import WebSocketGateway as Server

_LOGGER = logging.getLogger(__name__)


class LightTurnOnCommand(PlatformEntityCommand):
    """Light turn on command."""

    command: Literal[APICommands.LIGHT_TURN_ON] = APICommands.LIGHT_TURN_ON
    platform: str = Platform.LIGHT
    brightness: Union[Annotated[int, Field(ge=0, le=255)], None]
    transition: Union[Annotated[float, Field(ge=0, le=6553)], None]
    flash: Union[Literal["short", "long"], None]
    effect: Union[str, None]
    hs_color: Union[
        None,
        (
            tuple[
                Annotated[int, Field(ge=0, le=360)], Annotated[int, Field(ge=0, le=100)]
            ]
        ),
    ]
    color_temp: Union[int, None]

    @field_validator("color_temp", mode="before", check_fields=False)
    @classmethod
    def check_color_setting_exclusivity(
        cls, color_temp: int | None, validation_info: ValidationInfo
    ) -> int | None:
        """Ensure only one color mode is set."""
        if (
            "hs_color" in validation_info.data
            and validation_info.data["hs_color"] is not None
            and color_temp is not None
        ):
            raise ValueError('Only one of "hs_color" and "color_temp" can be set')
        return color_temp


@decorators.websocket_command(LightTurnOnCommand)
@decorators.async_response
async def turn_on(server: Server, client: Client, command: LightTurnOnCommand) -> None:
    """Turn on the light."""
    await execute_platform_entity_command(server, client, command, "async_turn_on")


class LightTurnOffCommand(PlatformEntityCommand):
    """Light turn off command."""

    command: Literal[APICommands.LIGHT_TURN_OFF] = APICommands.LIGHT_TURN_OFF
    platform: str = Platform.LIGHT
    transition: Union[Annotated[float, Field(ge=0, le=6553)], None]
    flash: Union[Literal["short", "long"], None]


@decorators.websocket_command(LightTurnOffCommand)
@decorators.async_response
async def turn_off(
    server: Server, client: Client, command: LightTurnOffCommand
) -> None:
    """Turn on the light."""
    await execute_platform_entity_command(server, client, command, "async_turn_off")


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, turn_on)
    register_api_command(server, turn_off)
