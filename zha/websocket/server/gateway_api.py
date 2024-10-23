"""Websocket API for zhawss."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeVar, Union, cast

from pydantic import Field
from zigpy.types.named import EUI64

from zha.websocket.const import DURATION, GROUPS, APICommands
from zha.websocket.server.api import decorators, register_api_command
from zha.websocket.server.api.model import (
    GetDevicesResponse,
    ReadClusterAttributesResponse,
    WebSocketCommand,
    WriteClusterAttributeResponse,
)
from zha.zigbee.device import Device
from zha.zigbee.group import Group
from zha.zigbee.model import GroupMemberReference

if TYPE_CHECKING:
    from zha.application.gateway import WebSocketServerGateway
    from zha.websocket.server.client import Client

GROUP = "group"
MFG_CLUSTER_ID_START = 0xFC00

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


def ensure_list(value: T | None) -> list[T] | list[Any]:
    """Wrap value in list if it is not one."""
    if value is None:
        return []
    return cast("list[T]", value) if isinstance(value, list) else [value]


class StartNetworkCommand(WebSocketCommand):
    """Start the Zigbee network."""

    command: Literal[APICommands.START_NETWORK] = APICommands.START_NETWORK


@decorators.websocket_command(StartNetworkCommand)
@decorators.async_response
async def start_network(
    gateway: WebSocketServerGateway, client: Client, command: StartNetworkCommand
) -> None:
    """Start the Zigbee network."""
    await gateway.start_network()
    client.send_result_success(command)


class StopNetworkCommand(WebSocketCommand):
    """Stop the Zigbee network."""

    command: Literal[APICommands.STOP_NETWORK] = APICommands.STOP_NETWORK


@decorators.websocket_command(StopNetworkCommand)
@decorators.async_response
async def stop_network(
    gateway: WebSocketServerGateway, client: Client, command: StopNetworkCommand
) -> None:
    """Stop the Zigbee network."""
    await gateway.stop_network()
    client.send_result_success(command)


class UpdateTopologyCommand(WebSocketCommand):
    """Stop the Zigbee network."""

    command: Literal[APICommands.UPDATE_NETWORK_TOPOLOGY] = (
        APICommands.UPDATE_NETWORK_TOPOLOGY
    )


@decorators.websocket_command(UpdateTopologyCommand)
@decorators.async_response
async def update_topology(
    gateway: WebSocketServerGateway, client: Client, command: WebSocketCommand
) -> None:
    """Update the Zigbee network topology."""
    await gateway.application_controller.topology.scan()
    client.send_result_success(command)


class GetDevicesCommand(WebSocketCommand):
    """Get all Zigbee devices."""

    command: Literal[APICommands.GET_DEVICES] = APICommands.GET_DEVICES


@decorators.websocket_command(GetDevicesCommand)
@decorators.async_response
async def get_devices(
    gateway: WebSocketServerGateway, client: Client, command: GetDevicesCommand
) -> None:
    """Get Zigbee devices."""
    try:
        response = GetDevicesResponse(
            success=True,
            devices={
                ieee: device.extended_device_info
                for ieee, device in gateway.devices.items()
            },
            message_id=command.message_id,
        )
        _LOGGER.info("response: %s", response)
        client.send_result_success(command, response)
    except Exception as e:
        _LOGGER.exception("Error getting devices", exc_info=e)
        client.send_result_error(command, "Error getting devices", str(e))


class ReconfigureDeviceCommand(WebSocketCommand):
    """Reconfigure a zigbee device."""

    command: Literal[APICommands.RECONFIGURE_DEVICE] = APICommands.RECONFIGURE_DEVICE
    ieee: EUI64


@decorators.websocket_command(ReconfigureDeviceCommand)
@decorators.async_response
async def reconfigure_device(
    gateway: WebSocketServerGateway, client: Client, command: ReconfigureDeviceCommand
) -> None:
    """Reconfigure a zigbee device."""
    device = gateway.devices.get(command.ieee)
    if device:
        await device.async_configure()
    client.send_result_success(command)


class GetGroupsCommand(WebSocketCommand):
    """Get all Zigbee devices."""

    command: Literal[APICommands.GET_GROUPS] = APICommands.GET_GROUPS


@decorators.websocket_command(GetGroupsCommand)
@decorators.async_response
async def get_groups(
    gateway: WebSocketServerGateway, client: Client, command: GetGroupsCommand
) -> None:
    """Get Zigbee groups."""
    groups: dict[int, Any] = {}
    for group_id, group in gateway.groups.items():
        groups[int(group_id)] = (
            group.info_object
        )  # maybe we should change the group_id type...
    _LOGGER.info("groups: %s", groups)
    client.send_result_success(command, {GROUPS: groups})


class PermitJoiningCommand(WebSocketCommand):
    """Permit joining."""

    command: Literal[APICommands.PERMIT_JOINING] = APICommands.PERMIT_JOINING
    duration: Annotated[int, Field(ge=1, le=254)] = 60
    ieee: Union[EUI64, None] = None


@decorators.websocket_command(PermitJoiningCommand)
@decorators.async_response
async def permit_joining(
    gateway: WebSocketServerGateway, client: Client, command: PermitJoiningCommand
) -> None:
    """Permit joining devices to the Zigbee network."""
    # TODO add permit with code support
    await gateway.application_controller.permit(command.duration, command.ieee)
    client.send_result_success(
        command,
        {DURATION: command.duration},
    )


class RemoveDeviceCommand(WebSocketCommand):
    """Remove device command."""

    command: Literal[APICommands.REMOVE_DEVICE] = APICommands.REMOVE_DEVICE
    ieee: EUI64


@decorators.websocket_command(RemoveDeviceCommand)
@decorators.async_response
async def remove_device(
    gateway: WebSocketServerGateway, client: Client, command: RemoveDeviceCommand
) -> None:
    """Permit joining devices to the Zigbee network."""
    await gateway.async_remove_device(command.ieee)
    client.send_result_success(command)


class ReadClusterAttributesCommand(WebSocketCommand):
    """Read cluster attributes command."""

    command: Literal[APICommands.READ_CLUSTER_ATTRIBUTES] = (
        APICommands.READ_CLUSTER_ATTRIBUTES
    )
    ieee: EUI64
    endpoint_id: int
    cluster_id: int
    cluster_type: Literal["in", "out"]
    attributes: list[str]
    manufacturer_code: Union[int, None] = None


@decorators.websocket_command(ReadClusterAttributesCommand)
@decorators.async_response
async def read_cluster_attributes(
    gateway: WebSocketServerGateway,
    client: Client,
    command: ReadClusterAttributesCommand,
) -> None:
    """Read the specified cluster attributes."""
    device: Device = gateway.devices[command.ieee]
    if not device:
        client.send_result_error(
            command,
            "Device not found",
            f"Device with ieee: {command.ieee} not found",
        )
        return
    endpoint_id = command.endpoint_id
    cluster_id = command.cluster_id
    cluster_type = command.cluster_type
    attributes = command.attributes
    manufacturer = command.manufacturer_code
    if cluster_id >= MFG_CLUSTER_ID_START and manufacturer is None:
        manufacturer = device.manufacturer_code
    cluster = device.async_get_cluster(
        endpoint_id, cluster_id, cluster_type=cluster_type
    )
    if not cluster:
        client.send_result_error(
            command,
            "Cluster not found",
            f"Cluster: {endpoint_id}:{command.cluster_id} not found on device with ieee: {str(command.ieee)} not found",
        )
        return
    success, failure = await cluster.read_attributes(
        attributes, allow_cache=False, only_cache=False, manufacturer=manufacturer
    )

    response = ReadClusterAttributesResponse(
        message_id=command.message_id,
        success=True,
        device=device.extended_device_info,
        cluster={
            "id": cluster.cluster_id,
            "name": cluster.name,
            "type": cluster.cluster_type,
            "endpoint_id": cluster.endpoint.endpoint_id,
            "endpoint_attribute": cluster.ep_attribute,
        },
        manufacturer_code=manufacturer,
        succeeded=success,
        failed=failure,
    )
    client.send_result_success(command, response)


class WriteClusterAttributeCommand(WebSocketCommand):
    """Write cluster attribute command."""

    command: Literal[APICommands.WRITE_CLUSTER_ATTRIBUTE] = (
        APICommands.WRITE_CLUSTER_ATTRIBUTE
    )
    ieee: EUI64
    endpoint_id: int
    cluster_id: int
    cluster_type: Literal["in", "out"]
    attribute: str
    value: Union[str, int, float, bool]
    manufacturer_code: Union[int, None] = None


@decorators.websocket_command(WriteClusterAttributeCommand)
@decorators.async_response
async def write_cluster_attribute(
    gateway: WebSocketServerGateway,
    client: Client,
    command: WriteClusterAttributeCommand,
) -> None:
    """Set the value of the specific cluster attribute."""
    device: Device = gateway.devices[command.ieee]
    if not device:
        client.send_result_error(
            command,
            "Device not found",
            f"Device with ieee: {command.ieee} not found",
        )
        return
    endpoint_id = command.endpoint_id
    cluster_id = command.cluster_id
    cluster_type = command.cluster_type
    attribute = command.attribute
    value = command.value
    manufacturer = command.manufacturer_code
    if cluster_id >= MFG_CLUSTER_ID_START and manufacturer is None:
        manufacturer = device.manufacturer_code
    cluster = device.async_get_cluster(
        endpoint_id, cluster_id, cluster_type=cluster_type
    )
    if not cluster:
        client.send_result_error(
            command,
            "Cluster not found",
            f"Cluster: {endpoint_id}:{command.cluster_id} not found on device with ieee: {str(command.ieee)} not found",
        )
        return
    response = await device.write_zigbee_attribute(
        endpoint_id,
        cluster_id,
        attribute,
        value,
        cluster_type=cluster_type,
        manufacturer=manufacturer,
    )

    api_response = WriteClusterAttributeResponse(
        message_id=command.message_id,
        success=True,
        device=device.extended_device_info,
        cluster={
            "id": cluster.cluster_id,
            "name": cluster.name,
            "type": cluster.cluster_type,
            "endpoint_id": cluster.endpoint.endpoint_id,
            "endpoint_attribute": cluster.ep_attribute,
        },
        manufacturer_code=manufacturer,
        response={
            "attribute": attribute,
            "status": response[0][0].status.name,  # type: ignore
        },  # TODO there has to be a better way to do this
    )
    client.send_result_success(command, api_response)


class CreateGroupCommand(WebSocketCommand):
    """Create group command."""

    command: Literal[APICommands.CREATE_GROUP] = APICommands.CREATE_GROUP
    group_name: str
    members: list[GroupMemberReference]
    group_id: Union[int, None] = None


@decorators.websocket_command(CreateGroupCommand)
@decorators.async_response
async def create_group(
    gateway: WebSocketServerGateway, client: Client, command: CreateGroupCommand
) -> None:
    """Create a new group."""
    group_name = command.group_name
    members = command.members
    group_id = command.group_id
    group: Group = await gateway.async_create_zigpy_group(group_name, members, group_id)
    client.send_result_success(command, {"group": group.info_object})


class RemoveGroupsCommand(WebSocketCommand):
    """Remove groups command."""

    command: Literal[APICommands.REMOVE_GROUPS] = APICommands.REMOVE_GROUPS
    group_ids: list[int]


@decorators.websocket_command(RemoveGroupsCommand)
@decorators.async_response
async def remove_groups(
    gateway: WebSocketServerGateway, client: Client, command: RemoveGroupsCommand
) -> None:
    """Remove the specified groups."""
    group_ids = command.group_ids

    if len(group_ids) > 1:
        tasks = []
        for group_id in group_ids:
            tasks.append(gateway.async_remove_zigpy_group(group_id))
        await asyncio.gather(*tasks)
    else:
        await gateway.async_remove_zigpy_group(group_ids[0])
    groups: dict[int, Any] = {}
    for group_id, group in gateway.groups.items():
        groups[int(group_id)] = group.info_object
    _LOGGER.info("groups: %s", groups)
    client.send_result_success(command, {GROUPS: groups})


class AddGroupMembersCommand(WebSocketCommand):
    """Add group members command."""

    command: Literal[
        APICommands.ADD_GROUP_MEMBERS, APICommands.REMOVE_GROUP_MEMBERS
    ] = APICommands.ADD_GROUP_MEMBERS
    group_id: int
    members: list[GroupMemberReference]


@decorators.websocket_command(AddGroupMembersCommand)
@decorators.async_response
async def add_group_members(
    gateway: WebSocketServerGateway, client: Client, command: AddGroupMembersCommand
) -> None:
    """Add members to a ZHA group."""
    group_id = command.group_id
    members = command.members
    group = None

    if group_id in gateway.groups:
        group = gateway.groups[group_id]
        await group.async_add_members(members)
    if not group:
        client.send_result_error(command, "G1", "ZHA Group not found")
        return
    client.send_result_success(command, {GROUP: group.info_object})


class RemoveGroupMembersCommand(AddGroupMembersCommand):
    """Remove group members command."""

    command: Literal[APICommands.REMOVE_GROUP_MEMBERS] = (
        APICommands.REMOVE_GROUP_MEMBERS
    )


@decorators.websocket_command(RemoveGroupMembersCommand)
@decorators.async_response
async def remove_group_members(
    gateway: WebSocketServerGateway, client: Client, command: RemoveGroupMembersCommand
) -> None:
    """Remove members from a ZHA group."""
    group_id = command.group_id
    members = command.members
    group = None

    if group_id in gateway.groups:
        group = gateway.groups[group_id]
        await group.async_remove_members(members)
    if not group:
        client.send_result_error(command, "G1", "ZHA Group not found")
        return
    client.send_result_success(command, {GROUP: group.info_object})


class StopServerCommand(WebSocketCommand):
    """Stop the server."""

    command: Literal[APICommands.STOP_SERVER] = APICommands.STOP_SERVER


@decorators.websocket_command(StopServerCommand)
@decorators.async_response
async def stop_server(
    server: WebSocketServerGateway, client: Client, command: WebSocketCommand
) -> None:
    """Stop the Zigbee network."""
    client.send_result_success(command)
    await server.stop_server()


def load_api(gateway: WebSocketServerGateway) -> None:
    """Load the api command handlers."""
    register_api_command(gateway, start_network)
    register_api_command(gateway, stop_network)
    register_api_command(gateway, get_devices)
    register_api_command(gateway, reconfigure_device)
    register_api_command(gateway, get_groups)
    register_api_command(gateway, create_group)
    register_api_command(gateway, remove_groups)
    register_api_command(gateway, add_group_members)
    register_api_command(gateway, remove_group_members)
    register_api_command(gateway, permit_joining)
    register_api_command(gateway, remove_device)
    register_api_command(gateway, update_topology)
    register_api_command(gateway, read_cluster_attributes)
    register_api_command(gateway, write_cluster_attribute)
    register_api_command(gateway, stop_server)
