"""WS API for common platform entity functionality."""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Literal

from zha.websocket.const import ATTR_UNIQUE_ID, IEEE, APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.platforms import PlatformEntityCommand

if TYPE_CHECKING:
    from zha.websocket.server.client import Client
    from zha.websocket.server.gateway import WebSocketGateway as Server

_LOGGER = logging.getLogger(__name__)


async def execute_platform_entity_command(
    server: Server,
    client: Client,
    command: PlatformEntityCommand,
    method_name: str,
) -> None:
    """Get the platform entity and execute a method based on the command."""
    try:
        if command.ieee:
            _LOGGER.debug("command: %s", command)
            device = server.get_device(command.ieee)
            platform_entity: Any = device.get_platform_entity(
                command.platform, command.unique_id
            )
        else:
            assert command.group_id
            group = server.get_group(command.group_id)
            platform_entity = group.group_entities[command.unique_id]
    except ValueError as err:
        _LOGGER.exception(
            "Error executing command: %s method_name: %s",
            command,
            method_name,
            exc_info=err,
        )
        client.send_result_error(command, "PLATFORM_ENTITY_COMMAND_ERROR", str(err))
        return None

    try:
        action = getattr(platform_entity, method_name)
        arg_spec = inspect.getfullargspec(action)
        if arg_spec.varkw:
            await action(**command.model_dump(exclude_none=True))
        else:
            await action()  # the only argument is self

    except Exception as err:
        _LOGGER.exception("Error executing command: %s", method_name, exc_info=err)
        client.send_result_error(command, "PLATFORM_ENTITY_ACTION_ERROR", str(err))
        return

    result: dict[str, Any] = {}
    if command.ieee:
        result[IEEE] = str(command.ieee)
    else:
        result["group_id"] = command.group_id
    result[ATTR_UNIQUE_ID] = command.unique_id
    client.send_result_success(command, result)


class PlatformEntityRefreshStateCommand(PlatformEntityCommand):
    """Platform entity refresh state command."""

    command: Literal[APICommands.PLATFORM_ENTITY_REFRESH_STATE] = (
        APICommands.PLATFORM_ENTITY_REFRESH_STATE
    )


@decorators.websocket_command(PlatformEntityRefreshStateCommand)
@decorators.async_response
async def refresh_state(
    server: Server, client: Client, command: PlatformEntityCommand
) -> None:
    """Refresh the state of the platform entity."""
    await execute_platform_entity_command(server, client, command, "async_update")


# pylint: disable=import-outside-toplevel
def load_platform_entity_apis(server: Server) -> None:
    """Load the ws apis for all platform entities types."""
    from zha.websocket.server.api.platforms.alarm_control_panel.api import (
        load_api as load_alarm_control_panel_api,
    )
    from zha.websocket.server.api.platforms.button.api import (
        load_api as load_button_api,
    )
    from zha.websocket.server.api.platforms.climate.api import (
        load_api as load_climate_api,
    )
    from zha.websocket.server.api.platforms.cover.api import load_api as load_cover_api
    from zha.websocket.server.api.platforms.fan.api import load_api as load_fan_api
    from zha.websocket.server.api.platforms.light.api import load_api as load_light_api
    from zha.websocket.server.api.platforms.lock.api import load_api as load_lock_api
    from zha.websocket.server.api.platforms.number.api import (
        load_api as load_number_api,
    )
    from zha.websocket.server.api.platforms.select.api import (
        load_api as load_select_api,
    )
    from zha.websocket.server.api.platforms.siren.api import load_api as load_siren_api
    from zha.websocket.server.api.platforms.switch.api import (
        load_api as load_switch_api,
    )

    register_api_command(server, refresh_state)
    load_alarm_control_panel_api(server)
    load_button_api(server)
    load_climate_api(server)
    load_cover_api(server)
    load_fan_api(server)
    load_light_api(server)
    load_lock_api(server)
    load_number_api(server)
    load_select_api(server)
    load_siren_api(server)
    load_switch_api(server)
