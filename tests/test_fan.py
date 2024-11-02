"""Test zha fan."""

# pylint: disable=redefined-outer-name

import asyncio
import logging
from typing import Optional
from unittest.mock import AsyncMock, call, patch

import pytest
import zhaquirks
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, hvac
import zigpy.zcl.foundation as zcl_f
import zigpy.zdo.types as zdo_t

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    get_group_entity,
    group_entity_availability_test,
    join_zigpy_device,
    send_attributes_report,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import GroupEntity, PlatformEntity
from zha.application.platforms.fan.const import (
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    PRESET_MODE_AUTO,
    PRESET_MODE_ON,
    PRESET_MODE_SMART,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MEDIUM,
    SPEED_OFF,
)
from zha.application.platforms.fan.helpers import NotValidPresetModeError
from zha.exceptions import ZHAException
from zha.zigbee.device import Device
from zha.zigbee.group import Group, GroupMemberReference

IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"

_LOGGER = logging.getLogger(__name__)


def zigpy_device_mock(zha_gateway: Gateway) -> ZigpyDevice:
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [hvac.Fan.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return create_mock_zigpy_device(
        zha_gateway,
        endpoints,
        node_descriptor=zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.EndDevice,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.RxOnWhenIdle
                | zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
            ),
            manufacturer_code=4098,
            maximum_buffer_size=82,
            maximum_incoming_transfer_size=82,
            server_mask=0,
            maximum_outgoing_transfer_size=82,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        ),
    )


async def device_fan_1_mock(zha_gateway: Gateway) -> Device:
    """Test zha fan platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
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
    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)
    return zha_device


async def device_fan_2_mock(zha_gateway: Gateway) -> Device:
    """Test zha fan platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
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
    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)
    return zha_device


async def test_fan(
    zha_gateway: Gateway,
) -> None:
    """Test zha fan platform."""

    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints.get(1).fan

    entity = get_entity(zha_device, platform=Platform.FAN)
    assert entity.state["is_on"] is False

    # turn on at fan
    await send_attributes_report(zha_gateway, cluster, {1: 2, 0: 1, 2: 3})
    assert entity.state["is_on"] is True

    # turn off at fan
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.state["is_on"] is False

    # turn on from client
    cluster.write_attributes.reset_mock()
    await async_turn_on(zha_gateway, entity)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 2}, manufacturer=None
    )
    assert entity.state["is_on"] is True

    # turn off from client
    cluster.write_attributes.reset_mock()
    await async_turn_off(zha_gateway, entity)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 0}, manufacturer=None
    )
    assert entity.state["is_on"] is False

    # change speed from client
    cluster.write_attributes.reset_mock()
    await async_set_speed(zha_gateway, entity, speed=SPEED_HIGH)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 3}, manufacturer=None
    )
    assert entity.state["is_on"] is True
    assert entity.state["speed"] == SPEED_HIGH

    # change preset_mode from client
    cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_ON)
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 4}, manufacturer=None
    )
    assert entity.state["is_on"] is True
    assert entity.state["preset_mode"] == PRESET_MODE_ON

    # test set percentage from client
    cluster.write_attributes.reset_mock()
    await entity.async_set_percentage(50)
    await zha_gateway.async_block_till_done()
    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"fan_mode": 2}, manufacturer=None
    )
    # this is converted to a ranged value
    assert entity.state["percentage"] == 66
    assert entity.state["is_on"] is True

    # set invalid preset_mode from client
    cluster.write_attributes.reset_mock()

    with pytest.raises(NotValidPresetModeError):
        await entity.async_set_preset_mode("invalid")
        assert len(cluster.write_attributes.mock_calls) == 0

    # test percentage in turn on command
    await entity.async_turn_on(percentage=25)
    await zha_gateway.async_block_till_done()
    assert entity.state["percentage"] == 33  # this is converted to a ranged value
    assert entity.state["speed"] == SPEED_LOW

    # test speed in turn on command
    await entity.async_turn_on(speed=SPEED_HIGH)
    await zha_gateway.async_block_till_done()
    assert entity.state["percentage"] == 100
    assert entity.state["speed"] == SPEED_HIGH


async def async_turn_on(
    zha_gateway: Gateway,
    entity: PlatformEntity,
    speed: Optional[str] = None,
) -> None:
    """Turn fan on."""
    await entity.async_turn_on(speed=speed)
    await zha_gateway.async_block_till_done()


async def async_turn_off(zha_gateway: Gateway, entity: PlatformEntity) -> None:
    """Turn fan off."""
    await entity.async_turn_off()
    await zha_gateway.async_block_till_done()


async def async_set_speed(
    zha_gateway: Gateway,
    entity: PlatformEntity,
    speed: Optional[str] = None,
) -> None:
    """Set speed for specified fan."""
    await entity.async_turn_on(speed=speed)
    await zha_gateway.async_block_till_done()


async def async_set_percentage(
    zha_gateway: Gateway, entity: PlatformEntity, percentage=None
):
    """Set percentage for specified fan."""
    await entity.async_set_percentage(percentage)
    await zha_gateway.async_block_till_done()


async def async_set_preset_mode(
    zha_gateway: Gateway,
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
    zha_gateway: Gateway,
):
    """Test the fan entity for a ZHAWS group."""
    device_fan_1 = await device_fan_1_mock(zha_gateway)
    device_fan_2 = await device_fan_2_mock(zha_gateway)
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

    entity: GroupEntity = get_group_entity(zha_group, platform=Platform.FAN)

    assert entity.group_id == zha_group.group_id
    assert isinstance(entity, GroupEntity)
    assert entity.info_object.fallback_name == zha_group.name

    group_fan_cluster = zha_group.zigpy_group.endpoint[hvac.Fan.cluster_id]

    dev1_fan_cluster = device_fan_1.device.endpoints[1].fan
    dev2_fan_cluster = device_fan_2.device.endpoints[1].fan

    # test that the fan group entity was created and is off
    assert entity.state["is_on"] is False

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
    assert entity.state["is_on"] is False

    await send_attributes_report(zha_gateway, dev2_fan_cluster, {0: 2})
    await zha_gateway.async_block_till_done()

    # no update yet because of debouncing
    assert entity.state["is_on"] is False

    # member updates are debounced for .5s
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()

    assert entity.state["is_on"] is True

    await send_attributes_report(zha_gateway, dev2_fan_cluster, {0: 0})
    await zha_gateway.async_block_till_done()

    # no update yet because of debouncing
    assert entity.state["is_on"] is True

    # member updates are debounced for .5s
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()

    # test that group fan is now off
    assert entity.state["is_on"] is False

    await group_entity_availability_test(
        zha_gateway, device_fan_1, device_fan_2, entity
    )


@patch(
    "zigpy.zcl.clusters.hvac.Fan.write_attributes",
    new=AsyncMock(side_effect=ZigbeeException),
)
async def test_zha_group_fan_entity_failure_state(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
):
    """Test the fan entity for a ZHA group when writing attributes generates an exception."""

    device_fan_1 = await device_fan_1_mock(zha_gateway)
    device_fan_2 = await device_fan_2_mock(zha_gateway)
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

    entity: GroupEntity = get_group_entity(zha_group, platform=Platform.FAN)
    assert entity.group_id == zha_group.group_id

    group_fan_cluster = zha_group.zigpy_group.endpoint[hvac.Fan.cluster_id]

    # test that the fan group entity was created and is off
    assert entity.state["is_on"] is False

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
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    plug_read: dict,
    expected_state: bool,
    expected_speed: Optional[str],
    expected_percentage: Optional[int],
):
    """Test zha fan platform."""

    zigpy_device = zigpy_device_mock(zha_gateway)
    cluster = zigpy_device.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = plug_read
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] == expected_state
    assert entity.state["speed"] == expected_speed
    assert entity.state["percentage"] == expected_percentage
    assert entity.state["preset_mode"] is None


async def test_fan_update_entity(
    zha_gateway: Gateway,
):
    """Test zha fan refresh state."""

    zigpy_device = zigpy_device_mock(zha_gateway)
    cluster = zigpy_device.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = {"fan_mode": 0}
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] is False
    assert entity.state["speed"] == SPEED_OFF
    assert entity.state["percentage"] == 0
    assert entity.state["preset_mode"] is None
    assert entity.percentage_step == 100 / 3
    assert cluster.read_attributes.await_count == 2

    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["is_on"] is False
    assert entity.state["speed"] == SPEED_OFF
    assert cluster.read_attributes.await_count == 3

    cluster.PLUGGED_ATTR_READS = {"fan_mode": 1}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["is_on"] is True
    assert entity.state["percentage"] == 33
    assert entity.state["speed"] == SPEED_LOW
    assert entity.state["preset_mode"] is None
    assert entity.percentage_step == 100 / 3
    assert cluster.read_attributes.await_count == 4


def zigpy_device_ikea_mock(zha_gateway: Gateway) -> ZigpyDevice:
    """Ikea fan zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [
                general.Basic.cluster_id,
                general.Identify.cluster_id,
                general.Groups.cluster_id,
                general.Scenes.cluster_id,
                64637,
            ],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.COMBINED_INTERFACE,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        },
    }
    return create_mock_zigpy_device(
        zha_gateway,
        endpoints,
        manufacturer="IKEA of Sweden",
        model="STARKVIND Air purifier",
        quirk=zhaquirks.ikea.starkvind.IkeaSTARKVIND,
        node_descriptor=zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.EndDevice,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.RxOnWhenIdle
                | zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
            ),
            manufacturer_code=4098,
            maximum_buffer_size=82,
            maximum_incoming_transfer_size=82,
            server_mask=0,
            maximum_outgoing_transfer_size=82,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        ),
    )


async def test_fan_ikea(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA fan Ikea platform."""
    zigpy_device_ikea = zigpy_device_ikea_mock(zha_gateway)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_ikea)
    cluster = zigpy_device_ikea.endpoints.get(1).ikea_airpurifier
    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] is False

    # turn on at fan
    await send_attributes_report(zha_gateway, cluster, {6: 1})
    assert entity.state["is_on"] is True

    # turn off at fan
    await send_attributes_report(zha_gateway, cluster, {6: 0})
    assert entity.state["is_on"] is False

    # turn on from HA
    cluster.write_attributes.reset_mock()
    await async_turn_on(zha_gateway, entity)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 1}, manufacturer=None)
    ]

    # turn on with set speed from HA
    cluster.write_attributes.reset_mock()
    await async_turn_on(zha_gateway, entity, speed="high")
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 10}, manufacturer=None)
    ]

    # turn off from HA
    cluster.write_attributes.reset_mock()
    await async_turn_off(zha_gateway, entity)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 0}, manufacturer=None)
    ]

    # change speed from HA
    cluster.write_attributes.reset_mock()
    await async_set_percentage(zha_gateway, entity, percentage=100)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 10}, manufacturer=None)
    ]

    # skip 10% when set from HA
    cluster.write_attributes.reset_mock()
    await async_set_percentage(zha_gateway, entity, percentage=10)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 2}, manufacturer=None)
    ]

    # change preset_mode from HA
    cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_AUTO)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 1}, manufacturer=None)
    ]

    # set invalid preset_mode from HA
    cluster.write_attributes.reset_mock()
    with pytest.raises(NotValidPresetModeError):
        await async_set_preset_mode(
            zha_gateway,
            entity,
            preset_mode="invalid does not exist",
        )
    assert len(cluster.write_attributes.mock_calls) == 0


@pytest.mark.parametrize(
    (
        "ikea_plug_read",
        "ikea_expected_state",
        "ikea_expected_percentage",
        "ikea_preset_mode",
    ),
    [
        (None, False, None, None),
        ({"fan_mode": 0, "fan_speed": 0}, False, 0, None),
        ({"fan_mode": 1, "fan_speed": 30}, True, 60, PRESET_MODE_AUTO),
        ({"fan_mode": 10, "fan_speed": 10}, True, 20, None),
        ({"fan_mode": 15, "fan_speed": 15}, True, 30, None),
        ({"fan_mode": 20, "fan_speed": 20}, True, 40, None),
        ({"fan_mode": 25, "fan_speed": 25}, True, 50, None),
        ({"fan_mode": 30, "fan_speed": 30}, True, 60, None),
        ({"fan_mode": 35, "fan_speed": 35}, True, 70, None),
        ({"fan_mode": 40, "fan_speed": 40}, True, 80, None),
        ({"fan_mode": 45, "fan_speed": 45}, True, 90, None),
        ({"fan_mode": 50, "fan_speed": 50}, True, 100, None),
    ],
)
async def test_fan_ikea_init(
    ikea_plug_read: dict,
    ikea_expected_state: bool,
    ikea_expected_percentage: int,
    ikea_preset_mode: Optional[str],
    zha_gateway: Gateway,
) -> None:
    """Test ZHA fan platform."""
    zigpy_device_ikea = zigpy_device_ikea_mock(zha_gateway)
    cluster = zigpy_device_ikea.endpoints.get(1).ikea_airpurifier
    cluster.PLUGGED_ATTR_READS = ikea_plug_read

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_ikea)
    entity = get_entity(zha_device, platform=Platform.FAN)
    assert entity.state["is_on"] == ikea_expected_state
    assert entity.state["percentage"] == ikea_expected_percentage
    assert entity.state["preset_mode"] == ikea_preset_mode


async def test_fan_ikea_update_entity(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA fan platform."""
    zigpy_device_ikea = zigpy_device_ikea_mock(zha_gateway)
    cluster = zigpy_device_ikea.endpoints.get(1).ikea_airpurifier
    cluster.PLUGGED_ATTR_READS = {"fan_mode": 0, "fan_speed": 0}

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_ikea)
    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] is False
    assert entity.state[ATTR_PERCENTAGE] == 0
    assert entity.state[ATTR_PRESET_MODE] is None
    assert entity.percentage_step == 100 / 10

    cluster.PLUGGED_ATTR_READS = {"fan_mode": 1, "fan_speed": 6}

    await entity.async_update()
    await zha_gateway.async_block_till_done()

    assert entity.state["is_on"] is True
    assert entity.state[ATTR_PERCENTAGE] == 60
    assert entity.state[ATTR_PRESET_MODE] is PRESET_MODE_AUTO
    assert entity.percentage_step == 100 / 10


def zigpy_device_kof_mock(zha_gateway: Gateway) -> ZigpyDevice:
    """Fan by King of Fans zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [
                general.Basic.cluster_id,
                general.Identify.cluster_id,
                general.Groups.cluster_id,
                general.Scenes.cluster_id,
                64637,
            ],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.COMBINED_INTERFACE,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        },
    }
    return create_mock_zigpy_device(
        zha_gateway,
        endpoints,
        manufacturer="King Of Fans, Inc.",
        model="HBUniversalCFRemote",
        quirk=zhaquirks.kof.kof_mr101z.CeilingFan,
        node_descriptor=zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.EndDevice,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.RxOnWhenIdle
                | zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
            ),
            manufacturer_code=4098,
            maximum_buffer_size=82,
            maximum_incoming_transfer_size=82,
            server_mask=0,
            maximum_outgoing_transfer_size=82,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        ),
    )


async def test_fan_kof(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA fan platform for King of Fans."""
    zigpy_device_kof = zigpy_device_kof_mock(zha_gateway)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_kof)
    cluster = zigpy_device_kof.endpoints.get(1).fan
    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] is False

    # turn on at fan
    await send_attributes_report(zha_gateway, cluster, {1: 2, 0: 1, 2: 3})
    assert entity.state["is_on"] is True

    # turn off at fan
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.state["is_on"] is False

    # turn on from HA
    cluster.write_attributes.reset_mock()
    await async_turn_on(zha_gateway, entity)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 2}, manufacturer=None)
    ]

    # turn off from HA
    cluster.write_attributes.reset_mock()
    await async_turn_off(zha_gateway, entity)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 0}, manufacturer=None)
    ]

    # change speed from HA
    cluster.write_attributes.reset_mock()
    await async_set_percentage(zha_gateway, entity, percentage=100)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 4}, manufacturer=None)
    ]

    # change preset_mode from HA
    cluster.write_attributes.reset_mock()
    await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_SMART)
    assert cluster.write_attributes.mock_calls == [
        call({"fan_mode": 6}, manufacturer=None)
    ]

    # set invalid preset_mode from HA
    cluster.write_attributes.reset_mock()
    with pytest.raises(NotValidPresetModeError):
        await async_set_preset_mode(zha_gateway, entity, preset_mode=PRESET_MODE_AUTO)
    assert len(cluster.write_attributes.mock_calls) == 0


@pytest.mark.parametrize(
    ("plug_read", "expected_state", "expected_percentage", "expected_preset"),
    [
        (None, False, None, None),
        ({"fan_mode": 0}, False, 0, None),
        ({"fan_mode": 1}, True, 25, None),
        ({"fan_mode": 2}, True, 50, None),
        ({"fan_mode": 3}, True, 75, None),
        ({"fan_mode": 4}, True, 100, None),
        ({"fan_mode": 6}, True, None, PRESET_MODE_SMART),
    ],
)
async def test_fan_kof_init(
    zha_gateway: Gateway,
    plug_read: dict,
    expected_state: bool,
    expected_percentage: Optional[int],
    expected_preset: Optional[str],
) -> None:
    """Test ZHA fan platform for King of Fans."""

    zigpy_device_kof = zigpy_device_kof_mock(zha_gateway)
    cluster = zigpy_device_kof.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = plug_read

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_kof)
    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] is expected_state
    assert entity.state[ATTR_PERCENTAGE] == expected_percentage
    assert entity.state[ATTR_PRESET_MODE] == expected_preset


async def test_fan_kof_update_entity(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA fan platform for King of Fans."""

    zigpy_device_kof = zigpy_device_kof_mock(zha_gateway)
    cluster = zigpy_device_kof.endpoints.get(1).fan
    cluster.PLUGGED_ATTR_READS = {"fan_mode": 0}

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_kof)
    entity = get_entity(zha_device, platform=Platform.FAN)

    assert entity.state["is_on"] is False
    assert entity.state[ATTR_PERCENTAGE] == 0
    assert entity.state[ATTR_PRESET_MODE] is None
    assert entity.percentage_step == 100 / 4

    cluster.PLUGGED_ATTR_READS = {"fan_mode": 1}

    await entity.async_update()
    await zha_gateway.async_block_till_done()

    assert entity.state["is_on"] is True
    assert entity.state[ATTR_PERCENTAGE] == 25
    assert entity.state[ATTR_PRESET_MODE] is None
    assert entity.percentage_step == 100 / 4
