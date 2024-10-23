"""WS api for the alarm control panel platform entity."""

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


class DisarmCommand(PlatformEntityCommand):
    """Disarm command."""

    command: Literal[APICommands.ALARM_CONTROL_PANEL_DISARM] = (
        APICommands.ALARM_CONTROL_PANEL_DISARM
    )
    platform: str = Platform.ALARM_CONTROL_PANEL
    code: Union[str, None]


@decorators.websocket_command(DisarmCommand)
@decorators.async_response
async def disarm(server: Server, client: Client, command: DisarmCommand) -> None:
    """Disarm the alarm control panel."""
    await execute_platform_entity_command(server, client, command, "async_alarm_disarm")


class ArmHomeCommand(PlatformEntityCommand):
    """Arm home command."""

    command: Literal[APICommands.ALARM_CONTROL_PANEL_ARM_HOME] = (
        APICommands.ALARM_CONTROL_PANEL_ARM_HOME
    )
    platform: str = Platform.ALARM_CONTROL_PANEL
    code: Union[str, None]


@decorators.websocket_command(ArmHomeCommand)
@decorators.async_response
async def arm_home(server: Server, client: Client, command: ArmHomeCommand) -> None:
    """Arm the alarm control panel in home mode."""
    await execute_platform_entity_command(
        server, client, command, "async_alarm_arm_home"
    )


class ArmAwayCommand(PlatformEntityCommand):
    """Arm away command."""

    command: Literal[APICommands.ALARM_CONTROL_PANEL_ARM_AWAY] = (
        APICommands.ALARM_CONTROL_PANEL_ARM_AWAY
    )
    platform: str = Platform.ALARM_CONTROL_PANEL
    code: Union[str, None]


@decorators.websocket_command(ArmAwayCommand)
@decorators.async_response
async def arm_away(server: Server, client: Client, command: ArmAwayCommand) -> None:
    """Arm the alarm control panel in away mode."""
    await execute_platform_entity_command(
        server, client, command, "async_alarm_arm_away"
    )


class ArmNightCommand(PlatformEntityCommand):
    """Arm night command."""

    command: Literal[APICommands.ALARM_CONTROL_PANEL_ARM_NIGHT] = (
        APICommands.ALARM_CONTROL_PANEL_ARM_NIGHT
    )
    platform: str = Platform.ALARM_CONTROL_PANEL
    code: Union[str, None]


@decorators.websocket_command(ArmNightCommand)
@decorators.async_response
async def arm_night(server: Server, client: Client, command: ArmNightCommand) -> None:
    """Arm the alarm control panel in night mode."""
    await execute_platform_entity_command(
        server, client, command, "async_alarm_arm_night"
    )


class TriggerAlarmCommand(PlatformEntityCommand):
    """Trigger alarm command."""

    command: Literal[APICommands.ALARM_CONTROL_PANEL_TRIGGER] = (
        APICommands.ALARM_CONTROL_PANEL_TRIGGER
    )
    platform: str = Platform.ALARM_CONTROL_PANEL
    code: Union[str, None] = None


@decorators.websocket_command(TriggerAlarmCommand)
@decorators.async_response
async def trigger(server: Server, client: Client, command: TriggerAlarmCommand) -> None:
    """Trigger the alarm control panel."""
    await execute_platform_entity_command(
        server, client, command, "async_alarm_trigger"
    )


def load_api(server: Server) -> None:
    """Load the api command handlers."""
    register_api_command(server, disarm)
    register_api_command(server, arm_home)
    register_api_command(server, arm_away)
    register_api_command(server, arm_night)
    register_api_command(server, trigger)
