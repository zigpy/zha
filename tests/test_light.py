"""Test zha light."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from unittest.mock import AsyncMock, call, patch, sentinel

from pydantic import ValidationError
import pytest
from slugify import slugify
from zhaws.client.controller import Controller
from zhaws.client.model.types import LightEntity, LightGroupEntity
from zhaws.client.proxy import DeviceProxy, GroupProxy
from zhaws.server.platforms.light import FLASH_EFFECTS, FLASH_LONG, FLASH_SHORT
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.cluster.lighting import ColorClusterHandler
from zhaws.server.zigbee.device import Device
from zhaws.server.zigbee.group import Group, GroupMemberReference
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, lighting
import zigpy.zcl.foundation as zcl_f

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
        nwk=0xC79E,
    )
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


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> LightEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]  # type: ignore


def get_group_entity(
    group_proxy: GroupProxy, entity_id: str
) -> LightGroupEntity | None:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in group_proxy.group_model.entities.values()
    }

    return entities.get(entity_id)  # type: ignore


@pytest.mark.looptime
async def test_light_refresh(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
):
    """Test zha light platform refresh."""
    zigpy_device = zigpy_device_mock(LIGHT_ON_OFF)
    on_off_cluster = zigpy_device.endpoints[1].on_off
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 0}
    zha_device = await device_joined(zigpy_device)
    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.LIGHT, zha_device)
    assert entity_id is not None
    client_device: DeviceProxy | None = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None
    assert entity.state.on is False

    on_off_cluster.read_attributes.reset_mock()

    # not enough time passed
    await asyncio.sleep(60)  # 1 minute
    await server.block_till_done()
    assert on_off_cluster.read_attributes.call_count == 0
    assert on_off_cluster.read_attributes.await_count == 0
    assert entity.state.on is False

    # 1 interval - at least 1 call
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 1}
    await asyncio.sleep(4800)  # 80 minutes
    await server.block_till_done()
    assert on_off_cluster.read_attributes.call_count >= 1
    assert on_off_cluster.read_attributes.await_count >= 1
    assert entity.state.on is True

    # 2 intervals - at least 2 calls
    on_off_cluster.PLUGGED_ATTR_READS = {"on_off": 0}
    await asyncio.sleep(4800)  # 80 minutes
    await server.block_till_done()
    assert on_off_cluster.read_attributes.call_count >= 2
    assert on_off_cluster.read_attributes.await_count >= 2
    assert entity.state.on is False


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
async def test_light(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
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
            "color_capabilities": ColorClusterHandler.CAPABILITIES_COLOR_XY
            | ColorClusterHandler.CAPABILITIES_COLOR_TEMP,
        }
        update_attribute_cache(cluster_color)
    zha_device = await device_joined(zigpy_device)
    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.LIGHT, zha_device)
    assert entity_id is not None

    cluster_on_off: general.OnOff = zigpy_device.endpoints[1].on_off
    cluster_level: general.LevelControl = getattr(
        zigpy_device.endpoints[1], "level", None
    )
    cluster_identify: general.Identify = getattr(
        zigpy_device.endpoints[1], "identify", None
    )

    client_device: DeviceProxy | None = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    assert entity.state.on is False

    # test turning the lights on and off from the light
    await async_test_on_off_from_light(server, cluster_on_off, entity)

    # test turning the lights on and off from the client
    await async_test_on_off_from_client(server, cluster_on_off, entity, controller)

    # test short flashing the lights from the client
    if cluster_identify:
        await async_test_flash_from_client(
            server, cluster_identify, entity, FLASH_SHORT, controller
        )

    # test turning the lights on and off from the client
    if cluster_level:
        await async_test_level_on_off_from_client(
            server, cluster_on_off, cluster_level, entity, controller
        )

        # test getting a brightness change from the network
        await async_test_on_from_light(server, cluster_on_off, entity)
        await async_test_dimmer_from_light(server, cluster_level, entity, 150, True)

    await async_test_off_from_client(server, cluster_on_off, entity, controller)

    # test long flashing the lights from the client
    if cluster_identify:
        await async_test_flash_from_client(
            server, cluster_identify, entity, FLASH_LONG, controller
        )
        await async_test_flash_from_client(
            server, cluster_identify, entity, FLASH_SHORT, controller
        )

    if cluster_color:
        # test color temperature from the client with transition
        assert entity.state.brightness != 50
        assert entity.state.color_temp != 200
        await controller.lights.turn_on(
            entity, brightness=50, transition=10, color_temp=200
        )
        await server.block_till_done()
        assert entity.state.brightness == 50
        assert entity.state.color_temp == 200
        assert entity.state.on is True
        assert cluster_color.request.call_count == 1
        assert cluster_color.request.await_count == 1
        assert cluster_color.request.call_args == call(
            False,
            10,
            cluster_color.commands_by_name["move_to_color_temp"].schema,
            200,
            100.0,
            expect_reply=True,
            manufacturer=None,
            tries=1,
            tsn=None,
        )
        cluster_color.request.reset_mock()

        # test color xy from the client
        assert entity.state.hs_color != (200.0, 50.0)
        await controller.lights.turn_on(entity, brightness=50, hs_color=[200, 50])
        await server.block_till_done()
        assert entity.state.brightness == 50
        assert entity.state.hs_color == (200.0, 50.0)
        assert cluster_color.request.call_count == 1
        assert cluster_color.request.await_count == 1
        assert cluster_color.request.call_args == call(
            False,
            7,
            cluster_color.commands_by_name["move_to_color"].schema,
            13369,
            18087,
            1,
            expect_reply=True,
            manufacturer=None,
            tries=1,
            tsn=None,
        )

        cluster_color.request.reset_mock()

        # test error when hs_color and color_temp are both set
        with pytest.raises(ValidationError):
            await controller.lights.turn_on(entity, color_temp=50, hs_color=[200, 50])
            await server.block_till_done()
            assert cluster_color.request.call_count == 0
            assert cluster_color.request.await_count == 0


async def async_test_on_off_from_light(
    server: Server, cluster: general.OnOff, entity: LightEntity | LightGroupEntity
) -> None:
    """Test on off functionality from the light."""
    # turn on at light
    await send_attributes_report(server, cluster, {1: 0, 0: 1, 2: 3})
    await server.block_till_done()
    assert entity.state.on is True

    # turn off at light
    await send_attributes_report(server, cluster, {1: 1, 0: 0, 2: 3})
    await server.block_till_done()
    assert entity.state.on is False


async def async_test_on_from_light(
    server: Server, cluster: general.OnOff, entity: LightEntity | LightGroupEntity
) -> None:
    """Test on off functionality from the light."""
    # turn on at light
    await send_attributes_report(server, cluster, {1: -1, 0: 1, 2: 2})
    await server.block_till_done()
    assert entity.state.on is True


async def async_test_on_off_from_client(
    server: Server,
    cluster: general.OnOff,
    entity: LightEntity | LightGroupEntity,
    controller: Controller,
) -> None:
    """Test on off functionality from client."""
    # turn on via UI
    cluster.request.reset_mock()
    await controller.lights.turn_on(entity)
    await server.block_till_done()
    assert entity.state.on is True
    assert cluster.request.call_count == 1
    assert cluster.request.await_count == 1
    assert cluster.request.call_args == call(
        False,
        ON,
        cluster.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tries=1,
        tsn=None,
    )

    await async_test_off_from_client(server, cluster, entity, controller)


async def async_test_off_from_client(
    server: Server,
    cluster: general.OnOff,
    entity: LightEntity | LightGroupEntity,
    controller: Controller,
) -> None:
    """Test turning off the light from the client."""

    # turn off via UI
    cluster.request.reset_mock()
    await controller.lights.turn_off(entity)
    await server.block_till_done()
    assert entity.state.on is False
    assert cluster.request.call_count == 1
    assert cluster.request.await_count == 1
    assert cluster.request.call_args == call(
        False,
        OFF,
        cluster.commands_by_name["off"].schema,
        expect_reply=True,
        manufacturer=None,
        tries=1,
        tsn=None,
    )


async def async_test_level_on_off_from_client(
    server: Server,
    on_off_cluster: general.OnOff,
    level_cluster: general.LevelControl,
    entity: LightEntity | LightGroupEntity,
    controller: Controller,
) -> None:
    """Test on off functionality from client."""

    on_off_cluster.request.reset_mock()
    level_cluster.request.reset_mock()
    # turn on via UI
    await controller.lights.turn_on(entity)
    await server.block_till_done()
    assert entity.state.on is True
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
        tries=1,
        tsn=None,
    )
    on_off_cluster.request.reset_mock()
    level_cluster.request.reset_mock()

    await controller.lights.turn_on(entity, transition=10)
    await server.block_till_done()
    assert entity.state.on is True
    assert on_off_cluster.request.call_count == 1
    assert on_off_cluster.request.await_count == 1
    assert level_cluster.request.call_count == 1
    assert level_cluster.request.await_count == 1
    assert on_off_cluster.request.call_args == call(
        False,
        ON,
        on_off_cluster.commands_by_name["on"].schema,
        expect_reply=True,
        manufacturer=None,
        tries=1,
        tsn=None,
    )
    assert level_cluster.request.call_args == call(
        False,
        4,
        level_cluster.commands_by_name["move_to_level_with_on_off"].schema,
        254,
        100.0,
        expect_reply=True,
        manufacturer=None,
        tries=1,
        tsn=None,
    )
    on_off_cluster.request.reset_mock()
    level_cluster.request.reset_mock()

    await controller.lights.turn_on(entity, brightness=10)
    await server.block_till_done()
    assert entity.state.on is True
    # the onoff cluster is now not used when brightness is present by default
    assert on_off_cluster.request.call_count == 0
    assert on_off_cluster.request.await_count == 0
    assert level_cluster.request.call_count == 1
    assert level_cluster.request.await_count == 1
    assert level_cluster.request.call_args == call(
        False,
        4,
        level_cluster.commands_by_name["move_to_level_with_on_off"].schema,
        10,
        1,
        expect_reply=True,
        manufacturer=None,
        tries=1,
        tsn=None,
    )
    on_off_cluster.request.reset_mock()
    level_cluster.request.reset_mock()

    await async_test_off_from_client(server, on_off_cluster, entity, controller)


async def async_test_dimmer_from_light(
    server: Server,
    cluster: general.LevelControl,
    entity: LightEntity | LightGroupEntity,
    level: int,
    expected_state: bool,
) -> None:
    """Test dimmer functionality from the light."""

    await send_attributes_report(
        server, cluster, {1: level + 10, 0: level, 2: level - 10 or 22}
    )
    await server.block_till_done()
    assert entity.state.on == expected_state
    # hass uses None for brightness of 0 in state attributes
    if level == 0:
        assert entity.state.brightness is None
    else:
        assert entity.state.brightness == level


async def async_test_flash_from_client(
    server: Server,
    cluster: general.Identify,
    entity: LightEntity | LightGroupEntity,
    flash: str,
    controller: Controller,
) -> None:
    """Test flash functionality from client."""
    # turn on via UI
    cluster.request.reset_mock()
    await controller.lights.turn_on(entity, flash=flash)
    await server.block_till_done()
    assert entity.state.on is True
    assert cluster.request.call_count == 1
    assert cluster.request.await_count == 1
    assert cluster.request.call_args == call(
        False,
        64,
        cluster.commands_by_name["trigger_effect"].schema,
        FLASH_EFFECTS[flash],
        0,
        expect_reply=True,
        manufacturer=None,
        tries=1,
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
async def test_zha_group_light_entity(
    device_light_1: Device,
    device_light_2: Device,
    device_light_3: Device,
    coordinator: Device,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test the light entity for a ZHA group."""
    controller, server = connected_client_and_server
    member_ieee_addresses = [device_light_1.ieee, device_light_2.ieee]
    members = [
        GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
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

    entity_id = async_find_group_entity_id(Platform.LIGHT, zha_group)
    assert entity_id is not None

    group_proxy: GroupProxy | None = controller.groups.get(2)
    assert group_proxy is not None

    device_1_proxy: DeviceProxy | None = controller.devices.get(device_light_1.ieee)
    assert device_1_proxy is not None

    device_2_proxy: DeviceProxy | None = controller.devices.get(device_light_2.ieee)
    assert device_2_proxy is not None

    device_3_proxy: DeviceProxy | None = controller.devices.get(device_light_3.ieee)
    assert device_3_proxy is not None

    entity: LightGroupEntity | None = get_group_entity(group_proxy, entity_id)
    assert entity is not None

    assert isinstance(entity, LightGroupEntity)
    assert entity is not None

    device_1_entity_id = find_entity_id(Platform.LIGHT, device_light_1)
    assert device_1_entity_id is not None
    device_2_entity_id = find_entity_id(Platform.LIGHT, device_light_2)
    assert device_2_entity_id is not None
    device_3_entity_id = find_entity_id(Platform.LIGHT, device_light_3)
    assert device_3_entity_id is not None

    device_1_light_entity = get_entity(device_1_proxy, device_1_entity_id)
    assert device_1_light_entity is not None

    device_2_light_entity = get_entity(device_2_proxy, device_2_entity_id)
    assert device_2_light_entity is not None

    device_3_light_entity = get_entity(device_3_proxy, device_3_entity_id)
    assert device_3_light_entity is not None

    assert (
        device_1_entity_id != device_2_entity_id
        and device_1_entity_id != device_3_entity_id
    )
    assert device_2_entity_id != device_3_entity_id

    group_entity_id = async_find_group_entity_id(Platform.LIGHT, zha_group)
    assert group_entity_id is not None
    entity = get_group_entity(group_proxy, group_entity_id)
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
    assert entity.state.on is False

    # test turning the lights on and off from the client
    await async_test_on_off_from_client(
        server, group_cluster_on_off, entity, controller
    )

    # test turning the lights on and off from the light
    await async_test_on_off_from_light(server, dev1_cluster_on_off, entity)

    # test turning the lights on and off from the client
    await async_test_level_on_off_from_client(
        server, group_cluster_on_off, group_cluster_level, entity, controller
    )

    # test getting a brightness change from the network
    await async_test_on_from_light(server, dev1_cluster_on_off, entity)
    await async_test_dimmer_from_light(server, dev1_cluster_level, entity, 150, True)

    # test short flashing the lights from the client
    await async_test_flash_from_client(
        server, group_cluster_identify, entity, FLASH_SHORT, controller
    )
    # test long flashing the lights from the client
    await async_test_flash_from_client(
        server, group_cluster_identify, entity, FLASH_LONG, controller
    )

    assert len(zha_group.members) == 2
    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(server, dev1_cluster_on_off, {0: 1})
    await send_attributes_report(server, dev2_cluster_on_off, {0: 1})
    await server.block_till_done()

    # test that group light is on
    assert device_1_light_entity.state.on is True
    assert device_2_light_entity.state.on is True
    assert entity.state.on is True

    await send_attributes_report(server, dev1_cluster_on_off, {0: 0})
    await server.block_till_done()

    # test that group light is still on
    assert device_1_light_entity.state.on is False
    assert device_2_light_entity.state.on is True
    assert entity.state.on is True

    await send_attributes_report(server, dev2_cluster_on_off, {0: 0})
    await server.block_till_done()

    # test that group light is now off
    assert device_1_light_entity.state.on is False
    assert device_2_light_entity.state.on is False
    assert entity.state.on is False

    await send_attributes_report(server, dev1_cluster_on_off, {0: 1})
    await server.block_till_done()

    # test that group light is now back on
    assert device_1_light_entity.state.on is True
    assert device_2_light_entity.state.on is False
    assert entity.state.on is True

    # turn it off to test a new member add being tracked
    await send_attributes_report(server, dev1_cluster_on_off, {0: 0})
    await server.block_till_done()
    assert device_1_light_entity.state.on is False
    assert device_2_light_entity.state.on is False
    assert entity.state.on is False

    # add a new member and test that his state is also tracked
    await zha_group.async_add_members(
        [GroupMemberReference(ieee=device_light_3.ieee, endpoint_id=1)]
    )
    await server.block_till_done()
    assert device_3_light_entity.unique_id in zha_group.all_member_entity_unique_ids
    assert len(zha_group.members) == 3
    entity = get_group_entity(group_proxy, group_entity_id)
    assert entity is not None
    await send_attributes_report(server, dev3_cluster_on_off, {0: 1})
    await server.block_till_done()

    assert device_1_light_entity.state.on is False
    assert device_2_light_entity.state.on is False
    assert device_3_light_entity.state.on is True
    assert entity.state.on is True

    # make the group have only 1 member and now there should be no entity
    await zha_group.async_remove_members(
        [
            GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
            GroupMemberReference(ieee=device_light_3.ieee, endpoint_id=1),
        ]
    )
    await server.block_till_done()
    assert len(zha_group.members) == 1
    assert device_2_light_entity.unique_id not in zha_group.all_member_entity_unique_ids
    assert device_3_light_entity.unique_id not in zha_group.all_member_entity_unique_ids
    assert entity.unique_id not in group_proxy.group_model.entities

    entity = get_group_entity(group_proxy, group_entity_id)
    assert entity is None

    # add a member back and ensure that the group entity was created again
    await zha_group.async_add_members(
        [GroupMemberReference(ieee=device_light_3.ieee, endpoint_id=1)]
    )
    await server.block_till_done()
    assert len(zha_group.members) == 2

    entity = get_group_entity(group_proxy, group_entity_id)
    assert entity is not None
    await send_attributes_report(server, dev3_cluster_on_off, {0: 1})
    await server.block_till_done()
    assert entity.state.on is True

    # add a 3rd member and ensure we still have an entity and we track the new member
    # First we turn the lights currently in the group off
    await send_attributes_report(server, dev1_cluster_on_off, {0: 0})
    await send_attributes_report(server, dev3_cluster_on_off, {0: 0})
    await server.block_till_done()
    assert entity.state.on is False

    # this will test that _reprobe_group is used correctly
    await zha_group.async_add_members(
        [
            GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
            GroupMemberReference(ieee=coordinator.ieee, endpoint_id=1),
        ]
    )
    await server.block_till_done()
    assert len(zha_group.members) == 4
    entity = get_group_entity(group_proxy, group_entity_id)
    assert entity is not None
    await send_attributes_report(server, dev2_cluster_on_off, {0: 1})
    await server.block_till_done()
    assert entity.state.on is True

    await zha_group.async_remove_members(
        [GroupMemberReference(ieee=coordinator.ieee, endpoint_id=1)]
    )
    await server.block_till_done()
    entity = get_group_entity(group_proxy, group_entity_id)
    assert entity is not None
    assert entity.state.on is True
    assert len(zha_group.members) == 3

    # remove the group and ensure that there is no entity and that the entity registry is cleaned up
    await server.controller.async_remove_zigpy_group(zha_group.group_id)
    await server.block_till_done()
    entity = get_group_entity(group_proxy, group_entity_id)
    assert entity is None
