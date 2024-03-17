"""Test zhaws binary sensor."""
from typing import Awaitable, Callable, Optional

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
import zigpy.zcl.clusters.general as general
import zigpy.zcl.clusters.measurement as measurement
import zigpy.zcl.clusters.security as security

from zhaws.client.controller import Controller
from zhaws.client.model.types import BinarySensorEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device

from .common import find_entity, send_attributes_report, update_attribute_cache
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

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
    await server.block_till_done()
    assert entity.state.state is True

    # binary sensor off
    cluster.listener_event("cluster_command", 1, 0, [0])
    await server.block_till_done()
    assert entity.state.state is False


@pytest.mark.parametrize(
    "device, on_off_test, cluster_name, reporting",
    [
        (DEVICE_IAS, async_test_iaszone_on_off, "ias_zone", (0,)),
        (DEVICE_OCCUPANCY, async_test_binary_sensor_on_off, "occupancy", (1,)),
    ],
)
async def test_binary_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
    device: dict,
    on_off_test: Callable[..., Awaitable[None]],
    cluster_name: str,
    reporting: tuple,
) -> None:
    """Test ZHA binary_sensor platform."""
    zigpy_device = zigpy_device_mock(device)
    controller, server = connected_client_and_server
    zhaws_device = await device_joined(zigpy_device)

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
    await server.block_till_done()
    assert entity.state.state is False
