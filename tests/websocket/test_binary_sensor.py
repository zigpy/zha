"""Test zhaws binary sensor."""

from collections.abc import Awaitable, Callable
from typing import Optional

import pytest
import zigpy.profiles.zha
from zigpy.zcl.clusters import general, measurement, security

from zha.application.discovery import Platform
from zha.application.platforms.model import BasePlatformEntity, BinarySensorEntity
from zha.websocket.client.controller import Controller
from zha.websocket.client.proxy import DeviceProxy
from zha.websocket.server.gateway import WebSocketGateway as Server

from ..common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)


def find_entity(
    device_proxy: DeviceProxy, platform: Platform
) -> Optional[BasePlatformEntity]:
    """Find an entity for the specified platform on the given device."""
    for entity in device_proxy.device_model.entities.values():
        if entity.platform == platform:
            return entity
    return None


DEVICE_IAS = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.IAS_ZONE,
        SIG_EP_INPUT: [security.IasZone.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


DEVICE_OCCUPANCY = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.OCCUPANCY_SENSOR,
        SIG_EP_INPUT: [measurement.OccupancySensing.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


async def async_test_binary_sensor_on_off(
    server: Server, cluster: general.OnOff, entity: BinarySensorEntity
) -> None:
    """Test getting on and off messages for binary sensors."""
    # binary sensor on
    await send_attributes_report(server, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.state.state is True

    # binary sensor off
    await send_attributes_report(server, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.state.state is False


async def async_test_iaszone_on_off(
    server: Server, cluster: security.IasZone, entity: BinarySensorEntity
) -> None:
    """Test getting on and off messages for iaszone binary sensors."""
    # binary sensor on
    cluster.listener_event("cluster_command", 1, 0, [1])
    await server.async_block_till_done()
    assert entity.state.state is True

    # binary sensor off
    cluster.listener_event("cluster_command", 1, 0, [0])
    await server.async_block_till_done()
    assert entity.state.state is False


@pytest.mark.parametrize(
    "device, on_off_test, cluster_name, reporting",
    [
        (DEVICE_IAS, async_test_iaszone_on_off, "ias_zone", (0,)),
        (DEVICE_OCCUPANCY, async_test_binary_sensor_on_off, "occupancy", (1,)),
    ],
)
async def test_binary_sensor(
    connected_client_and_server: tuple[Controller, Server],
    device: dict,
    on_off_test: Callable[..., Awaitable[None]],
    cluster_name: str,
    reporting: tuple,
) -> None:
    """Test ZHA binary_sensor platform."""
    controller, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(server, device)
    zhaws_device = await join_zigpy_device(server, zigpy_device)

    await server.async_block_till_done()

    client_device: Optional[DeviceProxy] = controller.devices.get(zhaws_device.ieee)
    assert client_device is not None
    entity: BinarySensorEntity = find_entity(client_device, Platform.BINARY_SENSOR)  # type: ignore
    assert entity is not None
    assert isinstance(entity, BinarySensorEntity)
    assert entity.state.state is False

    # test getting messages that trigger and reset the sensors
    cluster = getattr(zigpy_device.endpoints[1], cluster_name)
    await on_off_test(server, cluster, entity)

    # test refresh
    if cluster_name == "ias_zone":
        cluster.PLUGGED_ATTR_READS = {"zone_status": 0}
        update_attribute_cache(cluster)
    await controller.entities.refresh_state(entity)
    await server.async_block_till_done()
    assert entity.state.state is False
