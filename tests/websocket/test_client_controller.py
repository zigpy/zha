"""Test zha switch."""

import logging
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.types.named import EUI64
from zigpy.zcl.clusters import general

from zha.application.discovery import Platform
from zha.application.gateway import (
    DeviceJoinedDeviceInfo,
    DevicePairingStatus,
    RawDeviceInitializedDeviceInfo,
    RawDeviceInitializedEvent,
    WebSocketGateway as Server,
)
from zha.application.model import DeviceJoinedEvent, DeviceLeftEvent
from zha.application.platforms.model import (
    BasePlatformEntity,
    SwitchEntity,
    SwitchGroupEntity,
)
from zha.websocket.client.controller import Controller
from zha.websocket.client.proxy import DeviceProxy, GroupProxy
from zha.websocket.const import ControllerEvents
from zha.websocket.server.api.model import (
    ReadClusterAttributesResponse,
    WriteClusterAttributeResponse,
)
from zha.zigbee.device import Device
from zha.zigbee.group import Group, GroupMemberReference
from zha.zigbee.model import GroupInfo

from ..common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    async_find_group_entity_id,
    create_mock_zigpy_device,
    find_entity_id,
    join_zigpy_device,
    update_attribute_cache,
)

ON = 1
OFF = 0
IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"
_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def zigpy_device(connected_client_and_server: tuple[Controller, Server]) -> ZigpyDevice:
    """Device tracker zigpy device."""
    _, server = connected_client_and_server
    endpoints = {
        1: {
            SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return create_mock_zigpy_device(server, endpoints)


@pytest.fixture
async def device_switch_1(
    connected_client_and_server: tuple[Controller, Server],
) -> Device:
    """Test zha switch platform."""

    _, server = connected_client_and_server

    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE,
    )
    zha_device = await join_zigpy_device(server, zigpy_device)
    zha_device.available = True
    return zha_device


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> BasePlatformEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + entity.unique_id: entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]


def get_group_entity(
    group_proxy: GroupProxy, entity_id: str
) -> Optional[SwitchGroupEntity]:
    """Get entity."""

    return group_proxy.group_model.entities.get(entity_id)


@pytest.fixture
async def device_switch_2(
    connected_client_and_server: tuple[Controller, Server],
) -> Device:
    """Test zha switch platform."""

    controller, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
    )
    zha_device = await join_zigpy_device(server, zigpy_device)
    zha_device.available = True
    return zha_device


async def test_controller_devices(
    zigpy_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test client controller device related functionality."""
    controller, server = connected_client_and_server
    zha_device = await join_zigpy_device(server, zigpy_device)
    entity_id = find_entity_id(Platform.SWITCH, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity: SwitchEntity = get_entity(client_device, entity_id)
    assert entity is not None

    assert isinstance(entity, SwitchEntity)

    assert entity.state.state is False

    await controller.load_devices()
    devices: dict[EUI64, DeviceProxy] = controller.devices
    assert len(devices) == 2
    assert zha_device.ieee in devices

    # test client -> server
    server.application_controller.remove = AsyncMock(
        wraps=server.application_controller.remove
    )
    await controller.devices_helper.remove_device(client_device.device_model)
    assert server.application_controller.remove.await_count == 1
    assert server.application_controller.remove.await_args == call(
        client_device.device_model.ieee
    )

    # test server -> client
    server.device_removed(zigpy_device)
    await server.async_block_till_done()
    assert len(controller.devices) == 1

    # rejoin the device
    zha_device = await join_zigpy_device(server, zigpy_device)
    await server.async_block_till_done()
    assert len(controller.devices) == 2

    # test rejoining the same device
    zha_device = await join_zigpy_device(server, zigpy_device)
    await server.async_block_till_done()
    assert len(controller.devices) == 2

    # we removed and joined the device again so lets get the entity again
    client_device = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity: SwitchEntity = get_entity(client_device, entity_id)  # type: ignore
    assert entity is not None

    # test device reconfigure
    zha_device.async_configure = AsyncMock(wraps=zha_device.async_configure)
    await controller.devices_helper.reconfigure_device(client_device.device_model)
    await server.async_block_till_done()
    assert zha_device.async_configure.call_count == 1
    assert zha_device.async_configure.await_count == 1
    assert zha_device.async_configure.call_args == call()

    # test read cluster attribute
    cluster = zigpy_device.endpoints.get(1).on_off
    assert cluster is not None
    cluster.PLUGGED_ATTR_READS = {general.OnOff.AttributeDefs.on_off.name: 1}
    update_attribute_cache(cluster)
    await controller.entities.refresh_state(entity)
    await server.async_block_till_done()
    read_response: ReadClusterAttributesResponse = (
        await controller.devices_helper.read_cluster_attributes(
            client_device.device_model,
            general.OnOff.cluster_id,
            "in",
            1,
            [general.OnOff.AttributeDefs.on_off.name],
        )
    )
    await server.async_block_till_done()
    assert read_response is not None
    assert read_response.success is True
    assert len(read_response.succeeded) == 1
    assert len(read_response.failed) == 0
    assert read_response.succeeded[general.OnOff.AttributeDefs.on_off.name] == 1
    assert read_response.cluster.id == general.OnOff.cluster_id
    assert read_response.cluster.endpoint_id == 1
    assert (
        read_response.cluster.endpoint_attribute
        == general.OnOff.AttributeDefs.on_off.name
    )
    assert read_response.cluster.name == general.OnOff.name
    assert entity.state.state is True

    # test write cluster attribute
    write_response: WriteClusterAttributeResponse = (
        await controller.devices_helper.write_cluster_attribute(
            client_device.device_model,
            general.OnOff.cluster_id,
            "in",
            1,
            general.OnOff.AttributeDefs.on_off.name,
            0,
        )
    )
    assert write_response is not None
    assert write_response.success is True
    assert write_response.cluster.id == general.OnOff.cluster_id
    assert write_response.cluster.endpoint_id == 1
    assert (
        write_response.cluster.endpoint_attribute
        == general.OnOff.AttributeDefs.on_off.name
    )
    assert write_response.cluster.name == general.OnOff.name

    await controller.entities.refresh_state(entity)
    await server.async_block_till_done()
    assert entity.state.state is False

    # test controller events
    listener = MagicMock()

    # test device joined
    controller.on_event(ControllerEvents.DEVICE_JOINED, listener)
    device_joined_event = DeviceJoinedEvent(
        device_info=DeviceJoinedDeviceInfo(
            pairing_status=DevicePairingStatus.PAIRED,
            ieee=zigpy_device.ieee,
            nwk=zigpy_device.nwk,
        )
    )
    server.device_joined(zigpy_device)
    await server.async_block_till_done()
    assert listener.call_count == 1
    assert listener.call_args == call(device_joined_event)

    # test device left
    listener.reset_mock()
    controller.on_event(ControllerEvents.DEVICE_LEFT, listener)
    server.device_left(zigpy_device)
    await server.async_block_till_done()
    assert listener.call_count == 1
    assert listener.call_args == call(
        DeviceLeftEvent(
            ieee=zigpy_device.ieee,
            nwk=str(zigpy_device.nwk).lower(),
        )
    )

    # test raw  device initialized
    listener.reset_mock()
    controller.on_event(ControllerEvents.RAW_DEVICE_INITIALIZED, listener)
    server.raw_device_initialized(zigpy_device)
    await server.async_block_till_done()
    assert listener.call_count == 1
    assert listener.call_args == call(
        RawDeviceInitializedEvent(
            device_info=RawDeviceInitializedDeviceInfo(
                pairing_status=DevicePairingStatus.INTERVIEW_COMPLETE,
                ieee=zigpy_device.ieee,
                nwk=zigpy_device.nwk,
                manufacturer=client_device.device_model.manufacturer,
                model=client_device.device_model.model,
                signature=client_device.device_model.signature,
            ),
        )
    )


async def test_controller_groups(
    device_switch_1: Device,
    device_switch_2: Device,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test client controller group related functionality."""
    controller, server = connected_client_and_server
    member_ieee_addresses = [device_switch_1.ieee, device_switch_2.ieee]
    members = [
        GroupMemberReference(ieee=device_switch_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_switch_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await server.async_create_zigpy_group("Test Group", members)
    await server.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.SWITCH, zha_group)
    assert entity_id is not None

    group_proxy: Optional[GroupProxy] = controller.groups.get(zha_group.group_id)
    assert group_proxy is not None

    entity: SwitchGroupEntity = get_group_entity(group_proxy, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, SwitchGroupEntity)

    assert entity is not None

    await controller.load_groups()
    groups: dict[int, GroupProxy] = controller.groups
    # the application controller mock starts with a group already created
    assert len(groups) == 2
    assert zha_group.group_id in groups

    # test client -> server
    await controller.groups_helper.remove_groups([group_proxy.group_model])
    await server.async_block_till_done()
    assert len(controller.groups) == 1

    # test client create group
    client_device1: Optional[DeviceProxy] = controller.devices.get(device_switch_1.ieee)
    assert client_device1 is not None
    entity_id1 = find_entity_id(Platform.SWITCH, device_switch_1)
    assert entity_id1 is not None
    entity1: SwitchEntity = get_entity(client_device1, entity_id1)
    assert entity1 is not None

    client_device2: Optional[DeviceProxy] = controller.devices.get(device_switch_2.ieee)
    assert client_device2 is not None
    entity_id2 = find_entity_id(Platform.SWITCH, device_switch_2)
    assert entity_id2 is not None
    entity2: SwitchEntity = get_entity(client_device2, entity_id2)
    assert entity2 is not None

    response: GroupInfo = await controller.groups_helper.create_group(
        members=[entity1, entity2], name="Test Group Controller"
    )
    await server.async_block_till_done()
    assert len(controller.groups) == 2
    assert response.group_id in controller.groups
    assert response.name == "Test Group Controller"
    assert client_device1.device_model.ieee in response.members_by_ieee
    assert client_device2.device_model.ieee in response.members_by_ieee

    # test remove member from group from controller
    response = await controller.groups_helper.remove_group_members(response, [entity2])
    await server.async_block_till_done()
    assert len(controller.groups) == 2
    assert response.group_id in controller.groups
    assert response.name == "Test Group Controller"
    assert client_device1.device_model.ieee in response.members_by_ieee
    assert client_device2.device_model.ieee not in response.members_by_ieee

    # test add member to group from controller
    response = await controller.groups_helper.add_group_members(response, [entity2])
    await server.async_block_till_done()
    assert len(controller.groups) == 2
    assert response.group_id in controller.groups
    assert response.name == "Test Group Controller"
    assert client_device1.device_model.ieee in response.members_by_ieee
    assert client_device2.device_model.ieee in response.members_by_ieee
