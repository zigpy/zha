"""Test zha sensor."""

import asyncio
from collections.abc import Awaitable, Callable
import math
from typing import Any, Optional

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
from zigpy.quirks import CustomCluster, get_device
from zigpy.quirks.v2 import CustomDeviceV2, add_to_registry_v2
import zigpy.types as t
from zigpy.zcl import Cluster
from zigpy.zcl.clusters import general, homeautomation, hvac, measurement, smartenergy
from zigpy.zcl.clusters.manufacturer_specific import ManufacturerSpecificCluster

from zha.application import Platform
from zha.application.const import ZHA_CLUSTER_HANDLER_READS_PER_REQ
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.sensor import UnitOfMass
from zha.application.platforms.sensor.const import SensorDeviceClass
from zha.units import PERCENTAGE, UnitOfEnergy, UnitOfPressure, UnitOfVolume
from zha.zigbee.device import Device

from .common import find_entity_id, find_entity_ids, send_attributes_report
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

ENTITY_ID_PREFIX = "sensor.fakemanufacturer_fakemodel_e769900a_{}"

EMAttrs = homeautomation.ElectricalMeasurement.AttributeDefs


@pytest.fixture
async def elec_measurement_zigpy_dev(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Electric Measurement zigpy device."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    homeautomation.ElectricalMeasurement.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SIMPLE_SENSOR,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
    )
    zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    zigpy_device.endpoints[1].electrical_measurement.PLUGGED_ATTR_READS = {
        "ac_current_divisor": 10,
        "ac_current_multiplier": 1,
        "ac_power_divisor": 10,
        "ac_power_multiplier": 1,
        "ac_voltage_divisor": 10,
        "ac_voltage_multiplier": 1,
        "measurement_type": 8,
        "power_divisor": 10,
        "power_multiplier": 1,
    }
    return zigpy_device


@pytest.fixture
async def elec_measurement_zha_dev(
    elec_measurement_zigpy_dev: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Electric Measurement ZHA device."""

    zha_dev = await device_joined(elec_measurement_zigpy_dev)
    zha_dev.available = True
    return zha_dev


async def async_test_humidity(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test humidity sensor."""
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 1000, 2: 100})
    assert_state(entity, 10.0, "%")


async def async_test_temperature(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test temperature sensor."""
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 2900, 2: 100})
    assert_state(entity, 29.0, "°C")


async def async_test_pressure(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test pressure sensor."""
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 1000, 2: 10000})
    assert_state(entity, 1000, "hPa")

    await send_attributes_report(zha_gateway, cluster, {0: 1000, 20: -1, 16: 10000})
    assert_state(entity, 1000, "hPa")


async def async_test_illuminance(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test illuminance sensor."""
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 10, 2: 20})
    assert_state(entity, 1.0, "lx")

    await send_attributes_report(zha_gateway, cluster, {0: 0xFFFF})
    assert_state(entity, None, "lx")


async def async_test_metering(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test Smart Energy metering sensor."""
    await send_attributes_report(
        zha_gateway, cluster, {1025: 1, 1024: 12345, 1026: 100}
    )
    assert_state(entity, 12345.0, None)
    assert entity.state["status"] == "NO_ALARMS"
    assert entity.state["device_type"] == "Electric Metering"

    await send_attributes_report(zha_gateway, cluster, {1024: 12346, "status": 64 + 8})
    assert_state(entity, 12346.0, None)
    assert entity.state["status"] in (
        "SERVICE_DISCONNECT|POWER_FAILURE",
        "POWER_FAILURE|SERVICE_DISCONNECT",
    )

    await send_attributes_report(
        zha_gateway, cluster, {"status": 64 + 8, "metering_device_type": 1}
    )
    assert entity.state["status"] in (
        "SERVICE_DISCONNECT|NOT_DEFINED",
        "NOT_DEFINED|SERVICE_DISCONNECT",
    )

    await send_attributes_report(
        zha_gateway, cluster, {"status": 64 + 8, "metering_device_type": 2}
    )
    assert entity.state["status"] in (
        "SERVICE_DISCONNECT|PIPE_EMPTY",
        "PIPE_EMPTY|SERVICE_DISCONNECT",
    )

    await send_attributes_report(
        zha_gateway, cluster, {"status": 64 + 8, "metering_device_type": 5}
    )
    assert entity.state["status"] in (
        "SERVICE_DISCONNECT|TEMPERATURE_SENSOR",
        "TEMPERATURE_SENSOR|SERVICE_DISCONNECT",
    )

    # Status for other meter types
    await send_attributes_report(
        zha_gateway, cluster, {"status": 32, "metering_device_type": 4}
    )
    assert entity.state["status"] in ("<bitmap8.32: 32>", "32")


async def async_test_smart_energy_summation_delivered(
    zha_gateway: Gateway, cluster, entity
):
    """Test SmartEnergy Summation delivered sensor."""

    await send_attributes_report(
        zha_gateway, cluster, {1025: 1, "current_summ_delivered": 12321, 1026: 100}
    )
    assert_state(entity, 12.321, UnitOfEnergy.KILO_WATT_HOUR)
    assert entity.state["status"] == "NO_ALARMS"
    assert entity.state["device_type"] == "Electric Metering"
    assert entity.info_object.device_class == SensorDeviceClass.ENERGY


async def async_test_smart_energy_summation_received(
    zha_gateway: Gateway, cluster, entity
):
    """Test SmartEnergy Summation received sensor."""

    await send_attributes_report(
        zha_gateway, cluster, {1025: 1, "current_summ_received": 12321, 1026: 100}
    )
    assert_state(entity, 12.321, UnitOfEnergy.KILO_WATT_HOUR)
    assert entity.state["status"] == "NO_ALARMS"
    assert entity.state["device_type"] == "Electric Metering"
    assert entity.info_object.device_class == SensorDeviceClass.ENERGY


async def async_test_smart_energy_summation(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test SmartEnergy Summation delivered sensro."""

    await send_attributes_report(
        zha_gateway, cluster, {1025: 1, "current_summ_delivered": 12321, 1026: 100}
    )
    assert_state(entity, 12.32, "m³")
    assert entity.state["status"] == "NO_ALARMS"
    assert entity.state["device_type"] == "Electric Metering"


async def async_test_electrical_measurement(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test electrical measurement sensor."""
    # update divisor cached value
    await send_attributes_report(zha_gateway, cluster, {"ac_power_divisor": 1})
    await send_attributes_report(
        zha_gateway, cluster, {0: 1, EMAttrs.active_power.id: 100}
    )
    assert_state(entity, 100, "W")

    await send_attributes_report(
        zha_gateway, cluster, {0: 1, EMAttrs.active_power.id: 99}
    )
    assert_state(entity, 99, "W")

    await send_attributes_report(zha_gateway, cluster, {"ac_power_divisor": 10})
    await send_attributes_report(
        zha_gateway, cluster, {0: 1, EMAttrs.active_power.id: 1000}
    )
    assert_state(entity, 100, "W")

    await send_attributes_report(
        zha_gateway, cluster, {0: 1, EMAttrs.active_power.id: 99}
    )
    assert_state(entity, 9.9, "W")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x050D: 88})
    assert entity.state["active_power_max"] == 8.8


async def async_test_em_apparent_power(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test electrical measurement Apparent Power sensor."""
    # update divisor cached value
    await send_attributes_report(zha_gateway, cluster, {"ac_power_divisor": 1})
    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x050F: 100})
    assert_state(entity, 100, "VA")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x050F: 99})
    assert_state(entity, 99, "VA")

    await send_attributes_report(zha_gateway, cluster, {"ac_power_divisor": 10})
    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x050F: 1000})
    assert_state(entity, 100, "VA")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x050F: 99})
    assert_state(entity, 9.9, "VA")


async def async_test_em_power_factor(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
):
    """Test electrical measurement Power Factor sensor."""
    # update divisor cached value
    await send_attributes_report(zha_gateway, cluster, {"ac_power_divisor": 1})
    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0510: 100, 10: 1000})
    assert_state(entity, 100, PERCENTAGE)

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0510: 99, 10: 1000})
    assert_state(entity, 99, PERCENTAGE)

    await send_attributes_report(zha_gateway, cluster, {"ac_power_divisor": 10})
    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0510: 100, 10: 5000})
    assert_state(entity, 100, PERCENTAGE)

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0510: 99, 10: 5000})
    assert_state(entity, 99, PERCENTAGE)


async def async_test_em_rms_current(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test electrical measurement RMS Current sensor."""

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0508: 1234})
    assert_state(entity, 1.2, "A")

    await send_attributes_report(zha_gateway, cluster, {"ac_current_divisor": 10})
    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0508: 236})
    assert_state(entity, 23.6, "A")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0508: 1236})
    assert_state(entity, 124, "A")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x050A: 88})
    assert entity.state["rms_current_max"] == 8.8


async def async_test_em_rms_voltage(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test electrical measurement RMS Voltage sensor."""

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0505: 1234})
    assert_state(entity, 123, "V")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0505: 234})
    assert_state(entity, 23.4, "V")

    await send_attributes_report(zha_gateway, cluster, {"ac_voltage_divisor": 100})
    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0505: 2236})
    assert_state(entity, 22.4, "V")

    await send_attributes_report(zha_gateway, cluster, {0: 1, 0x0507: 888})
    assert entity.state["rms_voltage_max"] == 8.9


async def async_test_powerconfiguration(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test powerconfiguration/battery sensor."""
    await send_attributes_report(zha_gateway, cluster, {33: 98})
    assert_state(entity, 49, "%")
    assert entity.state["battery_voltage"] == 2.9
    assert entity.state["battery_quantity"] == 3
    assert entity.state["battery_size"] == "AAA"
    await send_attributes_report(zha_gateway, cluster, {32: 20})
    assert entity.state["battery_voltage"] == 2.0


async def async_test_powerconfiguration2(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
):
    """Test powerconfiguration/battery sensor."""
    await send_attributes_report(zha_gateway, cluster, {33: -1})
    assert_state(entity, None, "%")

    await send_attributes_report(zha_gateway, cluster, {33: 255})
    assert_state(entity, None, "%")

    await send_attributes_report(zha_gateway, cluster, {33: 98})
    assert_state(entity, 49, "%")


async def async_test_device_temperature(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
) -> None:
    """Test temperature sensor."""
    await send_attributes_report(zha_gateway, cluster, {0: 2900})
    assert_state(entity, 29.0, "°C")


async def async_test_setpoint_change_source(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
):
    """Test the translation of numerical state into enum text."""
    await send_attributes_report(
        zha_gateway,
        cluster,
        {hvac.Thermostat.AttributeDefs.setpoint_change_source.id: 0x01},
    )
    assert entity.state["state"] == "Schedule"


async def async_test_pi_heating_demand(
    zha_gateway: Gateway, cluster: Cluster, entity: PlatformEntity
):
    """Test pi heating demand is correctly returned."""
    await send_attributes_report(
        zha_gateway, cluster, {hvac.Thermostat.AttributeDefs.pi_heating_demand.id: 1}
    )
    assert_state(entity, 1, "%")


@pytest.mark.parametrize(
    "cluster_id, entity_suffix, test_func, read_plug, unsupported_attrs",
    (
        (
            measurement.RelativeHumidity.cluster_id,
            "humidity",
            async_test_humidity,
            None,
            None,
        ),
        (
            measurement.TemperatureMeasurement.cluster_id,
            "temperature",
            async_test_temperature,
            None,
            None,
        ),
        (
            measurement.PressureMeasurement.cluster_id,
            "pressure",
            async_test_pressure,
            None,
            None,
        ),
        (
            measurement.IlluminanceMeasurement.cluster_id,
            "illuminance",
            async_test_illuminance,
            None,
            None,
        ),
        (
            smartenergy.Metering.cluster_id,
            "smartenergy_metering",
            async_test_metering,
            {
                "demand_formatting": 0xF9,
                "divisor": 1,
                "metering_device_type": 0x00,
                "multiplier": 1,
                "status": 0x00,
            },
            {"current_summ_delivered"},
        ),
        (
            smartenergy.Metering.cluster_id,
            "smartenergy_metering_summation_delivered",
            async_test_smart_energy_summation,
            {
                "demand_formatting": 0xF9,
                "divisor": 1000,
                "metering_device_type": 0x00,
                "multiplier": 1,
                "status": 0x00,
                "summation_formatting": 0b1_0111_010,
                "unit_of_measure": 0x01,
            },
            {"instaneneous_demand"},
        ),
        (
            smartenergy.Metering.cluster_id,
            "smartenergy_metering_summation_received",
            async_test_smart_energy_summation_received,
            {
                "demand_formatting": 0xF9,
                "divisor": 1000,
                "metering_device_type": 0x00,
                "multiplier": 1,
                "status": 0x00,
                "summation_formatting": 0b1_0111_010,
                "unit_of_measure": 0x00,
                "current_summ_received": 0,
            },
            {"instaneneous_demand", "current_summ_delivered"},
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            "electrical_measurement",
            async_test_electrical_measurement,
            {"ac_power_divisor": 1000, "ac_power_multiplier": 1},
            {"apparent_power", "rms_current", "rms_voltage"},
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            "electrical_measurement_apparent_power",
            async_test_em_apparent_power,
            {"ac_power_divisor": 1000, "ac_power_multiplier": 1},
            {"active_power", "rms_current", "rms_voltage"},
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            "electrical_measurement_power_factor",
            async_test_em_power_factor,
            {"ac_power_divisor": 1000, "ac_power_multiplier": 1},
            {"active_power", "apparent_power", "rms_current", "rms_voltage"},
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            "electrical_measurement_rms_current",
            async_test_em_rms_current,
            {"ac_current_divisor": 1000, "ac_current_multiplier": 1},
            {"active_power", "apparent_power", "rms_voltage"},
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            "electrical_measurement_rms_voltage",
            async_test_em_rms_voltage,
            {"ac_voltage_divisor": 10, "ac_voltage_multiplier": 1},
            {"active_power", "apparent_power", "rms_current"},
        ),
        (
            general.PowerConfiguration.cluster_id,
            "power",
            async_test_powerconfiguration,
            {
                "battery_size": 4,  # AAA
                "battery_voltage": 29,
                "battery_quantity": 3,
            },
            None,
        ),
        (
            general.PowerConfiguration.cluster_id,
            "power",
            async_test_powerconfiguration2,
            {
                "battery_size": 4,  # AAA
                "battery_voltage": 29,
                "battery_quantity": 3,
            },
            None,
        ),
        (
            general.DeviceTemperature.cluster_id,
            "device_temperature",
            async_test_device_temperature,
            None,
            None,
        ),
        (
            hvac.Thermostat.cluster_id,
            "thermostat_setpoint_change_source",
            async_test_setpoint_change_source,
            None,
            None,
        ),
        (
            hvac.Thermostat.cluster_id,
            "thermostat_pi_heating_demand",
            async_test_pi_heating_demand,
            None,
            None,
        ),
    ),
)
async def test_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,
    cluster_id: int,
    entity_suffix: str,
    test_func: Callable[[Cluster, PlatformEntity], Awaitable[None]],
    read_plug: Optional[dict],
    unsupported_attrs: Optional[set],
) -> None:
    """Test zha sensor platform."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [cluster_id, general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        }
    )
    cluster = zigpy_device.endpoints[1].in_clusters[cluster_id]
    if unsupported_attrs:
        for attr in unsupported_attrs:
            cluster.add_unsupported_attribute(attr)
    if cluster_id in (
        smartenergy.Metering.cluster_id,
        homeautomation.ElectricalMeasurement.cluster_id,
    ):
        # this one is mains powered
        zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    cluster.PLUGGED_ATTR_READS = read_plug or {}

    zha_device = await device_joined(zigpy_device)

    entity_id = ENTITY_ID_PREFIX.format(entity_suffix)
    entity = get_entity(zha_device, entity_id)

    await zha_gateway.async_block_till_done()
    # test sensor associated logic
    await test_func(zha_gateway, cluster, entity)


def get_entity(zha_dev: Device, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]


def assert_state(entity: PlatformEntity, state: Any, unit_of_measurement: str) -> None:
    """Check that the state is what is expected.

    This is used to ensure that the logic in each sensor class handled the
    attribute report it received correctly.
    """
    assert entity.state["state"] == state
    # TODO assert entity._attr_native_unit_of_measurement == unit_of_measurement


@pytest.mark.looptime
async def test_electrical_measurement_init(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test proper initialization of the electrical measurement cluster."""

    cluster_id = homeautomation.ElectricalMeasurement.cluster_id
    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [cluster_id, general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        }
    )

    cluster = zigpy_device.endpoints[1].in_clusters[cluster_id]
    zha_device = await device_joined(zigpy_device)

    entity_id = "sensor.fakemanufacturer_fakemodel_e769900a_electrical_measurement"
    assert entity_id is not None
    entity = get_entity(zha_device, entity_id)
    assert entity is not None

    await send_attributes_report(
        zha_gateway,
        cluster,
        {EMAttrs.active_power.id: 100},
    )
    assert entity.state["state"] == 100

    cluster_handler = list(zha_device._endpoints.values())[0].all_cluster_handlers[
        "1:0x0b04"
    ]
    assert cluster_handler.ac_power_divisor == 1
    assert cluster_handler.ac_power_multiplier == 1

    # update power divisor
    await send_attributes_report(
        zha_gateway,
        cluster,
        {EMAttrs.active_power.id: 20, EMAttrs.power_divisor.id: 5},
    )
    assert cluster_handler.ac_power_divisor == 5
    assert cluster_handler.ac_power_multiplier == 1
    assert entity.state["state"] == 4.0

    zha_device.on_network = False

    await asyncio.sleep(entity.__polling_interval + 1)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert (
        "1-2820: skipping polling for updated state, available: False, allow polled requests: True"
        in caplog.text
    )

    zha_device.on_network = True

    await send_attributes_report(
        zha_gateway,
        cluster,
        {EMAttrs.active_power.id: 30, EMAttrs.ac_power_divisor.id: 10},
    )
    assert cluster_handler.ac_power_divisor == 10
    assert cluster_handler.ac_power_multiplier == 1
    assert entity.state["state"] == 3.0

    # update power multiplier
    await send_attributes_report(
        zha_gateway,
        cluster,
        {EMAttrs.active_power.id: 20, EMAttrs.power_multiplier.id: 6},
    )
    assert cluster_handler.ac_power_divisor == 10
    assert cluster_handler.ac_power_multiplier == 6
    assert entity.state["state"] == 12.0

    await send_attributes_report(
        zha_gateway,
        cluster,
        {EMAttrs.active_power.id: 30, EMAttrs.ac_power_multiplier.id: 20},
    )
    assert cluster_handler.ac_power_divisor == 10
    assert cluster_handler.ac_power_multiplier == 20
    assert entity.state["state"] == 60.0


@pytest.mark.parametrize(
    ("cluster_id", "unsupported_attributes", "entity_ids", "missing_entity_ids"),
    (
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            {"apparent_power", "rms_voltage", "rms_current"},
            {
                "electrical_measurement",
                "electrical_measurement_ac_frequency",
                "electrical_measurement_power_factor",
            },
            {
                "electrical_measurement_apparent_power",
                "electrical_measurement_rms_voltage",
                "electrical_measurement_rms_current",
            },
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            {"apparent_power", "rms_current", "ac_frequency", "power_factor"},
            {"electrical_measurement_rms_voltage", "electrical_measurement"},
            {
                "electrical_measurement_apparent_power",
                "electrical_measurement_current",
                "electrical_measurement_ac_frequency",
                "electrical_measurement_power_factor",
            },
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            set(),
            {
                "electrical_measurement_rms_voltage",
                "electrical_measurement",
                "electrical_measurement_apparent_power",
                "electrical_measurement_rms_current",
                "electrical_measurement_ac_frequency",
                "electrical_measurement_power_factor",
            },
            set(),
        ),
        (
            smartenergy.Metering.cluster_id,
            {
                "instantaneous_demand",
            },
            {
                "smartenergy_metering_summation_delivered",
            },
            {
                "instantaneous_demand",
            },
        ),
        (
            smartenergy.Metering.cluster_id,
            {"instantaneous_demand", "current_summ_delivered"},
            {},
            {
                "smartenergy_metering",
                "smartenergy_metering_summation_delivered",
            },
        ),
        (
            smartenergy.Metering.cluster_id,
            {},
            {
                "smartenergy_metering",
                "smartenergy_metering_summation_delivered",
            },
            {},
        ),
    ),
)
async def test_unsupported_attributes_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    cluster_id: int,
    unsupported_attributes: set,
    entity_ids: set,
    missing_entity_ids: set,
) -> None:
    """Test zha sensor platform."""

    entity_ids = {ENTITY_ID_PREFIX.format(e) for e in entity_ids}
    missing_entity_ids = {ENTITY_ID_PREFIX.format(e) for e in missing_entity_ids}

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [cluster_id, general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        }
    )
    cluster = zigpy_device.endpoints[1].in_clusters[cluster_id]
    if cluster_id == smartenergy.Metering.cluster_id:
        # this one is mains powered
        zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    for attr in unsupported_attributes:
        cluster.add_unsupported_attribute(attr)

    zha_device = await device_joined(zigpy_device)

    present_entity_ids = set(
        find_entity_ids(Platform.SENSOR, zha_device, omit=["lqi", "rssi"])
    )
    assert present_entity_ids == entity_ids
    assert missing_entity_ids not in present_entity_ids  # type: ignore[comparison-overlap]


@pytest.mark.parametrize(
    "raw_uom, raw_value, expected_state, expected_uom",
    (
        (
            1,
            12320,
            1.23,
            UnitOfVolume.CUBIC_METERS,
        ),
        (
            1,
            1232000,
            123.2,
            UnitOfVolume.CUBIC_METERS,
        ),
        (
            3,
            2340,
            0.23,
            UnitOfVolume.CUBIC_METERS,
        ),
        (
            3,
            2360,
            0.24,
            UnitOfVolume.CUBIC_METERS,
        ),
        (
            8,
            23660,
            2.37,
            UnitOfPressure.KPA,
        ),
        (
            0,
            9366,
            0.937,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            0,
            999,
            0.1,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            0,
            10091,
            1.009,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            0,
            10099,
            1.01,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            0,
            100999,
            10.1,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            0,
            100023,
            10.002,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            0,
            102456,
            10.246,
            UnitOfEnergy.KILO_WATT_HOUR,
        ),
        (
            5,
            102456,
            10.25,
            "IMP gal",
        ),
        (
            7,
            50124,
            5.01,
            UnitOfVolume.LITERS,
        ),
    ),
)
async def test_se_summation_uom(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    raw_uom: int,
    raw_value: int,
    expected_state: str,
    expected_uom: str,
) -> None:
    """Test zha smart energy summation."""

    entity_id = ENTITY_ID_PREFIX.format("smartenergy_metering_summation_delivered")
    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    smartenergy.Metering.cluster_id,
                    general.Basic.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SIMPLE_SENSOR,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        }
    )
    zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100

    cluster = zigpy_device.endpoints[1].in_clusters[smartenergy.Metering.cluster_id]
    for attr in ("instanteneous_demand",):
        cluster.add_unsupported_attribute(attr)
    cluster.PLUGGED_ATTR_READS = {
        "current_summ_delivered": raw_value,
        "demand_formatting": 0xF9,
        "divisor": 10000,
        "metering_device_type": 0x00,
        "multiplier": 1,
        "status": 0x00,
        "summation_formatting": 0b1_0111_010,
        "unit_of_measure": raw_uom,
    }
    zha_device = await device_joined(zigpy_device)

    entity = get_entity(zha_device, entity_id)

    assert_state(entity, expected_state, expected_uom)


@pytest.mark.parametrize(
    "raw_measurement_type, expected_type",
    (
        (1, "ACTIVE_MEASUREMENT"),
        (8, "PHASE_A_MEASUREMENT"),
        (9, "ACTIVE_MEASUREMENT, PHASE_A_MEASUREMENT"),
        (
            15,
            "ACTIVE_MEASUREMENT, REACTIVE_MEASUREMENT, APPARENT_MEASUREMENT, PHASE_A_MEASUREMENT",
        ),
    ),
)
async def test_elec_measurement_sensor_type(
    elec_measurement_zigpy_dev: ZigpyDevice,  # pylint: disable=redefined-outer-name
    raw_measurement_type: int,
    expected_type: str,
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test zha electrical measurement sensor type."""

    entity_id = ENTITY_ID_PREFIX.format("electrical_measurement")
    zigpy_dev = elec_measurement_zigpy_dev
    zigpy_dev.endpoints[1].electrical_measurement.PLUGGED_ATTR_READS[
        "measurement_type"
    ] = raw_measurement_type

    zha_dev = await device_joined(zigpy_dev)

    entity = get_entity(zha_dev, entity_id)
    assert entity is not None
    assert entity.state["measurement_type"] == expected_type


@pytest.mark.looptime
async def test_elec_measurement_sensor_polling(  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
    elec_measurement_zigpy_dev: ZigpyDevice,
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> None:
    """Test ZHA electrical measurement sensor polling."""

    entity_id = ENTITY_ID_PREFIX.format("electrical_measurement")
    zigpy_dev = elec_measurement_zigpy_dev
    zigpy_dev.endpoints[1].electrical_measurement.PLUGGED_ATTR_READS["active_power"] = (
        20
    )

    zha_dev = await device_joined(zigpy_dev)

    # test that the sensor has an initial state of 2.0
    entity = get_entity(zha_dev, entity_id)
    assert entity.state["state"] == 2.0

    # update the value for the power reading
    zigpy_dev.endpoints[1].electrical_measurement.PLUGGED_ATTR_READS["active_power"] = (
        60
    )

    # ensure the state is still 2.0
    assert entity.state["state"] == 2.0

    # let the polling happen
    await asyncio.sleep(90)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    # ensure the state has been updated to 6.0
    assert entity.state["state"] == 6.0


@pytest.mark.parametrize(
    "supported_attributes",
    (
        set(),
        {
            "active_power",
            "active_power_max",
            "rms_current",
            "rms_current_max",
            "rms_voltage",
            "rms_voltage_max",
        },
        {
            "active_power",
        },
        {
            "active_power",
            "active_power_max",
        },
        {
            "rms_current",
            "rms_current_max",
        },
        {
            "rms_voltage",
            "rms_voltage_max",
        },
    ),
)
async def test_elec_measurement_skip_unsupported_attribute(
    elec_measurement_zha_dev: Device,  # pylint: disable=redefined-outer-name
    supported_attributes: set[str],
) -> None:
    """Test zha electrical measurement skipping update of unsupported attributes."""

    entity_id = ENTITY_ID_PREFIX.format("electrical_measurement")
    zha_dev = elec_measurement_zha_dev

    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    entity = entities[entity_id]

    cluster = zha_dev.device.endpoints[1].electrical_measurement

    all_attrs = {
        "active_power",
        "active_power_max",
        "apparent_power",
        "rms_current",
        "rms_current_max",
        "rms_voltage",
        "rms_voltage_max",
        "power_factor",
        "ac_frequency",
        "ac_frequency_max",
    }
    for attr in all_attrs - supported_attributes:
        cluster.add_unsupported_attribute(attr)
    cluster.read_attributes.reset_mock()

    await entity.async_update()
    await zha_dev.gateway.async_block_till_done()
    assert cluster.read_attributes.call_count == math.ceil(
        len(supported_attributes) / ZHA_CLUSTER_HANDLER_READS_PER_REQ
    )
    read_attrs = {
        a for call in cluster.read_attributes.call_args_list for a in call[0][0]
    }
    assert read_attrs == supported_attributes


class OppleCluster(CustomCluster, ManufacturerSpecificCluster):
    """Aqara manufacturer specific cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "opple_cluster"
    attributes = {
        0x010C: ("last_feeding_size", t.uint16_t, True),
    }

    def __init__(self, *args, **kwargs) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        # populate cache to create config entity
        self._attr_cache.update({0x010C: 10})


(
    add_to_registry_v2("Fake_Manufacturer_sensor", "Fake_Model_sensor")
    .replaces(OppleCluster)
    .sensor(
        "last_feeding_size",
        OppleCluster.cluster_id,
        divisor=1,
        multiplier=1,
        unit=UnitOfMass.GRAMS,
    )
)


@pytest.fixture
async def zigpy_device_aqara_sensor_v2(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    zigpy_device_mock,
    device_joined,
):
    """Device tracker zigpy Aqara motion sensor device."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    OppleCluster.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.OCCUPANCY_SENSOR,
            }
        },
        manufacturer="Fake_Manufacturer_sensor",
        model="Fake_Model_sensor",
    )

    zigpy_device = get_device(zigpy_device)

    zha_device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].opple_cluster


async def test_last_feeding_size_sensor_v2(
    zha_gateway: Gateway,
    zigpy_device_aqara_sensor_v2,  # pylint: disable=redefined-outer-name
) -> None:
    """Test quirks defined sensor."""

    zha_device, cluster = zigpy_device_aqara_sensor_v2
    assert isinstance(zha_device.device, CustomDeviceV2)
    entity_id = find_entity_id(
        Platform.SENSOR, zha_device, qualifier="last_feeding_size"
    )
    assert entity_id is not None
    entity = get_entity(zha_device, entity_id)
    assert entity is not None

    await send_attributes_report(zha_gateway, cluster, {0x010C: 1})
    assert_state(entity, 1.0, "g")

    await send_attributes_report(zha_gateway, cluster, {0x010C: 5})
    assert_state(entity, 5.0, "g")


@pytest.mark.looptime
async def test_device_counter_sensors(
    zha_gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    """Test quirks defined sensor."""

    coordinator = zha_gateway.coordinator_zha_device
    assert coordinator.is_coordinator
    entity_id = (
        "sensor.coordinator_manufacturer_coordinator_model_ezsp_counters_counter_1"
    )
    entity = get_entity(coordinator, entity_id)
    assert entity is not None

    assert entity.state["state"] == 1

    # simulate counter increment on application
    coordinator.device.application.state.counters["ezsp_counters"][
        "counter_1"
    ].increment()

    await asyncio.sleep(zha_gateway.global_updater.__polling_interval + 2)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert entity.state["state"] == 2

    coordinator.available = False
    await asyncio.sleep(120)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert (
        "counter_1: skipping polling for updated state, available: False, allow polled requests: True"
        in caplog.text
    )
