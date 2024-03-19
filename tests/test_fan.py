"""Test zha fan."""

# pylint: disable=redefined-outer-name

from collections.abc import Awaitable, Callable
import logging
from typing import Optional
from unittest.mock import AsyncMock, call, patch

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, hvac
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.gateway import ZHAGateway
from zha.application.platforms import GroupEntity, PlatformEntity
from zha.application.platforms.fan.const import (
    PRESET_MODE_AUTO,
    PRESET_MODE_ON,
    PRESET_MODE_SMART,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MEDIUM,
    SPEED_OFF,
)
from zha.exceptions import ZHAException
from zha.zigbee.device import ZHADevice
from zha.zigbee.group import Group, GroupMemberReference

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
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha fan platform."""

    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Groups.cluster_id,
                    general.OnOff.cluster_id,
                    hvac.Fan.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            },
        },
        ieee=IEEE_GROUPABLE_DEVICE,
    )
    zha_device = await device_joined(zigpy_dev)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_fan_2(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha fan platform."""

    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Groups.cluster_id,
                    general.OnOff.cluster_id,
                    hvac.Fan.cluster_id,
                    general.LevelControl.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.LEVEL_CONTROL_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            },
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
    )
    zha_device = await device_joined(zigpy_dev)
    zha_device.available = True
    return zha_device


def get_entity(zha_dev: ZHADevice, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]


def get_group_entity(group: Group, entity_id: str) -> Optional[GroupEntity]:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in group.group_entities.values()
    }

    return entities.get(entity_id)


async def test_fan(
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
    zigpy_device: ZigpyDevice,
    zha_gateway: ZHAGateway,
) -> None:
    """Test zha fan platform."""

    zha_device = await device_joined(zigpy_device)
    cluster = zigpy_device.endpoints.get(1).fan
    entity_id = find_entity_id(Platform.FAN, zha_device)
    assert entity_id is not None

    entity = get_entity(zha_device, entity_id)
    assert entity is not None
    assert entity.get_state()["is_on"] is False

    # turn on at fan
    await send_attributes_report(zha_gateway, cluster, {1: 2, 0: 1, 2: 3})
    assert entity.get_state()["is_on"] is True

    # turn off at fan
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.get_state()["is_on"] is False

    # turn on from client
    cluster.write_attributes.reset_mock()
    await async_turn_on(zha_gateway, entity)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 2}, manufacturer=None
    )
    assert entity.get_state()["is_on"] is True

    # turn off from client
    cluster.write_attributes.reset_mock()
    await async_turn_off(zha_gateway, entity)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 0}, manufacturer=None
    )
    assert entity.get_state()["is_on"] is False

    # change speed from client
    cluster.write_attributes.reset_mock()
    await async_set_speed(zha_gateway, entity, speed=SPEED_HIGH)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 3}, manufacturer=None
    )
    assert entity.get_state()["is_on"] is True
    assert entity.get_state()["speed"] == SPEED_HIGH

    # change preset_mode from client
    cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_ON)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 4}, manufacturer=None
    )
    assert entity.get_state()["is_on"] is True
    assert entity.get_state()["preset_mode"] == PRESET_MODE_ON

    # test set percentage from client
    cluster.write_attributes.reset_mock()
    await entity.async_set_percentage(50)
    await zha_gateway.async_block_till_done()
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 2}, manufacturer=None
    )
    # this is converted to a ranged value
    assert entity.get_state()["percentage"] == 66
    assert entity.get_state()["is_on"] is True

    # set invalid preset_mode from client
    cluster.write_attributes.reset_mock()

    with pytest.raises(KeyError, match="invalid"):
        await entity.async_set_preset_mode("invalid")
        assert len(cluster.write_attributes.mock_calls) == 0

    # test percentage in turn on command
    await entity.async_turn_on(percentage=25)
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["percentage"] == 33  # this is converted to a ranged value
    assert entity.get_state()["speed"] == SPEED_LOW

    # test speed in turn on command
    await entity.async_turn_on(speed=SPEED_HIGH)
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["percentage"] == 100
    assert entity.get_state()["speed"] == SPEED_HIGH


async def async_turn_on(
    zha_gateway: ZHAGateway,
    entity: PlatformEntity,
    speed: Optional[str] = None,
) -> None:
    """Turn fan on."""
    await entity.async_turn_on(speed=speed)
    await zha_gateway.async_block_till_done()


async def async_turn_off(zha_gateway: ZHAGateway, entity: PlatformEntity) -> None:
    """Turn fan off."""
    await entity.async_turn_off()
    await zha_gateway.async_block_till_done()


async def async_set_speed(
    zha_gateway: ZHAGateway,
    entity: PlatformEntity,
    speed: Optional[str] = None,
) -> None:
    """Set speed for specified fan."""
    await entity.async_turn_on(speed=speed)
    await zha_gateway.async_block_till_done()


async def async_set_preset_mode(
    zha_gateway: ZHAGateway,
    entity: PlatformEntity,
    preset_mode: Optional[str] = None,
) -> None:
    """Set preset_mode for specified fan."""
    assert preset_mode is not None
    await entity.async_set_preset_mode(preset_mode)
    await zha_gateway.async_block_till_done()


@patch(
    "zigpy.zcl.clusters.hvac.Fan.write_attributes",
    new=AsyncMock(return_value=zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]),
)
async def test_zha_group_fan_entity(
    device_fan_1: ZHADevice, device_fan_2: ZHADevice, zha_gateway: ZHAGateway
):
    """Test the fan entity for a ZHAWS group."""

    member_ieee_addresses = [device_fan_1.ieee, device_fan_2.ieee]
    members = [
        GroupMemberReference(ieee=device_fan_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_fan_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await zha_gateway.async_create_zigpy_group("Test Group", members)
    await zha_gateway.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.FAN, zha_group)
    assert entity_id is not None

    entity: GroupEntity = get_group_entity(zha_group, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, GroupEntity)

    group_fan_cluster = zha_group.zigpy_group.endpoint[hvac.Fan.cluster_id]

    dev1_fan_cluster = device_fan_1.device.endpoints[1].fan
    dev2_fan_cluster = device_fan_2.device.endpoints[1].fan

    # test that the fan group entity was created and is off
    assert entity.get_state()["is_on"] is False

    # turn on from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_turn_on(zha_gateway, entity)
    await zha_gateway.async_block_till_done()
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 2}

    # turn off from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_turn_off(zha_gateway, entity)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 0}

    # change speed from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_speed(zha_gateway, entity, speed=SPEED_HIGH)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 3}

    # change preset mode from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_ON)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 4}

    # change preset mode from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_AUTO)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 5}

    # change preset mode from client
    group_fan_cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_SMART)
    assert len(group_fan_cluster.write_attributes.mock_calls) == 1
    assert group_fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 6}

    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(zha_gateway, dev1_fan_cluster, {0: 0})
    await send_attributes_report(zha_gateway, dev2_fan_cluster, {0: 0})

    # test that group fan is off
    assert entity.get_state()["is_on"] is False

    await send_attributes_report(zha_gateway, dev2_fan_cluster, {0: 2})
    await zha_gateway.async_block_till_done()

    # test that group fan is speed medium
    assert entity.get_state()["is_on"] is True

    await send_attributes_report(zha_gateway, dev2_fan_cluster, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group fan is now off
    assert entity.get_state()["is_on"] is False


@patch(
    "zigpy.zcl.clusters.hvac.Fan.write_attributes",
    new=AsyncMock(side_effect=ZigbeeException),
)
async def test_zha_group_fan_entity_failure_state(
    device_fan_1: ZHADevice,
    device_fan_2: ZHADevice,
    zha_gateway: ZHAGateway,
    caplog: pytest.LogCaptureFixture,
):
    """Test the fan entity for a ZHA group when writing attributes generates an exception."""

    member_ieee_addresses = [device_fan_1.ieee, device_fan_2.ieee]
    members = [
        GroupMemberReference(ieee=device_fan_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_fan_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await zha_gateway.async_create_zigpy_group("Test Group", members)
    await zha_gateway.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.FAN, zha_group)
    assert entity_id is not None

    entity: GroupEntity = get_group_entity(zha_group, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, GroupEntity)

    group_fan_cluster = zha_group.zigpy_group.endpoint[hvac.Fan.cluster_id]

    # test that the fan group entity was created and is off
    assert entity.get_state()["is_on"] is False

    # turn on from client
    group_fan_cluster.write_attributes.reset_mock()
    with pytest.raises(ZHAException, match="Failed to send request"):
        await async_turn_on(zha_gateway, entity)
        await zha_gateway.async_block_till_done()
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
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
    zigpy_device: ZigpyDevice,
    zha_gateway: ZHAGateway,  # pylint: disable=unused-argument
    plug_read: dict,
    expected_state: bool,
    expected_speed: Optional[str],
    expected_percentage: Optional[int],
):
    """Test zha fan platform."""

    cluster = zigpy_device.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = plug_read
    zha_device = await device_joined(zigpy_device)
    entity_id = find_entity_id(Platform.FAN, zha_device)
    assert entity_id is not None

    entity = get_entity(zha_device, entity_id)
    assert entity is not None

    assert entity.get_state()["is_on"] == expected_state
    assert entity.get_state()["speed"] == expected_speed
    assert entity.get_state()["percentage"] == expected_percentage
    assert entity.get_state()["preset_mode"] is None


async def test_fan_update_entity(
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
    zigpy_device: ZigpyDevice,
    zha_gateway: ZHAGateway,
):
    """Test zha fan refresh state."""

    cluster = zigpy_device.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = {"fan_mode": 0}
    zha_device = await device_joined(zigpy_device)
    entity_id = find_entity_id(Platform.FAN, zha_device)
    assert entity_id is not None

    entity = get_entity(zha_device, entity_id)
    assert entity is not None

    assert entity.get_state()["is_on"] is False
    assert entity.get_state()["speed"] == SPEED_OFF
    assert entity.get_state()["percentage"] == 0
    assert entity.get_state()["preset_mode"] is None
    assert entity.percentage_step == 100 / 3
    assert cluster.read_attributes.await_count == 2

    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["is_on"] is False
    assert entity.get_state()["speed"] == SPEED_OFF
    assert cluster.read_attributes.await_count == 3

    cluster.PLUGGED_ATTR_READS = {"fan_mode": 1}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["is_on"] is True
    assert entity.get_state()["percentage"] == 33
    assert entity.get_state()["speed"] == SPEED_LOW
    assert entity.get_state()["preset_mode"] is None
    assert entity.percentage_step == 100 / 3
    assert cluster.read_attributes.await_count == 4
