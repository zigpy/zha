"""Helper classes for zhaws.client."""

from __future__ import annotations

from typing import Any, cast

from zigpy.types.named import EUI64

from zha.application.discovery import Platform
from zha.websocket.client.client import Client
from zha.websocket.client.model.commands import (
    CommandResponse,
    GetDevicesResponse,
    GroupsResponse,
    PermitJoiningResponse,
    ReadClusterAttributesResponse,
    UpdateGroupResponse,
    WriteClusterAttributeResponse,
)
from zha.websocket.client.model.types import (
    BaseEntity,
    BasePlatformEntity,
    Device,
    Group,
)
from zha.websocket.server.client import (
    ClientDisconnectCommand,
    ClientListenCommand,
    ClientListenRawZCLCommand,
)
from zha.websocket.server.gateway import StopServerCommand
from zha.websocket.server.gateway_api import (
    AddGroupMembersCommand,
    CreateGroupCommand,
    GetDevicesCommand,
    GetGroupsCommand,
    PermitJoiningCommand,
    ReadClusterAttributesCommand,
    ReconfigureDeviceCommand,
    RemoveDeviceCommand,
    RemoveGroupMembersCommand,
    RemoveGroupsCommand,
    StartNetworkCommand,
    StopNetworkCommand,
    UpdateTopologyCommand,
    WriteClusterAttributeCommand,
)


def ensure_platform_entity(entity: BaseEntity, platform: Platform) -> None:
    """Ensure an entity exists and is from the specified platform."""
    if entity is None or entity.platform != platform:
        raise ValueError(
            f"entity must be provided and it must be a {platform} platform entity"
        )


class ClientHelper:
    """Helper to send client specific commands."""

    def __init__(self, client: Client):
        """Initialize the client helper."""
        self._client: Client = client

    async def listen(self) -> CommandResponse:
        """Listen for incoming messages."""
        command = ClientListenCommand()
        return await self._client.async_send_command(command)

    async def listen_raw_zcl(self) -> CommandResponse:
        """Listen for incoming raw ZCL messages."""
        command = ClientListenRawZCLCommand()
        return await self._client.async_send_command(command)

    async def disconnect(self) -> CommandResponse:
        """Disconnect this client from the server."""
        command = ClientDisconnectCommand()
        return await self._client.async_send_command(command)


class GroupHelper:
    """Helper to send group commands."""

    def __init__(self, client: Client):
        """Initialize the group helper."""
        self._client: Client = client

    async def get_groups(self) -> dict[int, Group]:
        """Get the groups."""
        response = cast(
            GroupsResponse,
            await self._client.async_send_command(GetGroupsCommand()),
        )
        return response.groups

    async def create_group(
        self,
        name: str,
        unique_id: int | None = None,
        members: list[BasePlatformEntity] | None = None,
    ) -> Group:
        """Create a new group."""
        request_data: dict[str, Any] = {
            "group_name": name,
            "group_id": unique_id,
        }
        if members is not None:
            request_data["members"] = [
                {"ieee": member.device_ieee, "endpoint_id": member.endpoint_id}
                for member in members
            ]

        command = CreateGroupCommand(**request_data)
        response = cast(
            UpdateGroupResponse,
            await self._client.async_send_command(command),
        )
        return response.group

    async def remove_groups(self, groups: list[Group]) -> dict[int, Group]:
        """Remove groups."""
        request: dict[str, Any] = {
            "group_ids": [group.id for group in groups],
        }
        command = RemoveGroupsCommand(**request)
        response = cast(
            GroupsResponse,
            await self._client.async_send_command(command),
        )
        return response.groups

    async def add_group_members(
        self, group: Group, members: list[BasePlatformEntity]
    ) -> Group:
        """Add members to a group."""
        request_data: dict[str, Any] = {
            "group_id": group.id,
            "members": [
                {"ieee": member.device_ieee, "endpoint_id": member.endpoint_id}
                for member in members
            ],
        }

        command = AddGroupMembersCommand(**request_data)
        response = cast(
            UpdateGroupResponse,
            await self._client.async_send_command(command),
        )
        return response.group

    async def remove_group_members(
        self, group: Group, members: list[BasePlatformEntity]
    ) -> Group:
        """Remove members from a group."""
        request_data: dict[str, Any] = {
            "group_id": group.id,
            "members": [
                {"ieee": member.device_ieee, "endpoint_id": member.endpoint_id}
                for member in members
            ],
        }

        command = RemoveGroupMembersCommand(**request_data)
        response = cast(
            UpdateGroupResponse,
            await self._client.async_send_command(command),
        )
        return response.group


class DeviceHelper:
    """Helper to send device commands."""

    def __init__(self, client: Client):
        """Initialize the device helper."""
        self._client: Client = client

    async def get_devices(self) -> dict[EUI64, Device]:
        """Get the groups."""
        response = cast(
            GetDevicesResponse,
            await self._client.async_send_command(GetDevicesCommand()),
        )
        return response.devices

    async def reconfigure_device(self, device: Device) -> None:
        """Reconfigure a device."""
        await self._client.async_send_command(
            ReconfigureDeviceCommand(ieee=device.ieee)
        )

    async def remove_device(self, device: Device) -> None:
        """Remove a device."""
        await self._client.async_send_command(RemoveDeviceCommand(ieee=device.ieee))

    async def read_cluster_attributes(
        self,
        device: Device,
        cluster_id: int,
        cluster_type: str,
        endpoint_id: int,
        attributes: list[str],
        manufacturer_code: int | None = None,
    ) -> ReadClusterAttributesResponse:
        """Read cluster attributes."""
        response = cast(
            ReadClusterAttributesResponse,
            await self._client.async_send_command(
                ReadClusterAttributesCommand(
                    ieee=device.ieee,
                    endpoint_id=endpoint_id,
                    cluster_id=cluster_id,
                    cluster_type=cluster_type,
                    attributes=attributes,
                    manufacturer_code=manufacturer_code,
                )
            ),
        )
        return response

    async def write_cluster_attribute(
        self,
        device: Device,
        cluster_id: int,
        cluster_type: str,
        endpoint_id: int,
        attribute: str,
        value: Any,
        manufacturer_code: int | None = None,
    ) -> WriteClusterAttributeResponse:
        """Set the value for a cluster attribute."""
        response = cast(
            WriteClusterAttributeResponse,
            await self._client.async_send_command(
                WriteClusterAttributeCommand(
                    ieee=device.ieee,
                    endpoint_id=endpoint_id,
                    cluster_id=cluster_id,
                    cluster_type=cluster_type,
                    attribute=attribute,
                    value=value,
                    manufacturer_code=manufacturer_code,
                )
            ),
        )
        return response


class NetworkHelper:
    """Helper for network commands."""

    def __init__(self, client: Client):
        """Initialize the device helper."""
        self._client: Client = client

    async def permit_joining(
        self, duration: int = 255, device: Device | None = None
    ) -> bool:
        """Permit joining for a specified duration."""
        # TODO add permit with code support
        request_data: dict[str, Any] = {
            "duration": duration,
        }
        if device is not None:
            if device.device_type == "EndDevice":
                raise ValueError("Device is not a coordinator or router")
            request_data["ieee"] = device.ieee
        command = PermitJoiningCommand(**request_data)
        response = cast(
            PermitJoiningResponse,
            await self._client.async_send_command(command),
        )
        return response.success

    async def update_topology(self) -> None:
        """Update the network topology."""
        await self._client.async_send_command(UpdateTopologyCommand())

    async def start_network(self) -> bool:
        """Start the Zigbee network."""
        command = StartNetworkCommand()
        response = await self._client.async_send_command(command)
        return response.success

    async def stop_network(self) -> bool:
        """Stop the Zigbee network."""
        response = await self._client.async_send_command(StopNetworkCommand())
        return response.success


class ServerHelper:
    """Helper for server commands."""

    def __init__(self, client: Client):
        """Initialize the helper."""
        self._client: Client = client

    async def stop_server(self) -> bool:
        """Stop the websocket server."""
        response = await self._client.async_send_command(StopServerCommand())
        return response.success
