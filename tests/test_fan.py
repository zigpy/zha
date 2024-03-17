"""Test zha fan."""
import logging
from typing import Awaitable, Callable, Optional
from unittest.mock import AsyncMock, call, patch

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import ZigbeeException
import zigpy.profiles.zha as zha
import zigpy.zcl.clusters.general as general
import zigpy.zcl.clusters.hvac as hvac
import zigpy.zcl.foundation as zcl_f

from zhaws.client.controller import Controller
from zhaws.client.model.types import FanEntity, FanGroupEntity
from zhaws.client.proxy import DeviceProxy, GroupProxy
from zhaws.server.platforms.fan import (
    PRESET_MODE_AUTO,
    PRESET_MODE_ON,
    PRESET_MODE_SMART,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MEDIUM,
    SPEED_OFF,
)
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device
from zhaws.server.zigbee.group import Group, GroupMemberReference

from .common import async_find_group_entity_id, find_entity_id, send_attributes_report
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def zigpy_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [hvac.Fan.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return zigpy_device_mock(
        endpoints, node_descriptor=b"\x02@\x8c\x02\x10RR\x00\x00\x00R\x00\x00"
    )


@pytest.fixture
async def device_fan_1(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Test zha fan platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Groups.cluster_id,
                    general.OnOff.cluster_id,
                    hvac.Fan.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            },
        },
        ieee=IEEE_GROUPABLE_DEVICE,
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_fan_2(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Test zha fan platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Groups.cluster_id,
                    general.OnOff.cluster_id,
                    hvac.Fan.cluster_id,
                    general.LevelControl.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            },
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> FanEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]  # type: ignore


def get_group_entity(
    group_proxy: GroupProxy, entity_id: str
) -> Optional[FanGroupEntity]:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in group_proxy.group_model.entities.values()
    }

    return entities.get(entity_id)  # type: ignore


async def test_fan(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test zha fan platform."""
    controller, server = connected_client_and_server
    zha_device = await device_joined(zigpy_device)
    cluster = zigpy_device.endpoints.get(1).fan
    entity_id = find_entity_id(Platform.FAN, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None
    assert entity.state.is_on is False

    # turn on at fan
    await send_attributes_report(server, cluster, {1: 2, 0: 1, 2: 3})
    assert entity.state.is_on is True

    # turn off at fan
    await send_attributes_report(server, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.state.is_on is False

    # turn on from client
    cluster.write_attributes.reset_mock()
    await async_turn_on(server, entity, controller)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call({"fan_mode": 2})
    assert entity.state.is_on is True

    # turn off from client
    cluster.write_attributes.reset_mock()
    await async_turn_off(server, entity, controller)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call({"fan_mode": 0})
    assert entity.state.is_on is False

    # change speed from client
    cluster.write_attributes.reset_mock()
    await async_set_speed(server, entity, controller, speed=SPEED_HIGH)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call({"fan_mode": 3})
    assert entity.state.is_on is True
    assert entity.state.speed == SPEED_HIGH

    # change preset_mode from client
    cluster.write_attributes.reset_mock()
    await async_set_preset_mode(server, entity, controller, preset_mode=PRESET_MODE_ON)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call({"fan_mode": 4})
    assert entity.state.is_on is True
    assert entity.state.preset_mode == PRESET_MODE_ON

    # test set percentage from client
    cluster.write_attributes.reset_mock()
    await controller.fans.set_fan_percentage(entity, 50)
    await server.block_till_done()
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call({"fan_mode": 2})
    # this is converted to a ranged value
    assert entity.state.percentage == 66
    assert entity.state.is_on is True

    # set invalid preset_mode from client
    cluster.write_attributes.reset_mock()
    response_error = await controller.fans.set_fan_preset_mode(entity, "invalid")
    assert response_error is not None
    assert (
        response_error.error_message
        == "The preset_mode invalid is not a valid preset_mode: ['on', 'auto', 'smart']"
    )
    assert response_error.error_code == "PLATFORM_ENTITY_ACTION_ERROR"
    assert response_error.zigbee_error_code is None
    assert response_error.command == "error.fan_set_preset_mode"
    assert "Error executing command: async_set_preset_mode" in caplog.text
    assert len(cluster.write_attributes.mock_calls) == 0

    # test percentage in turn on command
    await controller.fans.turn_on(entity, percentage=25)
    await server.block_till_done()
    assert entity.state.percentage == 33  # this is converted to a ranged value
    assert entity.state.speed == SPEED_LOW

    # test speed in turn on command
    await controller.fans.turn_on(entity, speed=SPEED_HIGH)
    await server.block_till_done()
    assert entity.state.percentage == 100
    assert entity.state.speed == SPEED_HIGH


async def async_turn_on(
    server: Server,
    entity: FanEntity,
    controller: Controller,
    speed: Optional[str] = None,
) -> None:
    """Turn fan on."""
    await controller.fans.turn_on(entity, speed=speed)
    await server.block_till_done()


async def async_turn_off(
    server: Server, entity: FanEntity, controller: Controller
) -> None:
    """Turn fan off."""
    await controller.fans.turn_off(entity)
    await server.block_till_done()


async def async_set_speed(
    server: Server,
    entity: FanEntity,
    controller: Controller,
    speed: Optional[str] = None,
) -> None:
    """Set speed for specified fan."""
    await controller.fans.turn_on(entity, speed=speed)
    await server.block_till_done()


async def async_set_preset_mode(
    server: Server,
    entity: FanEntity,
    controller: Controller,
    preset_mode: Optional[str] = None,
) -> None:
    """Set preset_mode for specified fan."""
    assert preset_mode is not None
    await controller.fans.set_fan_preset_mode(entity, preset_mode)
    await server.block_till_done()


@patch(
    "zigpy.zcl.clusters.hvac.Fan.write_attributes",
    new=AsyncMock(return_value=zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]),
)
async def test_zha_group_fan_entity(
    device_fan_1: Device,
    device_fan_2: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test the fan entity for a ZHAWS group."""
    controller, server = connected_client_and_server
    member_ieee_addresses = [device_fan_1.ieee, device_fan_2.ieee]
    members = [
        GroupMemberReference(ieee=device_fan_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_fan_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await server.controller.async_create_zigpy_group(
        "Test Group", members
    )
    await server.block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.FAN, zha_group)
    assert entity_id is not None

    group_proxy: Optional[GroupProxy] = controller.groups.get(2)
    assert group_proxy is not None

    entity: FanGroupEntity = get_group_entity(group_proxy, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, FanGroupEntity)

    group_fan_cluster = zha_group.zigpy_group.endpoint[hvac.Fan.cluster_id]

    dev1_fan_cluster = device_fan_1.device.endpoints[1].fan
    dev2_fan_cluster = device_fan_2.device.endpoints[1].fan

    # test that the fan group entity was created and is off
    assert entity.state.is_on is False

    # turn on from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_turn_on(server, entity, controller)
    await server.block_till_done()
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 2}

    # turn off from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_turn_off(server, entity, controller)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 0}

    # change speed from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_speed(server, entity, controller, speed=SPEED_HIGH)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 3}

    # change preset mode from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_preset_mode(server, entity, controller, preset_mode=PRESET_MODE_ON)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 4}

    # change preset mode from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_preset_mode(
        server, entity, controller, preset_mode=PRESET_MODE_AUTO
    )
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 5}

    # change preset mode from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_preset_mode(
        server, entity, controller, preset_mode=PRESET_MODE_SMART
    )
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 6}

    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(server, dev1_fan_cluster, {0: 0})
    await send_attributes_report(server, dev2_fan_cluster, {0: 0})

    # test that group fan is off
    assert entity.state.is_on is False

    await send_attributes_report(server, dev2_fan_cluster, {0: 2})
    await server.block_till_done()

    # test that group fan is speed medium
    assert entity.state.is_on is True

    await send_attributes_report(server, dev2_fan_cluster, {0: 0})
    await server.block_till_done()

    # test that group fan is now off
    assert entity.state.is_on is False


@patch(
    "zigpy.zcl.clusters.hvac.Fan.write_attributes",
    new=AsyncMock(side_effect=ZigbeeException),
)
async def test_zha_group_fan_entity_failure_state(
    device_fan_1: Device,
    device_fan_2: Device,
    connected_client_and_server: tuple[Controller, Server],
    caplog: pytest.LogCaptureFixture,
):
    """Test the fan entity for a ZHA group when writing attributes generates an exception."""
    controller, server = connected_client_and_server
    member_ieee_addresses = [device_fan_1.ieee, device_fan_2.ieee]
    members = [
        GroupMemberReference(ieee=device_fan_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_fan_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await server.controller.async_create_zigpy_group(
        "Test Group", members
    )
    await server.block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.FAN, zha_group)
    assert entity_id is not None

    group_proxy: Optional[GroupProxy] = controller.groups.get(2)
    assert group_proxy is not None

    entity: FanGroupEntity = get_group_entity(group_proxy, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, FanGroupEntity)

    group_fan_cluster = zha_group.zigpy_group.endpoint[hvac.Fan.cluster_id]

    # test that the fan group entity was created and is off
    assert entity.state.is_on is False

    # turn on from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_turn_on(server, entity, controller)
    await server.block_till_done()
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 2}

    assert "Could not set fan mode" in caplog.text


@pytest.mark.parametrize(
    "plug_read, expected_state, expected_speed, expected_percentage",
    (
        ({"fan_mode": None}, False, None, None),
        ({"fan_mode": 0}, False, SPEED_OFF, 0),
        ({"fan_mode": 1}, True, SPEED_LOW, 33),
        ({"fan_mode": 2}, True, SPEED_MEDIUM, 66),
        ({"fan_mode": 3}, True, SPEED_HIGH, 100),
    ),
)
async def test_fan_init(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
    plug_read: dict,
    expected_state: bool,
    expected_speed: Optional[str],
    expected_percentage: Optional[int],
):
    """Test zha fan platform."""
    controller, server = connected_client_and_server
    cluster = zigpy_device.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = plug_read
    zha_device = await device_joined(zigpy_device)
    entity_id = find_entity_id(Platform.FAN, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    assert entity.state.is_on == expected_state
    assert entity.state.speed == expected_speed
    assert entity.state.percentage == expected_percentage
    assert entity.state.preset_mode is None


async def test_fan_update_entity(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test zha fan refresh state."""
    controller, server = connected_client_and_server
    cluster = zigpy_device.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = {"fan_mode": 0}
    zha_device = await device_joined(zigpy_device)
    entity_id = find_entity_id(Platform.FAN, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    assert entity.state.is_on is False
    assert entity.state.speed == SPEED_OFF
    assert entity.state.percentage == 0
    assert entity.state.preset_mode is None
    assert entity.percentage_step == 100 / 3
    assert cluster.read_attributes.await_count == 2

    await controller.entities.refresh_state(entity)
    await server.block_till_done()
    assert entity.state.is_on is False
    assert entity.state.speed == SPEED_OFF
    assert cluster.read_attributes.await_count == 3

    cluster.PLUGGED_ATTR_READS = {"fan_mode": 1}
    await controller.entities.refresh_state(entity)
    await server.block_till_done()
    assert entity.state.is_on is True
    assert entity.state.percentage == 33
    assert entity.state.speed == SPEED_LOW
    assert entity.state.preset_mode is None
    assert entity.percentage_step == 100 / 3
    assert cluster.read_attributes.await_count == 4
