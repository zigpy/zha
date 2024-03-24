"""Test zhaws binary sensor."""

from collections.abc import Awaitable, Callable

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
from zigpy.zcl.clusters import general, measurement, security

from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.binary_sensor import IASZone, Occupancy
from zha.zigbee.device import Device

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
    zha_gateway: Gateway, cluster: general.OnOff, entity: Occupancy
) -> None:
    """Test getting on and off messages for binary sensors."""
    # binary sensor on
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.is_on

    # binary sensor off
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert not entity.is_on


async def async_test_iaszone_on_off(
    zha_gateway: Gateway, cluster: security.IasZone, entity: IASZone
) -> None:
    """Test getting on and off messages for iaszone binary sensors."""
    # binary sensor on
    cluster.listener_event("cluster_command", 1, 0, [1])
    await zha_gateway.async_block_till_done()
    assert entity.is_on

    # binary sensor off
    cluster.listener_event("cluster_command", 1, 0, [0])
    await zha_gateway.async_block_till_done()
    assert not entity.is_on

    # check that binary sensor remains off when non-alarm bits change
    cluster.listener_event("cluster_command", 1, 0, [0b1111111100])  # type: ignore[unreachable]
    await zha_gateway.async_block_till_done()
    assert not entity.is_on


@pytest.mark.parametrize(
    "device, on_off_test, cluster_name, entity_type, plugs",
    [
        (
            DEVICE_IAS,
            async_test_iaszone_on_off,
            "ias_zone",
            IASZone,
            {"zone_status": 1},
        ),
        (
            DEVICE_OCCUPANCY,
            async_test_binary_sensor_on_off,
            "occupancy",
            Occupancy,
            {"occupancy": 1},
        ),
    ],
)
async def test_binary_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,
    device: dict,
    on_off_test: Callable[..., Awaitable[None]],
    cluster_name: str,
    entity_type: type,
    plugs: dict[str, int],
) -> None:
    """Test ZHA binary_sensor platform."""
    zigpy_device = zigpy_device_mock(device)
    zha_device = await device_joined(zigpy_device)

    entity: PlatformEntity = find_entity(zha_device, Platform.BINARY_SENSOR)  # type: ignore
    assert entity is not None
    assert isinstance(entity, entity_type)
    assert entity.PLATFORM == Platform.BINARY_SENSOR
    assert not entity.is_on

    # test getting messages that trigger and reset the sensors
    cluster = getattr(zigpy_device.endpoints[1], cluster_name)
    await on_off_test(zha_gateway, cluster, entity)

    # test refresh
    assert not entity.is_on
    cluster.PLUGGED_ATTR_READS = plugs
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.is_on
