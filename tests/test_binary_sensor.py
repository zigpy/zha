"""Test zhaws binary sensor."""

from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock, call

import pytest
from zigpy.profiles import zha
import zigpy.profiles.zha
from zigpy.quirks import DeviceRegistry
from zigpy.quirks.v2 import CustomDeviceV2, QuirkBuilder
from zigpy.zcl.clusters import general, measurement, security
from zigpy.zcl.clusters.general import OnOff

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    find_entity,
    get_entity,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.binary_sensor import (
    Accelerometer,
    BinarySensor,
    IASZone,
    Occupancy,
)
from zha.zigbee.cluster_handlers.const import SMARTTHINGS_ACCELERATION_CLUSTER

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

DEVICE_GENERAL = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SENSOR,
        SIG_EP_INPUT: [general.BinaryInput.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}

DEVICE_SMARTTHINGS_MULTI = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.IAS_ZONE,
        SIG_EP_INPUT: [
            general.Basic.cluster_id,
            general.PowerConfiguration.cluster_id,
            general.Identify.cluster_id,
            general.PollControl.cluster_id,
            measurement.TemperatureMeasurement.cluster_id,
            security.IasZone.cluster_id,
            SMARTTHINGS_ACCELERATION_CLUSTER,
        ],
        SIG_EP_OUTPUT: [general.Identify.cluster_id, general.Ota.cluster_id],
    }
}


async def async_test_binary_sensor_occupancy(
    zha_gateway: Gateway,
    cluster: general.OnOff,
    entity: Occupancy,
    plugs: dict[str, int],
) -> None:
    """Test getting on and off messages for binary sensors."""
    # binary sensor on
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.is_on

    # binary sensor off
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.is_on is False

    # test refresh
    cluster.read_attributes.reset_mock()
    assert entity.is_on is False
    cluster.PLUGGED_ATTR_READS = plugs
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["occupancy"], allow_cache=True, only_cache=True, manufacturer=None
    )
    assert entity.is_on


async def async_test_iaszone_on_off(
    zha_gateway: Gateway,
    cluster: security.IasZone,
    entity: IASZone,
    plugs: dict[str, int],
) -> None:
    """Test getting on and off messages for iaszone binary sensors."""
    # binary sensor on
    cluster.listener_event("cluster_command", 1, 0, [1])
    await zha_gateway.async_block_till_done()
    assert entity.is_on

    # binary sensor off
    cluster.listener_event("cluster_command", 1, 0, [0])
    await zha_gateway.async_block_till_done()
    assert entity.is_on is False

    # check that binary sensor remains off when non-alarm bits change
    cluster.listener_event("cluster_command", 1, 0, [0b1111111100])
    await zha_gateway.async_block_till_done()
    assert entity.is_on is False

    # test refresh
    cluster.read_attributes.reset_mock()
    assert entity.is_on is False
    cluster.PLUGGED_ATTR_READS = plugs
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["zone_status"], allow_cache=False, only_cache=False, manufacturer=None
    )
    assert entity.is_on


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
            async_test_binary_sensor_occupancy,
            "occupancy",
            Occupancy,
            {"occupancy": 1},
        ),
    ],
)
async def test_binary_sensor(
    zha_gateway: Gateway,
    device: dict,
    on_off_test: Callable[..., Awaitable[None]],
    cluster_name: str,
    entity_type: type,
    plugs: dict[str, int],
) -> None:
    """Test ZHA binary_sensor platform."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, device)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity: PlatformEntity = find_entity(zha_device, Platform.BINARY_SENSOR)
    assert entity is not None
    assert isinstance(entity, entity_type)
    assert entity.PLATFORM == Platform.BINARY_SENSOR

    assert entity.fallback_name is None
    assert entity.is_on is False

    # test getting messages that trigger and reset the sensors
    cluster = getattr(zigpy_device.endpoints[1], cluster_name)
    await on_off_test(zha_gateway, cluster, entity, plugs)


async def test_binary_sensor_general(
    zha_gateway: Gateway,
) -> None:
    """Test binary sensor general - description."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway, DEVICE_GENERAL, manufacturer="DevManuf", model="DevModel"
    )

    cluster = getattr(zigpy_device.endpoints[1], "binary_input")
    cluster.PLUGGED_ATTR_READS = {"description": "Binary Input", "present_value": 1}
    update_attribute_cache(cluster)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity: PlatformEntity = find_entity(zha_device, Platform.BINARY_SENSOR)

    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.fallback_name == "Binary Input"
    assert entity.translation_key is None


async def test_smarttthings_multi(
    zha_gateway: Gateway,
) -> None:
    """Test smartthings multi."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway, DEVICE_SMARTTHINGS_MULTI, manufacturer="Samjin", model="multi"
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity: PlatformEntity = get_entity(
        zha_device, Platform.BINARY_SENSOR, entity_type=Accelerometer
    )
    assert entity is not None
    assert isinstance(entity, Accelerometer)
    assert entity.PLATFORM == Platform.BINARY_SENSOR
    assert entity.is_on is False

    st_ch = zha_device.endpoints[1].all_cluster_handlers["1:0xfc02"]
    assert st_ch is not None

    st_ch.emit_zha_event = MagicMock(wraps=st_ch.emit_zha_event)

    await send_attributes_report(zha_gateway, st_ch.cluster, {0x0012: 120})

    assert st_ch.emit_zha_event.call_count == 1
    assert st_ch.emit_zha_event.mock_calls == [
        call(
            "attribute_updated",
            {"attribute_id": 18, "attribute_name": "x_axis", "attribute_value": 120},
        )
    ]


async def test_quirks_binary_sensor_attr_converter(zha_gateway: Gateway) -> None:
    """Test ZHA quirks v2 binary_sensor with attribute_converter."""

    registry = DeviceRegistry()
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.SIMPLE_SENSOR,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="manufacturer",
        model="model",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model, registry=registry)
        .binary_sensor(
            OnOff.AttributeDefs.on_off.name,
            OnOff.cluster_id,
            translation_key="on_off",
            fallback_name="On/off",
            attribute_converter=lambda x: not bool(x),  # invert value with lambda
        )
        .add_to_registry()
    )

    zigpy_device_ = registry.get_device(zigpy_dev)

    assert isinstance(zigpy_device_, CustomDeviceV2)
    cluster = zigpy_device_.endpoints[1].on_off

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)
    entity = get_entity(zha_device, platform=Platform.BINARY_SENSOR)
    assert isinstance(entity, BinarySensor)

    # send updated value, check if the value is inverted
    await send_attributes_report(zha_gateway, cluster, {"on_off": 1})
    assert entity.is_on is False

    await send_attributes_report(zha_gateway, cluster, {"on_off": 0})
    assert entity.is_on is True
