"""Test zha light."""

# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any
from unittest.mock import AsyncMock, call, patch, sentinel

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, lighting
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.const import (
    CONF_ALWAYS_PREFER_XY_COLOR_MODE,
    CONF_GROUP_MEMBERS_ASSUME_STATE,
    CUSTOM_CONFIGURATION,
    ZHA_OPTIONS,
)
from zha.application.gateway import Gateway
from zha.application.platforms import GroupEntity, PlatformEntity
from zha.application.platforms.light.const import (
    FLASH_EFFECTS,
    FLASH_LONG,
    FLASH_SHORT,
    ColorMode,
)
from zha.zigbee.device import Device
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
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
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
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
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
    color_cluster = zigpy_device.endpoints[1].light_color
    color_cluster.PLUGGED_ATTR_READS = {
        "color_capabilities": lighting.Color.ColorCapabilities.Color_temperature
        | lighting.Color.ColorCapabilities.XY_attributes
    }
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_2(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
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
        manufacturer="sengled",
        nwk=0xC79E,
    )
    color_cluster = zigpy_device.endpoints[1].light_color
    color_cluster.PLUGGED_ATTR_READS = {
        "color_capabilities": lighting.Color.ColorCapabilities.Color_temperature
        | lighting.Color.ColorCapabilities.XY_attributes
    }
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_3(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
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


@pytest.fixture
async def eWeLink_light(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
):
    """Mock eWeLink light."""

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
        ieee="03:2d:6f:00:0a:90:69:e3",
        manufacturer="eWeLink",
        nwk=0xB79D,
    )
    color_cluster = zigpy_device.endpoints[1].light_color
    color_cluster.PLUGGED_ATTR_READS = {
        "color_capabilities": lighting.Color.ColorCapabilities.Color_temperature
        | lighting.Color.ColorCapabilities.XY_attributes,
        "color_temp_physical_min": 0,
        "color_temp_physical_max": 0,
    }
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


def get_entity(zha_dev: Device, entity_id: str) -> PlatformEntity:
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
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,
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
    assert bool(entity.state["on"]) is False

    on_off_cluster.read_attributes.reset_mock()

    # not enough time passed
    await asyncio.sleep(60)  # 1 minute
    await zha_gateway.async_block_till_done()
    assert on_off_cluster.read_attributes.call_count == 0
    assert on_off_cluster.read_attributes.await_count == 0
    assert bool(entity.state["on"]) is False

    # 1 interval - at least 1 call
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 1}
    await asyncio.sleep(4800)  # 80 minutes
    await zha_gateway.async_block_till_done()
    assert on_off_cluster.read_attributes.call_count >= 1
    assert on_off_cluster.read_attributes.await_count >= 1
    assert bool(entity.state["on"]) is True

    # 2 intervals - at least 2 calls
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 0}
    await asyncio.sleep(4800)  # 80 minutes
    await zha_gateway.async_block_till_done()
    assert on_off_cluster.read_attributes.call_count >= 2
    assert on_off_cluster.read_attributes.await_count >= 2
    assert bool(entity.state["on"]) is False


# TODO reporting is not checked
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
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,
    device: dict,
    reporting: tuple,  # pylint: disable=unused-argument
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

    assert bool(entity.state["on"]) is False

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
        assert entity.state["brightness"] != 50
        assert entity.state["color_temp"] != 200
        await entity.async_turn_on(brightness=50, transition=10, color_temp=200)
        await zha_gateway.async_block_till_done()
        assert entity.state["brightness"] == 50
        assert entity.state["color_temp"] == 200
        assert bool(entity.state["on"]) is True
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
        assert entity.state["xy_color"] != [13369, 18087]
        await entity.async_turn_on(brightness=50, xy_color=[13369, 18087])
        await zha_gateway.async_block_till_done()
        assert entity.state["brightness"] == 50
        assert entity.state["xy_color"] == [13369, 18087]
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
    zha_gateway: Gateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test on off functionality from the light."""
    # turn on at light
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 3})
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is True

    # turn off at light
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 3})
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is False


async def async_test_on_from_light(
    zha_gateway: Gateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test on off functionality from the light."""
    # turn on at light
    await send_attributes_report(
        zha_gateway, cluster, {general.OnOff.AttributeDefs.on_off.id: 1}
    )
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is True


async def async_test_on_off_from_client(
    zha_gateway: Gateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test on off functionality from client."""
    # turn on via UI
    cluster.request.reset_mock()
    await entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is True
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
    zha_gateway: Gateway,
    cluster: general.OnOff,
    entity: PlatformEntity | GroupEntity,
) -> None:
    """Test turning off the light from the client."""

    # turn off via UI
    cluster.request.reset_mock()
    await entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is False
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


async def _async_shift_time(zha_gateway: Gateway):
    """Shift time to cause call later tasks to run."""
    await asyncio.sleep(11)
    await zha_gateway.async_block_till_done()


@pytest.mark.looptime
async def async_test_level_on_off_from_client(
    zha_gateway: Gateway,
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
        assert bool(entity.state["on"]) is False

    await _reset_light()
    await _async_shift_time(zha_gateway)

    # turn on via UI
    await entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is True
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
    assert bool(entity.state["on"]) is True
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
    assert bool(entity.state["on"]) is True
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
    zha_gateway: Gateway,
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
    assert entity.state["on"] == expected_state
    # hass uses None for brightness of 0 in state attributes
    if level == 0:
        assert entity.state["brightness"] is None
    else:
        assert entity.state["brightness"] == level


async def async_test_flash_from_client(
    zha_gateway: Gateway,
    cluster: general.Identify,
    entity: PlatformEntity | GroupEntity,
    flash: str,
) -> None:
    """Test flash functionality from client."""
    # turn on via UI
    cluster.request.reset_mock()
    await entity.async_turn_on(flash=flash)
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is True
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
    device_light_1: Device,  # pylint: disable=redefined-outer-name
    device_light_2: Device,  # pylint: disable=redefined-outer-name
    device_light_3: Device,  # pylint: disable=redefined-outer-name
    coordinator: Device,  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
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
    assert entity.group_id == zha_group.group_id

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

    assert device_1_entity_id not in (device_2_entity_id, device_3_entity_id)
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
    assert bool(entity.state["on"]) is False

    # test turning the lights on and off from the client
    await async_test_on_off_from_client(zha_gateway, group_cluster_on_off, entity)
    await _async_shift_time(zha_gateway)

    # test turning the lights on and off from the light
    await async_test_on_off_from_light(zha_gateway, dev1_cluster_on_off, entity)
    await _async_shift_time(zha_gateway)

    # test turning the lights on and off from the client
    await async_test_level_on_off_from_client(
        zha_gateway,
        group_cluster_on_off,
        group_cluster_level,
        entity,
        expected_default_transition=1,
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
    assert device_1_light_entity.state["on"] is True
    assert device_2_light_entity.state["on"] is True
    assert bool(entity.state["on"]) is True

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is still on
    assert device_1_light_entity.state["on"] is False
    assert device_2_light_entity.state["on"] is True
    assert bool(entity.state["on"]) is True

    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is now off
    assert device_1_light_entity.state["on"] is False
    assert device_2_light_entity.state["on"] is False
    assert bool(entity.state["on"]) is False

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # test that group light is now back on
    assert device_1_light_entity.state["on"] is True
    assert device_2_light_entity.state["on"] is False
    assert bool(entity.state["on"]) is True

    # turn it off to test a new member add being tracked
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()
    assert device_1_light_entity.state["on"] is False
    assert device_2_light_entity.state["on"] is False
    assert bool(entity.state["on"]) is False

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

    assert device_1_light_entity.state["on"] is False
    assert device_2_light_entity.state["on"] is False
    assert device_3_light_entity.state["on"] is True
    assert bool(entity.state["on"]) is True

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
    assert bool(entity.state["on"]) is True

    # add a 3rd member and ensure we still have an entity and we track the new member
    # First we turn the lights currently in the group off
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await send_attributes_report(zha_gateway, dev3_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()
    assert bool(entity.state["on"]) is False

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
    assert bool(entity.state["on"]) is True

    await zha_group.async_remove_members(
        [GroupMemberReference(ieee=coordinator.ieee, endpoint_id=1)]
    )
    await zha_gateway.async_block_till_done()
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None
    assert bool(entity.state["on"]) is True
    assert len(zha_group.members) == 3

    # remove the group and ensure that there is no entity and that the entity registry is cleaned up
    await zha_gateway.async_remove_zigpy_group(zha_group.group_id)
    await zha_gateway.async_block_till_done()
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is None


@pytest.mark.parametrize(
    ("plugged_attr_reads", "config_override", "expected_state"),
    [
        # HS light without cached hue or saturation
        (
            {
                "color_capabilities": (
                    lighting.Color.ColorCapabilities.Hue_and_saturation
                ),
            },
            {CONF_ALWAYS_PREFER_XY_COLOR_MODE: False},
            {},
        ),
        # HS light with cached hue
        (
            {
                "color_capabilities": (
                    lighting.Color.ColorCapabilities.Hue_and_saturation
                ),
                "current_hue": 100,
            },
            {CONF_ALWAYS_PREFER_XY_COLOR_MODE: False},
            {},
        ),
        # HS light with cached saturation
        (
            {
                "color_capabilities": (
                    lighting.Color.ColorCapabilities.Hue_and_saturation
                ),
                "current_saturation": 100,
            },
            {CONF_ALWAYS_PREFER_XY_COLOR_MODE: False},
            {},
        ),
        # HS light with both
        (
            {
                "color_capabilities": (
                    lighting.Color.ColorCapabilities.Hue_and_saturation
                ),
                "current_hue": 100,
                "current_saturation": 100,
            },
            {CONF_ALWAYS_PREFER_XY_COLOR_MODE: False},
            {},
        ),
    ],
)
# TODO expected_state is not used
async def test_light_initialization(
    zha_gateway: Gateway,
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    plugged_attr_reads: dict[str, Any],
    config_override: dict[str, Any],
    expected_state: dict[str, Any],  # pylint: disable=unused-argument
) -> None:
    """Test ZHA light initialization with cached attributes and color modes."""

    # create zigpy devices
    zigpy_device = zigpy_device_mock(LIGHT_COLOR)

    # mock attribute reads
    zigpy_device.endpoints[1].light_color.PLUGGED_ATTR_READS = plugged_attr_reads

    for key in config_override:
        zha_gateway.config.config_entry_data["options"][CUSTOM_CONFIGURATION][
            ZHA_OPTIONS
        ][key] = config_override[key]
    zha_device = await device_joined(zigpy_device)
    entity_id = find_entity_id(Platform.LIGHT, zha_device)
    assert entity_id is not None

    # TODO ensure hue and saturation are properly set on startup


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
async def test_transitions(
    zha_gateway: Gateway,
    device_light_1,  # pylint: disable=redefined-outer-name
    device_light_2,  # pylint: disable=redefined-outer-name
    eWeLink_light,  # pylint: disable=redefined-outer-name
) -> None:
    """Test ZHA light transition code."""

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
    assert entity.group_id == zha_group.group_id

    device_1_entity_id = find_entity_id(Platform.LIGHT, device_light_1)
    assert device_1_entity_id is not None
    device_2_entity_id = find_entity_id(Platform.LIGHT, device_light_2)
    assert device_2_entity_id is not None
    device_3_entity_id = find_entity_id(Platform.LIGHT, eWeLink_light)
    assert device_3_entity_id is not None

    device_1_light_entity = get_entity(device_light_1, device_1_entity_id)
    assert device_1_light_entity is not None

    device_2_light_entity = get_entity(device_light_2, device_2_entity_id)
    assert device_2_light_entity is not None

    eWeLink_light_entity = get_entity(eWeLink_light, device_3_entity_id)
    assert eWeLink_light_entity is not None

    assert device_1_entity_id not in (device_2_entity_id, device_3_entity_id)
    assert device_2_entity_id != device_3_entity_id

    group_entity_id = async_find_group_entity_id(Platform.LIGHT, zha_group)
    assert group_entity_id is not None
    entity = get_group_entity(zha_group, group_entity_id)
    assert entity is not None

    assert device_1_light_entity.unique_id in zha_group.all_member_entity_unique_ids
    assert device_2_light_entity.unique_id in zha_group.all_member_entity_unique_ids
    assert eWeLink_light_entity.unique_id not in zha_group.all_member_entity_unique_ids

    dev1_cluster_on_off = device_light_1.device.endpoints[1].on_off
    dev2_cluster_on_off = device_light_2.device.endpoints[1].on_off
    eWeLink_cluster_on_off = eWeLink_light.device.endpoints[1].on_off

    dev1_cluster_level = device_light_1.device.endpoints[1].level
    dev2_cluster_level = device_light_2.device.endpoints[1].level
    eWeLink_cluster_level = eWeLink_light.device.endpoints[1].level

    dev1_cluster_color = device_light_1.device.endpoints[1].light_color
    dev2_cluster_color = device_light_2.device.endpoints[1].light_color
    eWeLink_cluster_color = eWeLink_light.device.endpoints[1].light_color

    # test that the lights were created and are off
    assert bool(entity.state["on"]) is False
    assert bool(device_1_light_entity.state["on"]) is False
    assert bool(device_2_light_entity.state["on"]) is False

    # first test 0 length transition with no color and no brightness provided
    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_level.request.reset_mock()
    await device_1_light_entity.async_turn_on(transition=0)
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 0
    assert dev1_cluster_color.request.await_count == 0
    assert dev1_cluster_level.request.call_count == 1
    assert dev1_cluster_level.request.await_count == 1
    assert dev1_cluster_level.request.call_args == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=254,  # default "full on" brightness
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is True
    assert device_1_light_entity.state["brightness"] == 254

    # test 0 length transition with no color and no brightness provided again, but for "force on" lights
    eWeLink_cluster_on_off.request.reset_mock()
    eWeLink_cluster_level.request.reset_mock()

    await eWeLink_light_entity.async_turn_on(transition=0)
    await zha_gateway.async_block_till_done()
    assert eWeLink_cluster_on_off.request.call_count == 1
    assert eWeLink_cluster_on_off.request.await_count == 1
    assert eWeLink_cluster_on_off.request.call_args_list[0] == call(
        False,
        eWeLink_cluster_on_off.commands_by_name["on"].id,
        eWeLink_cluster_on_off.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert eWeLink_cluster_color.request.call_count == 0
    assert eWeLink_cluster_color.request.await_count == 0
    assert eWeLink_cluster_level.request.call_count == 1
    assert eWeLink_cluster_level.request.await_count == 1
    assert eWeLink_cluster_level.request.call_args == call(
        False,
        eWeLink_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        eWeLink_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=254,  # default "full on" brightness
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(eWeLink_light_entity.state["on"]) is True
    assert eWeLink_light_entity.state["brightness"] == 254

    eWeLink_cluster_on_off.request.reset_mock()
    eWeLink_cluster_level.request.reset_mock()

    # test 0 length transition with brightness, but no color provided
    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_level.request.reset_mock()
    await device_1_light_entity.async_turn_on(transition=0, brightness=50)
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 0
    assert dev1_cluster_color.request.await_count == 0
    assert dev1_cluster_level.request.call_count == 1
    assert dev1_cluster_level.request.await_count == 1
    assert dev1_cluster_level.request.call_args == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=50,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is True
    assert device_1_light_entity.state["brightness"] == 50

    dev1_cluster_level.request.reset_mock()

    # test non 0 length transition with color provided while light is on
    await device_1_light_entity.async_turn_on(
        transition=3.5, brightness=18, color_temp=432
    )
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 1
    assert dev1_cluster_color.request.await_count == 1
    assert dev1_cluster_level.request.call_count == 1
    assert dev1_cluster_level.request.await_count == 1
    assert dev1_cluster_level.request.call_args == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=18,
        transition_time=35,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_color.request.call_args == call(
        False,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=432,
        transition_time=35,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is True
    assert device_1_light_entity.state["brightness"] == 18
    assert device_1_light_entity.state["color_temp"] == 432
    assert device_1_light_entity.state["color_mode"] == ColorMode.COLOR_TEMP

    dev1_cluster_level.request.reset_mock()
    dev1_cluster_color.request.reset_mock()

    # test 0 length transition to turn light off
    await device_1_light_entity.async_turn_off(transition=0)
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 0
    assert dev1_cluster_color.request.await_count == 0
    assert dev1_cluster_level.request.call_count == 1
    assert dev1_cluster_level.request.await_count == 1
    assert dev1_cluster_level.request.call_args == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=0,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is False

    dev1_cluster_level.request.reset_mock()

    # test non 0 length transition and color temp while turning light on (new_color_provided_while_off)
    await device_1_light_entity.async_turn_on(
        transition=1, brightness=25, color_temp=235
    )
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 1
    assert dev1_cluster_color.request.await_count == 1
    assert dev1_cluster_level.request.call_count == 2
    assert dev1_cluster_level.request.await_count == 2

    # first it comes on with no transition at 2 brightness
    assert dev1_cluster_level.request.call_args_list[0] == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=2,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_color.request.call_args == call(
        False,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=235,
        transition_time=0,  # no transition when new_color_provided_while_off
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_level.request.call_args_list[1] == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level"].id,
        dev1_cluster_level.commands_by_name["move_to_level"].schema,
        level=25,
        transition_time=10,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is True
    assert device_1_light_entity.state["brightness"] == 25
    assert device_1_light_entity.state["color_temp"] == 235
    assert device_1_light_entity.state["color_mode"] == ColorMode.COLOR_TEMP

    dev1_cluster_level.request.reset_mock()
    dev1_cluster_color.request.reset_mock()

    # turn light 1 back off
    await device_1_light_entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 1
    assert dev1_cluster_on_off.request.await_count == 1
    assert dev1_cluster_color.request.call_count == 0
    assert dev1_cluster_color.request.await_count == 0
    assert dev1_cluster_level.request.call_count == 0
    assert dev1_cluster_level.request.await_count == 0

    assert bool(entity.state["on"]) is False

    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_color.request.reset_mock()
    dev1_cluster_level.request.reset_mock()

    # test no transition provided and color temp while turning light on (new_color_provided_while_off)
    await device_1_light_entity.async_turn_on(brightness=25, color_temp=236)
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 1
    assert dev1_cluster_color.request.await_count == 1
    assert dev1_cluster_level.request.call_count == 2
    assert dev1_cluster_level.request.await_count == 2

    # first it comes on with no transition at 2 brightness
    assert dev1_cluster_level.request.call_args_list[0] == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=2,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_color.request.call_args == call(
        False,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=236,
        transition_time=0,  # no transition when new_color_provided_while_off
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_level.request.call_args_list[1] == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level"].id,
        dev1_cluster_level.commands_by_name["move_to_level"].schema,
        level=25,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is True
    assert device_1_light_entity.state["brightness"] == 25
    assert device_1_light_entity.state["color_temp"] == 236
    assert device_1_light_entity.state["color_mode"] == ColorMode.COLOR_TEMP

    dev1_cluster_level.request.reset_mock()
    dev1_cluster_color.request.reset_mock()

    # turn light 1 back off to setup group test
    await device_1_light_entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 1
    assert dev1_cluster_on_off.request.await_count == 1
    assert dev1_cluster_color.request.call_count == 0
    assert dev1_cluster_color.request.await_count == 0
    assert dev1_cluster_level.request.call_count == 0
    assert dev1_cluster_level.request.await_count == 0
    assert bool(entity.state["on"]) is False

    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_color.request.reset_mock()
    dev1_cluster_level.request.reset_mock()

    # test no transition when the same color temp is provided from off
    await device_1_light_entity.async_turn_on(color_temp=236)
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 1
    assert dev1_cluster_on_off.request.await_count == 1
    assert dev1_cluster_color.request.call_count == 1
    assert dev1_cluster_color.request.await_count == 1
    assert dev1_cluster_level.request.call_count == 0
    assert dev1_cluster_level.request.await_count == 0

    assert dev1_cluster_on_off.request.call_args == call(
        False,
        dev1_cluster_on_off.commands_by_name["on"].id,
        dev1_cluster_on_off.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert dev1_cluster_color.request.call_args == call(
        False,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=236,
        transition_time=0,  # no transition when new_color_provided_while_off
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_1_light_entity.state["on"]) is True
    assert device_1_light_entity.state["brightness"] == 25
    assert device_1_light_entity.state["color_temp"] == 236
    assert device_1_light_entity.state["color_mode"] == ColorMode.COLOR_TEMP

    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_color.request.reset_mock()

    # turn light 1 back off to setup group test
    await device_1_light_entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert dev1_cluster_on_off.request.call_count == 1
    assert dev1_cluster_on_off.request.await_count == 1
    assert dev1_cluster_color.request.call_count == 0
    assert dev1_cluster_color.request.await_count == 0
    assert dev1_cluster_level.request.call_count == 0
    assert dev1_cluster_level.request.await_count == 0
    assert bool(entity.state["on"]) is False

    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_color.request.reset_mock()
    dev1_cluster_level.request.reset_mock()

    # test sengled light uses default minimum transition time
    dev2_cluster_on_off.request.reset_mock()
    dev2_cluster_color.request.reset_mock()
    dev2_cluster_level.request.reset_mock()

    await device_2_light_entity.async_turn_on(transition=0, brightness=100)
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 0
    assert dev2_cluster_on_off.request.await_count == 0
    assert dev2_cluster_color.request.call_count == 0
    assert dev2_cluster_color.request.await_count == 0
    assert dev2_cluster_level.request.call_count == 1
    assert dev2_cluster_level.request.await_count == 1
    assert dev2_cluster_level.request.call_args == call(
        False,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=100,
        transition_time=1,  # transition time - sengled light uses default minimum
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_2_light_entity.state["on"]) is True
    assert device_2_light_entity.state["brightness"] == 100

    dev2_cluster_level.request.reset_mock()

    # turn the sengled light back off
    await device_2_light_entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 1
    assert dev2_cluster_on_off.request.await_count == 1
    assert dev2_cluster_color.request.call_count == 0
    assert dev2_cluster_color.request.await_count == 0
    assert dev2_cluster_level.request.call_count == 0
    assert dev2_cluster_level.request.await_count == 0
    assert bool(device_2_light_entity.state["on"]) is False

    dev2_cluster_on_off.request.reset_mock()

    # test non 0 length transition and color temp while turning light on and sengled (new_color_provided_while_off)
    await device_2_light_entity.async_turn_on(
        transition=1, brightness=25, color_temp=235
    )
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 0
    assert dev2_cluster_on_off.request.await_count == 0
    assert dev2_cluster_color.request.call_count == 1
    assert dev2_cluster_color.request.await_count == 1
    assert dev2_cluster_level.request.call_count == 2
    assert dev2_cluster_level.request.await_count == 2

    # first it comes on with no transition at 2 brightness
    assert dev2_cluster_level.request.call_args_list[0] == call(
        False,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=2,
        transition_time=1,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev2_cluster_color.request.call_args == call(
        False,
        dev2_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev2_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=235,
        transition_time=1,  # sengled transition == 1 when new_color_provided_while_off
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev2_cluster_level.request.call_args_list[1] == call(
        False,
        dev2_cluster_level.commands_by_name["move_to_level"].id,
        dev2_cluster_level.commands_by_name["move_to_level"].schema,
        level=25,
        transition_time=10,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_2_light_entity.state["on"]) is True
    assert device_2_light_entity.state["brightness"] == 25
    assert device_2_light_entity.state["color_temp"] == 235
    assert device_2_light_entity.state["color_mode"] == ColorMode.COLOR_TEMP

    dev2_cluster_level.request.reset_mock()
    dev2_cluster_color.request.reset_mock()

    # turn the sengled light back off
    await device_2_light_entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 1
    assert dev2_cluster_on_off.request.await_count == 1
    assert dev2_cluster_color.request.call_count == 0
    assert dev2_cluster_color.request.await_count == 0
    assert dev2_cluster_level.request.call_count == 0
    assert dev2_cluster_level.request.await_count == 0
    assert bool(device_2_light_entity.state["on"]) is False

    dev2_cluster_on_off.request.reset_mock()

    # test non 0 length transition and color temp while turning group light on (new_color_provided_while_off)
    await entity.async_turn_on(transition=1, brightness=25, color_temp=235)
    await zha_gateway.async_block_till_done()

    group_on_off_cluster_handler = zha_group.endpoint[general.OnOff.cluster_id]
    group_level_cluster_handler = zha_group.endpoint[general.LevelControl.cluster_id]
    group_color_cluster_handler = zha_group.endpoint[lighting.Color.cluster_id]
    assert group_on_off_cluster_handler.request.call_count == 0
    assert group_on_off_cluster_handler.request.await_count == 0
    assert group_color_cluster_handler.request.call_count == 1
    assert group_color_cluster_handler.request.await_count == 1
    assert group_level_cluster_handler.request.call_count == 1
    assert group_level_cluster_handler.request.await_count == 1

    # groups are omitted from the 3 call dance for new_color_provided_while_off
    assert group_color_cluster_handler.request.call_args == call(
        False,
        dev2_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev2_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=235,
        transition_time=10,  # sengled transition == 1 when new_color_provided_while_off
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert group_level_cluster_handler.request.call_args == call(
        False,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=25,
        transition_time=10,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(entity.state["on"]) is True
    assert entity.state["brightness"] == 25
    assert entity.state["color_temp"] == 235
    assert entity.state["color_mode"] == ColorMode.COLOR_TEMP

    group_on_off_cluster_handler.request.reset_mock()
    group_color_cluster_handler.request.reset_mock()
    group_level_cluster_handler.request.reset_mock()

    # turn the sengled light back on
    await device_2_light_entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 1
    assert dev2_cluster_on_off.request.await_count == 1
    assert dev2_cluster_color.request.call_count == 0
    assert dev2_cluster_color.request.await_count == 0
    assert dev2_cluster_level.request.call_count == 0
    assert dev2_cluster_level.request.await_count == 0
    assert bool(device_2_light_entity.state["on"]) is True

    dev2_cluster_on_off.request.reset_mock()

    # turn the light off with a transition
    await device_2_light_entity.async_turn_off(transition=2)
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 0
    assert dev2_cluster_on_off.request.await_count == 0
    assert dev2_cluster_color.request.call_count == 0
    assert dev2_cluster_color.request.await_count == 0
    assert dev2_cluster_level.request.call_count == 1
    assert dev2_cluster_level.request.await_count == 1
    assert dev2_cluster_level.request.call_args == call(
        False,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=0,
        transition_time=20,  # transition time
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_2_light_entity.state["on"]) is False

    dev2_cluster_level.request.reset_mock()

    # turn the light back on with no args should use a transition and last known brightness
    await device_2_light_entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert dev2_cluster_on_off.request.call_count == 0
    assert dev2_cluster_on_off.request.await_count == 0
    assert dev2_cluster_color.request.call_count == 0
    assert dev2_cluster_color.request.await_count == 0
    assert dev2_cluster_level.request.call_count == 1
    assert dev2_cluster_level.request.await_count == 1
    assert dev2_cluster_level.request.call_args == call(
        False,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev2_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=25,
        transition_time=1,  # transition time - sengled light uses default minimum
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(device_2_light_entity.state["on"]) is True

    dev2_cluster_level.request.reset_mock()
    eWeLink_cluster_on_off.request.reset_mock()
    eWeLink_cluster_level.request.reset_mock()
    eWeLink_cluster_color.request.reset_mock()

    # test eWeLink color temp while turning light on from off (new_color_provided_while_off)
    await eWeLink_light_entity.async_turn_on(color_temp=235)
    await zha_gateway.async_block_till_done()
    assert eWeLink_cluster_on_off.request.call_count == 1
    assert eWeLink_cluster_on_off.request.await_count == 1
    assert eWeLink_cluster_color.request.call_count == 1
    assert eWeLink_cluster_color.request.await_count == 1
    assert eWeLink_cluster_level.request.call_count == 0
    assert eWeLink_cluster_level.request.await_count == 0

    # first it comes on
    assert eWeLink_cluster_on_off.request.call_args_list[0] == call(
        False,
        eWeLink_cluster_on_off.commands_by_name["on"].id,
        eWeLink_cluster_on_off.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert eWeLink_cluster_color.request.call_args == call(
        False,
        eWeLink_cluster_color.commands_by_name["move_to_color_temp"].id,
        eWeLink_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=235,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(eWeLink_light_entity.state["on"]) is True
    assert eWeLink_light_entity.state["color_temp"] == 235
    assert eWeLink_light_entity.state["color_mode"] == ColorMode.COLOR_TEMP
    assert eWeLink_light_entity.min_mireds == 153
    assert eWeLink_light_entity.max_mireds == 500


@patch(
    "zigpy.zcl.clusters.lighting.Color.request",
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
async def test_on_with_off_color(
    zha_gateway: Gateway,
    device_light_1,  # pylint: disable=redefined-outer-name
) -> None:
    """Test turning on the light and sending color commands before on/level commands for supporting lights."""

    device_1_entity_id = find_entity_id(Platform.LIGHT, device_light_1)
    dev1_cluster_on_off = device_light_1.device.endpoints[1].on_off
    dev1_cluster_level = device_light_1.device.endpoints[1].level
    dev1_cluster_color = device_light_1.device.endpoints[1].light_color

    entity = get_entity(device_light_1, device_1_entity_id)
    assert entity is not None

    # Execute_if_off will override the "enhanced turn on from an off-state" config option that's enabled here
    dev1_cluster_color.PLUGGED_ATTR_READS = {
        "options": lighting.Color.Options.Execute_if_off
    }
    update_attribute_cache(dev1_cluster_color)

    # turn on via UI
    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_level.request.reset_mock()
    dev1_cluster_color.request.reset_mock()

    await entity.async_turn_on(color_temp=235)

    assert dev1_cluster_on_off.request.call_count == 1
    assert dev1_cluster_on_off.request.await_count == 1
    assert dev1_cluster_color.request.call_count == 1
    assert dev1_cluster_color.request.await_count == 1
    assert dev1_cluster_level.request.call_count == 0
    assert dev1_cluster_level.request.await_count == 0

    assert dev1_cluster_on_off.request.call_args_list[0] == call(
        False,
        dev1_cluster_on_off.commands_by_name["on"].id,
        dev1_cluster_on_off.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_color.request.call_args == call(
        False,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=235,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(entity.state["on"]) is True
    assert entity.state["color_temp"] == 235
    assert entity.state["color_mode"] == ColorMode.COLOR_TEMP

    # now let's turn off the Execute_if_off option and see if the old behavior is restored
    dev1_cluster_color.PLUGGED_ATTR_READS = {"options": 0}
    update_attribute_cache(dev1_cluster_color)

    # turn off via UI, so the old "enhanced turn on from an off-state" behavior can do something
    await async_test_off_from_client(zha_gateway, dev1_cluster_on_off, entity)

    # turn on via UI (with a different color temp, so the "enhanced turn on" does something)
    dev1_cluster_on_off.request.reset_mock()
    dev1_cluster_level.request.reset_mock()
    dev1_cluster_color.request.reset_mock()

    await entity.async_turn_on(color_temp=240)

    assert dev1_cluster_on_off.request.call_count == 0
    assert dev1_cluster_on_off.request.await_count == 0
    assert dev1_cluster_color.request.call_count == 1
    assert dev1_cluster_color.request.await_count == 1
    assert dev1_cluster_level.request.call_count == 2
    assert dev1_cluster_level.request.await_count == 2

    # first it comes on with no transition at 2 brightness
    assert dev1_cluster_level.request.call_args_list[0] == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].id,
        dev1_cluster_level.commands_by_name["move_to_level_with_on_off"].schema,
        level=2,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_color.request.call_args == call(
        False,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].id,
        dev1_cluster_color.commands_by_name["move_to_color_temp"].schema,
        color_temp_mireds=240,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )
    assert dev1_cluster_level.request.call_args_list[1] == call(
        False,
        dev1_cluster_level.commands_by_name["move_to_level"].id,
        dev1_cluster_level.commands_by_name["move_to_level"].schema,
        level=254,
        transition_time=0,
        expect_reply=True,
        manufacturer=None,
        tsn=None,
    )

    assert bool(entity.state["on"]) is True
    assert entity.state["color_temp"] == 240
    assert entity.state["brightness"] == 254
    assert entity.state["color_mode"] == ColorMode.COLOR_TEMP


@patch(
    "zigpy.zcl.clusters.general.OnOff.request",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
@patch(
    "zha.application.platforms.light.const.ASSUME_UPDATE_GROUP_FROM_CHILD_DELAY",
    new=0,
)
@pytest.mark.looptime
async def test_group_member_assume_state(
    zha_gateway: Gateway,
    coordinator,  # pylint: disable=redefined-outer-name
    device_light_1,  # pylint: disable=redefined-outer-name
    device_light_2,  # pylint: disable=redefined-outer-name
) -> None:
    """Test the group members assume state function."""

    zha_gateway.config.config_entry_data["options"][CUSTOM_CONFIGURATION][ZHA_OPTIONS][
        CONF_GROUP_MEMBERS_ASSUME_STATE
    ] = True

    zha_gateway.coordinator_zha_device = coordinator
    coordinator._zha_gateway = zha_gateway
    device_light_1._zha_gateway = zha_gateway
    device_light_2._zha_gateway = zha_gateway

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
    assert entity.group_id == zha_group.group_id

    device_1_entity_id = find_entity_id(Platform.LIGHT, device_light_1)
    device_2_entity_id = find_entity_id(Platform.LIGHT, device_light_2)

    assert device_1_entity_id != device_2_entity_id

    device_1_light_entity = get_entity(device_light_1, device_1_entity_id)
    device_2_light_entity = get_entity(device_light_2, device_2_entity_id)

    assert device_1_light_entity is not None
    assert device_2_light_entity is not None

    group_cluster_on_off = zha_group.endpoint[general.OnOff.cluster_id]

    # test that the lights were created and are off
    assert bool(entity.state["on"]) is False

    group_cluster_on_off.request.reset_mock()
    await asyncio.sleep(11)

    # turn on via UI
    await entity.async_turn_on()
    await zha_gateway.async_block_till_done()

    # members also instantly assume STATE_ON
    assert bool(device_1_light_entity.state["on"]) is True
    assert bool(device_2_light_entity.state["on"]) is True
    assert bool(entity.state["on"]) is True

    # turn off via UI
    await entity.async_turn_off()
    await zha_gateway.async_block_till_done()

    # members also instantly assume STATE_OFF
    assert bool(device_1_light_entity.state["on"]) is False
    assert bool(device_2_light_entity.state["on"]) is False
    assert bool(entity.state["on"]) is False
