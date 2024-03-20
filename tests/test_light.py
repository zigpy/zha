"""Test zha light."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from unittest.mock import AsyncMock, call, patch, sentinel

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, lighting
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.gateway import ZHAGateway
from zha.application.platforms import GroupEntity, PlatformEntity
from zha.application.platforms.light.const import FLASH_EFFECTS, FLASH_LONG, FLASH_SHORT
from zha.zigbee.device import ZHADevice
from zha.zigbee.group import Group, GroupMemberReference

from .common import (
    async_find_group_entity_id,
    find_entity_id,
    send_attributes_report,
    update_attribute_cache,
)
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

ON = 1
OFF = 0
IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e9"
IEEE_GROUPABLE_DEVICE3 = "03:2d:6f:00:0a:90:69:e7"

_LOGGER = logging.getLogger(__name__)

LIGHT_ON_OFF = {
    1: {
        SIG_EP_PROFILE: zha.PROFILE_ID,
        SIG_EP_TYPE: zha.DeviceType.ON_OFF_LIGHT,
        SIG_EP_INPUT: [
            general.Basic.cluster_id,
            general.Identify.cluster_id,
            general.OnOff.cluster_id,
        ],
        SIG_EP_OUTPUT: [general.Ota.cluster_id],
    }
}

LIGHT_LEVEL = {
    1: {
        SIG_EP_PROFILE: zha.PROFILE_ID,
        SIG_EP_TYPE: zha.DeviceType.DIMMABLE_LIGHT,
        SIG_EP_INPUT: [
            general.Basic.cluster_id,
            general.LevelControl.cluster_id,
            general.OnOff.cluster_id,
        ],
        SIG_EP_OUTPUT: [general.Ota.cluster_id],
    }
}

LIGHT_COLOR = {
    1: {
        SIG_EP_PROFILE: zha.PROFILE_ID,
        SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
        SIG_EP_INPUT: [
            general.Basic.cluster_id,
            general.Identify.cluster_id,
            general.LevelControl.cluster_id,
            general.OnOff.cluster_id,
            lighting.Color.cluster_id,
        ],
        SIG_EP_OUTPUT: [general.Ota.cluster_id],
    }
}


@pytest.fixture
async def coordinator(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha light platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee="00:15:8d:00:02:32:4f:32",
        nwk=0x0000,
        node_descriptor=b"\xf8\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff",
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_1(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha light platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                    lighting.Color.cluster_id,
                    general.Groups.cluster_id,
                    general.Identify.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE,
        manufacturer="Philips",
        model="LWA004",
        nwk=0xB79D,
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_2(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha light platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                    lighting.Color.cluster_id,
                    general.Groups.cluster_id,
                    general.Identify.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
        nwk=0xC79E,
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_3(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha light platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                    lighting.Color.cluster_id,
                    general.Groups.cluster_id,
                    general.Identify.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE3,
        nwk=0xB89F,
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


def get_entity(zha_dev: ZHADevice, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]


def get_group_entity(group: Group, entity_id: str) -> GroupEntity | None:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in group.group_entities.values()
    }

    return entities.get(entity_id)


@pytest.mark.looptime
async def test_light_refresh(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
    zha_gateway: ZHAGateway,
):
    """Test zha light platform refresh."""
    zigpy_device = zigpy_device_mock(LIGHT_ON_OFF)
    on_off_cluster = zigpy_device.endpoints[1].on_off
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 0}
    zha_device = await device_joined(zigpy_device)

    entity_id = find_entity_id(Platform.LIGHT, zha_device)
    assert entity_id is not None

    entity = get_entity(zha_device, entity_id)
    assert entity is not None
    assert bool(entity.get_state()["on"]) is False

    on_off_cluster.read_attributes.reset_mock()

    # not enough time passed
    await asyncio.sleep(60)  # 1 minute
    await zha_gateway.async_block_till_done()
    assert on_off_cluster.read_attributes.call_count == 0
    assert on_off_cluster.read_attributes.await_count == 0
    assert bool(entity.get_state()["on"]) is False

    # 1 interval - at least 1 call
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 1}
    await asyncio.sleep(4800)  # 80 minutes
    await zha_gateway.async_block_till_done()
    assert on_off_cluster.read_attributes.call_count >= 1
    assert on_off_cluster.read_attributes.await_count >= 1
    assert bool(entity.get_state()["on"]) is True

    # 2 intervals - at least 2 calls
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 0}
    await asyncio.sleep(4800)  # 80 minutes
    await zha_gateway.async_block_till_done()
    assert on_off_cluster.read_attributes.call_count >= 2
    assert on_off_cluster.read_attributes.await_count >= 2
    assert bool(entity.get_state()["on"]) is False


@patch(
    "zigpy.zcl.clusters.lighting.Color.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zigpy.zcl.clusters.general.Identify.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zigpy.zcl.clusters.general.LevelControl.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zigpy.zcl.clusters.general.OnOff.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@pytest.mark.parametrize(
    "device, reporting",
    [(LIGHT_ON_OFF, (1, 0, 0)), (LIGHT_LEVEL, (1, 1, 0)), (LIGHT_COLOR, (1, 1, 3))],
)
@pytest.mark.looptime
async def test_light(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
    zha_gateway: ZHAGateway,
    device: dict,
    reporting: tuple,
) -> None:
    """Test zha light platform."""

    # create zigpy devices
    zigpy_device = zigpy_device_mock(device)
    cluster_color: lighting.Color = getattr(
        zigpy_device.endpoints[1], "light_color", None
    )
    if cluster_color:
        cluster_color.PLUGGED_ATTR_READS = {
            "color_temperature": 100,
            "color_temp_physical_min": 0,
            "color_temp_physical_max": 600,
            "color_capabilities": lighting.ColorCapabilities.XY_attributes
            | lighting.ColorCapabilities.Color_temperature,
        }
        update_attribute_cache(cluster_color)
    zha_device = await device_joined(zigpy_device)

    entity_id = find_entity_id(Platform.LIGHT, zha_device)
    assert entity_id is not None

    cluster_on_off: general.OnOff = zigpy_device.endpoints[1].on_off
    cluster_level: general.LevelControl = getattr(
        zigpy_device.endpoints[1], "level", None
    )
    cluster_identify: general.Identify = getattr(
        zigpy_device.endpoints[1], "identify", None
    )

    entity = get_entity(zha_device, entity_id)
    assert entity is not None

    assert bool(entity.get_state()["on"]) is False

    # test turning the lights on and off from the light
    await async_test_on_off_from_light(zha_gateway, cluster_on_off, entity)

    # test turning the lights on and off from the client
    await async_test_on_off_from_client(zha_gateway, cluster_on_off, entity)
    await _async_shift_time(zha_gateway)

    # test short flashing the lights from the client
    if cluster_identify:
        await async_test_flash_from_client(
            zha_gateway, cluster_identify, entity, FLASH_SHORT
        )
        await _async_shift_time(zha_gateway)

    # test turning the lights on and off from the client
    if cluster_level:
        await async_test_level_on_off_from_client(
            zha_gateway, cluster_on_off, cluster_level, entity
        )
        await _async_shift_time(zha_gateway)

        # test getting a brightness change from the network
        await async_test_on_from_light(zha_gateway, cluster_on_off, entity)
        await async_test_dimmer_from_light(
            zha_gateway, cluster_level, entity, 150, True
        )

    await async_test_off_from_client(zha_gateway, cluster_on_off, entity)
    await _async_shift_time(zha_gateway)

    # test long flashing the lights from the client
    if cluster_identify:
        await async_test_flash_from_client(
            zha_gateway, cluster_identify, entity, FLASH_LONG
        )
        await _async_shift_time(zha_gateway)
        await async_test_flash_from_client(
            zha_gateway, cluster_identify, entity, FLASH_SHORT
        )
        await _async_shift_time(zha_gateway)

    if cluster_color:
        # test color temperature from the client with transition
        assert entity.get_state()["brightness"] != 50
        assert entity.get_state()["color_temp"] != 200
        await entity.async_turn_on(brightness=50, transition=10, color_temp=200)
        await zha_gateway.async_block_till_done()
        assert entity.get_state()["brightness"] == 50
        assert entity.get_state()["color_temp"] == 200
        assert bool(entity.get_state()["on"]) is True
        assert cluster_color.request.call_count == 1
        assert cluster_color.request.await_count == 1
        assert cluster_color.request.call_args == call(
            False,
            10,
            cluster_color.commands_by_name["move_to_color_temp"].schema,
            color_temp_mireds=200,
            transition_time=100.0,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
        cluster_color.request.reset_mock()

        # test color xy from the client
        assert entity.get_state()["xy_color"] != [13369, 18087]
        await entity.async_turn_on(brightness=50, xy_color=[13369, 18087])
        await zha_gateway.async_block_till_done()
        assert entity.get_state()["brightness"] == 50
        assert entity.get_state()["xy_color"] == [13369, 18087]
        assert cluster_color.request.call_count == 1
        assert cluster_color.request.await_count == 1
        assert cluster_color.request.call_args == call(
            False,
            7,
            cluster_color.commands_by_name["move_to_color"].schema,
            color_x=876137415,
            color_y=1185331545,
            transition_time=0,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

        cluster_color.request.reset_mock()


async def async_test_on_off_from_light(
    zha_gateway: ZHAGateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test on off functionality from the light."""
    # turn on at light
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 3})
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True

    # turn off at light
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 3})
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is False


async def async_test_on_from_light(
    zha_gateway: ZHAGateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test on off functionality from the light."""
    # turn on at light
    await send_attributes_report(
        zha_gateway, cluster, {general.OnOff.AttributeDefs.on_off.id: 1}
    )
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True


async def async_test_on_off_from_client(
    zha_gateway: ZHAGateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test on off functionality from client."""
    # turn on via UI
    cluster.request.reset_mock()
    await entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True
    assert cluster.request.call_count == 1
    assert cluster.request.await_count == 1
    assert cluster.request.call_args == call(
        False,
        ON,
        cluster.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    await async_test_off_from_client(zha_gateway, cluster, entity)


async def async_test_off_from_client(
    zha_gateway: ZHAGateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test turning off the light from the client."""

    # turn off via UI
    cluster.request.reset_mock()
    await entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is False
    assert cluster.request.call_count == 1
    assert cluster.request.await_count == 1
    assert cluster.request.call_args == call(
        False,
        OFF,
        cluster.commands_by_name["off"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )


async def _async_shift_time(zha_gateway: ZHAGateway):
    """Shift time to cause call later tasks to run."""
    await asyncio.sleep(11)
    await zha_gateway.async_block_till_done()


@pytest.mark.looptime
async def async_test_level_on_off_from_client(
    zha_gateway: ZHAGateway,
    on_off_cluster: general.OnOff,
    level_cluster: general.LevelControl,
    entity: PlatformEntity | GroupEntity,
    expected_default_transition: int = 0,
) -> None:
    """Test on off functionality from client."""

    async def _reset_light():
        # reset the light
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        on_off_cluster.request.reset_mock()
        level_cluster.request.reset_mock()
        assert bool(entity.get_state()["on"]) is False

    await _reset_light()
    await _async_shift_time(zha_gateway)

    # turn on via UI
    await entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True
    assert on_off_cluster.request.call_count == 1
    assert on_off_cluster.request.await_count == 1
    assert level_cluster.request.call_count == 0
    assert level_cluster.request.await_count == 0
    assert on_off_cluster.request.call_args == call(
        False,
        ON,
        on_off_cluster.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    await _reset_light()
    await _async_shift_time(zha_gateway)

    await entity.async_turn_on(transition=10)
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True
    assert on_off_cluster.request.call_count == 0
    assert on_off_cluster.request.await_count == 0
    assert level_cluster.request.call_count == 1
    assert level_cluster.request.await_count == 1
    assert level_cluster.request.call_args == call(
        False,
        level_cluster.commands_by_name["move_to_level_with_on_off"].id,
        level_cluster.commands_by_name["move_to_level_with_on_off"].schema,
        level=254,
        transition_time=100,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    await _reset_light()

    await entity.async_turn_on(brightness=10)
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True
    # the onoff cluster is now not used when brightness is present by default
    assert on_off_cluster.request.call_count == 0
    assert on_off_cluster.request.await_count == 0
    assert level_cluster.request.call_count == 1
    assert level_cluster.request.await_count == 1
    assert level_cluster.request.call_args == call(
        False,
        level_cluster.commands_by_name["move_to_level_with_on_off"].id,
        level_cluster.commands_by_name["move_to_level_with_on_off"].schema,
        level=10,
        transition_time=int(expected_default_transition),
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    await _reset_light()

    await async_test_off_from_client(zha_gateway, on_off_cluster, entity)


async def async_test_dimmer_from_light(
    zha_gateway: ZHAGateway,
    cluster: general.LevelControl,
    entity: PlatformEntity | GroupEntity,
    level: int,
    expected_state: bool,
) -> None:
    """Test dimmer functionality from the light."""

    await send_attributes_report(
        zha_gateway, cluster, {1: level + 10, 0: level, 2: level - 10 or 22}
    )
    await zha_gateway.async_block_till_done()
    assert entity.get_state()["on"] == expected_state
    # hass uses None for brightness of 0 in state attributes
    if level == 0:
        assert entity.get_state()["brightness"] is None
    else:
        assert entity.get_state()["brightness"] == level


async def async_test_flash_from_client(
    zha_gateway: ZHAGateway,
    cluster: general.Identify,
    entity: PlatformEntity | GroupEntity,
    flash: str,
) -> None:
    """Test flash functionality from client."""
    # turn on via UI
    cluster.request.reset_mock()
    await entity.async_turn_on(flash=flash)
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True
    assert cluster.request.call_count == 1
    assert cluster.request.await_count == 1
    assert cluster.request.call_args == call(
        False,
        cluster.commands_by_name["trigger_effect"].id,
        cluster.commands_by_name["trigger_effect"].schema,
        effect_id=FLASH_EFFECTS[flash],
        effect_variant=general.Identify.EffectVariant.Default,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )


@patch(
    "zigpy.zcl.clusters.lighting.Color.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zigpy.zcl.clusters.general.Identify.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zigpy.zcl.clusters.general.LevelControl.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zigpy.zcl.clusters.general.OnOff.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@pytest.mark.looptime
async def test_zha_group_light_entity(
    device_light_1: ZHADevice,
    device_light_2: ZHADevice,
    device_light_3: ZHADevice,
    coordinator: ZHADevice,
    zha_gateway: ZHAGateway,
) -> None:
    """Test the light entity for a ZHA group."""

    member_ieee_addresses = [device_light_1.ieee, device_light_2.ieee]
    members = [
        GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
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

    entity_id = async_find_group_entity_id(Platform.LIGHT, zha_group)
    assert entity_id is not None

    entity: GroupEntity | None = get_group_entity(zha_group, entity_id)
    assert entity is not None

    assert isinstance(entity, GroupEntity)
    assert entity is not None

    device_1_entity_id = find_entity_id(Platform.LIGHT, device_light_1)
    assert device_1_entity_id is not None
    device_2_entity_id = find_entity_id(Platform.LIGHT, device_light_2)
    assert device_2_entity_id is not None
    device_3_entity_id = find_entity_id(Platform.LIGHT, device_light_3)
    assert device_3_entity_id is not None

    device_1_light_entity = get_entity(device_light_1, device_1_entity_id)
    assert device_1_light_entity is not None

    device_2_light_entity = get_entity(device_light_2, device_2_entity_id)
    assert device_2_light_entity is not None

    device_3_light_entity = get_entity(device_light_3, device_3_entity_id)
    assert device_3_light_entity is not None

    assert (
        device_1_entity_id != device_2_entity_id
        and device_1_entity_id != device_3_entity_id
    )
    assert device_2_entity_id != device_3_entity_id

    group_entity_id = async_find_group_entity_id(Platform.LIGHT, zha_group)
    assert group_entity_id is not None
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None

    assert device_1_light_entity.unique_id in zha_group.all_member_entity_unique_ids
    assert device_2_light_entity.unique_id in zha_group.all_member_entity_unique_ids
    assert device_3_light_entity.unique_id not in zha_group.all_member_entity_unique_ids

    group_cluster_on_off = zha_group.zigpy_group.endpoint[general.OnOff.cluster_id]
    group_cluster_level = zha_group.zigpy_group.endpoint[
        general.LevelControl.cluster_id
    ]
    group_cluster_identify = zha_group.zigpy_group.endpoint[general.Identify.cluster_id]
    assert group_cluster_identify is not None

    dev1_cluster_on_off = device_light_1.device.endpoints[1].on_off
    dev2_cluster_on_off = device_light_2.device.endpoints[1].on_off
    dev3_cluster_on_off = device_light_3.device.endpoints[1].on_off

    dev1_cluster_level = device_light_1.device.endpoints[1].level

    # test that the lights were created and are off
    assert bool(entity.get_state()["on"]) is False

    # test turning the lights on and off from the client
    await async_test_on_off_from_client(zha_gateway, group_cluster_on_off, entity)
    await _async_shift_time(zha_gateway)

    # test turning the lights on and off from the light
    await async_test_on_off_from_light(zha_gateway, dev1_cluster_on_off, entity)
    await _async_shift_time(zha_gateway)

    # test turning the lights on and off from the client
    await async_test_level_on_off_from_client(
        zha_gateway, group_cluster_on_off, group_cluster_level, entity
    )
    await _async_shift_time(zha_gateway)

    # test getting a brightness change from the network
    await async_test_on_from_light(zha_gateway, dev1_cluster_on_off, entity)
    await async_test_dimmer_from_light(
        zha_gateway, dev1_cluster_level, entity, 150, True
    )

    # test short flashing the lights from the client
    await async_test_flash_from_client(
        zha_gateway, group_cluster_identify, entity, FLASH_SHORT
    )
    await _async_shift_time(zha_gateway)
    # test long flashing the lights from the client
    await async_test_flash_from_client(
        zha_gateway, group_cluster_identify, entity, FLASH_LONG
    )
    await _async_shift_time(zha_gateway)

    assert len(zha_group.members) == 2
    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # test that group light is on
    assert device_1_light_entity.get_state()["on"] is True
    assert device_2_light_entity.get_state()["on"] is True
    assert bool(entity.get_state()["on"]) is True

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is still on
    assert device_1_light_entity.get_state()["on"] is False
    assert device_2_light_entity.get_state()["on"] is True
    assert bool(entity.get_state()["on"]) is True

    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is now off
    assert device_1_light_entity.get_state()["on"] is False
    assert device_2_light_entity.get_state()["on"] is False
    assert bool(entity.get_state()["on"]) is False

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # test that group light is now back on
    assert device_1_light_entity.get_state()["on"] is True
    assert device_2_light_entity.get_state()["on"] is False
    assert bool(entity.get_state()["on"]) is True

    # turn it off to test a new member add being tracked
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()
    assert device_1_light_entity.get_state()["on"] is False
    assert device_2_light_entity.get_state()["on"] is False
    assert bool(entity.get_state()["on"]) is False

    # add a new member and test that his state is also tracked
    await zha_group.async_add_members(
        [GroupMemberReference(ieee=device_light_3.ieee, endpoint_id=1)]
    )
    await zha_gateway.async_block_till_done()
    assert device_3_light_entity.unique_id in zha_group.all_member_entity_unique_ids
    assert len(zha_group.members) == 3
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None
    await send_attributes_report(zha_gateway, dev3_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    assert device_1_light_entity.get_state()["on"] is False
    assert device_2_light_entity.get_state()["on"] is False
    assert device_3_light_entity.get_state()["on"] is True
    assert bool(entity.get_state()["on"]) is True

    # make the group have only 1 member and now there should be no entity
    await zha_group.async_remove_members(
        [
            GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
            GroupMemberReference(ieee=device_light_3.ieee, endpoint_id=1),
        ]
    )
    await zha_gateway.async_block_till_done()
    assert len(zha_group.members) == 1
    assert device_2_light_entity.unique_id not in zha_group.all_member_entity_unique_ids
    assert device_3_light_entity.unique_id not in zha_group.all_member_entity_unique_ids
    # assert entity.unique_id not in group_proxy.group_model.entities

    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is None

    # add a member back and ensure that the group entity was created again
    await zha_group.async_add_members(
        [GroupMemberReference(ieee=device_light_3.ieee, endpoint_id=1)]
    )
    await zha_gateway.async_block_till_done()
    assert len(zha_group.members) == 2

    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None
    await send_attributes_report(zha_gateway, dev3_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True

    # add a 3rd member and ensure we still have an entity and we track the new member
    # First we turn the lights currently in the group off
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await send_attributes_report(zha_gateway, dev3_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is False

    # this will test that _reprobe_group is used correctly
    await zha_group.async_add_members(
        [
            GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
            GroupMemberReference(ieee=coordinator.ieee, endpoint_id=1),
        ]
    )
    await zha_gateway.async_block_till_done()
    assert len(zha_group.members) == 4
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None
    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["on"]) is True

    await zha_group.async_remove_members(
        [GroupMemberReference(ieee=coordinator.ieee, endpoint_id=1)]
    )
    await zha_gateway.async_block_till_done()
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None
    assert bool(entity.get_state()["on"]) is True
    assert len(zha_group.members) == 3

    # remove the group and ensure that there is no entity and that the entity registry is cleaned up
    await zha_gateway.async_remove_zigpy_group(zha_group.group_id)
    await zha_gateway.async_block_till_done()
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is None
