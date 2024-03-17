"""Test zha cover."""
import asyncio
from typing import Awaitable, Callable, Optional
from unittest.mock import AsyncMock, patch

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
import zigpy.types
import zigpy.zcl.clusters.closures as closures
import zigpy.zcl.clusters.general as general
import zigpy.zcl.foundation as zcl_f

from zhaws.client.controller import Controller
from zhaws.client.model.types import CoverEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.cover import STATE_CLOSED, STATE_OPEN
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device

from .common import find_entity_id, send_attributes_report, update_attribute_cache
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

from tests.common import mock_coro


@pytest.fixture
def zigpy_cover_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy cover device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.IAS_ZONE,
            SIG_EP_INPUT: [closures.WindowCovering.cluster_id],
            SIG_EP_OUTPUT: [],
        }
    }
    return zigpy_device_mock(endpoints)


@pytest.fixture
def zigpy_shade_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy shade device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SHADE,
            SIG_EP_INPUT: [
                closures.Shade.cluster_id,
                general.LevelControl.cluster_id,
                general.OnOff.cluster_id,
            ],
            SIG_EP_OUTPUT: [],
        }
    }
    return zigpy_device_mock(endpoints)


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> CoverEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]  # type: ignore


@pytest.fixture
def zigpy_keen_vent(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy Keen Vent device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROLLABLE_OUTPUT,
            SIG_EP_INPUT: [general.LevelControl.cluster_id, general.OnOff.cluster_id],
            SIG_EP_OUTPUT: [],
        }
    }
    return zigpy_device_mock(
        endpoints, manufacturer="Keen Home Inc", model="SV02-612-MP-1.3"
    )


async def test_cover(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_cover_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha cover platform."""
    controller, server = connected_client_and_server
    cluster = zigpy_cover_device.endpoints.get(1).window_covering
    cluster.PLUGGED_ATTR_READS = {"current_position_lift_percentage": 100}
    zha_device = await device_joined(zigpy_cover_device)
    assert cluster.read_attributes.call_count == 1
    assert "current_position_lift_percentage" in cluster.read_attributes.call_args[0][0]

    entity_id = find_entity_id(Platform.COVER, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    # test that the state has changed from unavailable to off
    await send_attributes_report(server, cluster, {0: 0, 8: 100, 1: 1})
    assert entity.state.state == STATE_CLOSED

    # test to see if it opens
    await send_attributes_report(server, cluster, {0: 1, 8: 0, 1: 100})
    assert entity.state.state == STATE_OPEN

    cluster.PLUGGED_ATTR_READS = {1: 100}
    update_attribute_cache(cluster)
    await controller.entities.refresh_state(entity)
    await server.block_till_done()
    assert entity.state.state == STATE_OPEN

    # close from client
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([0x1, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.close_cover(entity)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x01
        assert cluster.request.call_args[0][2].command.name == "down_close"
        assert cluster.request.call_args[1]["expect_reply"] is True

    # open from client
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([0x0, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.open_cover(entity)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x00
        assert cluster.request.call_args[0][2].command.name == "up_open"
        assert cluster.request.call_args[1]["expect_reply"] is True

    # set position UI
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([0x5, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.set_cover_position(entity, 47)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x05
        assert cluster.request.call_args[0][2].command.name == "go_to_lift_percentage"
        assert cluster.request.call_args[0][3] == 53
        assert cluster.request.call_args[1]["expect_reply"] is True

    # stop from client
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([0x2, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.stop_cover(entity)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x02
        assert cluster.request.call_args[0][2].command.name == "stop"
        assert cluster.request.call_args[1]["expect_reply"] is True


async def test_shade(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_shade_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha cover platform for shade device type."""
    controller, server = connected_client_and_server
    zha_device = await device_joined(zigpy_shade_device)
    cluster_on_off = zigpy_shade_device.endpoints.get(1).on_off
    cluster_level = zigpy_shade_device.endpoints.get(1).level
    entity_id = find_entity_id(Platform.COVER, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    # test that the state has changed from unavailable to off
    await send_attributes_report(server, cluster_on_off, {8: 0, 0: False, 1: 1})
    assert entity.state.state == STATE_CLOSED

    # test to see if it opens
    await send_attributes_report(server, cluster_on_off, {8: 0, 0: True, 1: 1})
    assert entity.state.state == STATE_OPEN

    await controller.entities.refresh_state(entity)
    await server.block_till_done()
    assert entity.state.state == STATE_OPEN

    # close from client command fails
    with patch("zigpy.zcl.Cluster.request", side_effect=asyncio.TimeoutError):
        await controller.covers.close_cover(entity)
        await server.block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0000
        assert entity.state.state == STATE_OPEN

    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x1, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.close_cover(entity)
        await server.block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0000
        assert entity.state.state == STATE_CLOSED

    # open from client command fails
    await send_attributes_report(server, cluster_level, {0: 0})
    with patch("zigpy.zcl.Cluster.request", side_effect=asyncio.TimeoutError):
        await controller.covers.open_cover(entity)
        await server.block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert entity.state.state == STATE_CLOSED

    # open from client succeeds
    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x0, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.open_cover(entity)
        await server.block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert entity.state.state == STATE_OPEN

    # set position UI command fails
    with patch("zigpy.zcl.Cluster.request", side_effect=asyncio.TimeoutError):
        await controller.covers.set_cover_position(entity, 47)
        await server.block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] == 0x0004
        assert int(cluster_level.request.call_args[0][3] * 100 / 255) == 47
        assert entity.state.current_position == 0

    # set position UI success
    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x5, zcl_f.Status.SUCCESS])
    ):
        await controller.covers.set_cover_position(entity, 47)
        await server.block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] == 0x0004
        assert int(cluster_level.request.call_args[0][3] * 100 / 255) == 47
        assert entity.state.current_position == 47

    # report position change
    await send_attributes_report(server, cluster_level, {8: 0, 0: 100, 1: 1})
    assert entity.state.current_position == int(100 * 100 / 255)

    # test cover stop
    with patch("zigpy.zcl.Cluster.request", side_effect=asyncio.TimeoutError):
        await controller.covers.stop_cover(entity)
        await server.block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] in (0x0003, 0x0007)


async def test_keen_vent(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_keen_vent: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test keen vent."""
    controller, server = connected_client_and_server
    zha_device = await device_joined(zigpy_keen_vent)
    cluster_on_off = zigpy_keen_vent.endpoints.get(1).on_off
    cluster_level = zigpy_keen_vent.endpoints.get(1).level
    entity_id = find_entity_id(Platform.COVER, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    # test that the state has changed from unavailable to off
    await send_attributes_report(server, cluster_on_off, {8: 0, 0: False, 1: 1})
    assert entity.state.state == STATE_CLOSED

    await controller.entities.refresh_state(entity)
    await server.block_till_done()
    assert entity.state.state == STATE_CLOSED

    # open from client command fails
    p1 = patch.object(cluster_on_off, "request", side_effect=asyncio.TimeoutError)
    p2 = patch.object(cluster_level, "request", AsyncMock(return_value=[4, 0]))

    with p1, p2:
        await controller.covers.open_cover(entity)
        await server.block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert cluster_level.request.call_count == 1
        assert entity.state.state == STATE_CLOSED

    # open from client command success
    p1 = patch.object(cluster_on_off, "request", AsyncMock(return_value=[1, 0]))
    p2 = patch.object(cluster_level, "request", AsyncMock(return_value=[4, 0]))

    with p1, p2:
        await controller.covers.open_cover(entity)
        await server.block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert cluster_level.request.call_count == 1
        assert entity.state.state == STATE_OPEN
        assert entity.state.current_position == 100
