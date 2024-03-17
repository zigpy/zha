"""Test zha sensor."""
import math
from typing import Any, Awaitable, Callable, Optional

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
from zigpy.zcl import Cluster
import zigpy.zcl.clusters.general as general
import zigpy.zcl.clusters.homeautomation as homeautomation
import zigpy.zcl.clusters.measurement as measurement
import zigpy.zcl.clusters.smartenergy as smartenergy

from zhaws.client.controller import Controller
from zhaws.client.model.types import (
    BatteryEntity,
    ElectricalMeasurementEntity,
    SensorEntity,
    SmartEnergyMeteringEntity,
)
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device

from .common import find_entity_id, find_entity_ids, send_attributes_report
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

ENTITY_ID_PREFIX = "sensor.fakemanufacturer_fakemodel_e769900a_{}"


@pytest.fixture
async def elec_measurement_zigpy_dev(
    zigpy_device_mock: Callable[..., ZigpyDevice]
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
    elec_measurement_zigpy_dev: ZigpyDevice,
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Electric Measurement ZHA device."""

    zha_dev = await device_joined(elec_measurement_zigpy_dev)
    zha_dev.available = True
    return zha_dev


async def async_test_humidity(
    server: Server, cluster: Cluster, entity: SensorEntity
) -> None:
    """Test humidity sensor."""
    await send_attributes_report(server, cluster, {1: 1, 0: 1000, 2: 100})
    assert_state(entity, "10.0", "%")


async def async_test_temperature(
    server: Server, cluster: Cluster, entity: SensorEntity
) -> None:
    """Test temperature sensor."""
    await send_attributes_report(server, cluster, {1: 1, 0: 2900, 2: 100})
    assert_state(entity, "29.0", "°C")


async def async_test_pressure(
    server: Server, cluster: Cluster, entity: SensorEntity
) -> None:
    """Test pressure sensor."""
    await send_attributes_report(server, cluster, {1: 1, 0: 1000, 2: 10000})
    assert_state(entity, "1000", "hPa")

    await send_attributes_report(server, cluster, {0: 1000, 20: -1, 16: 10000})
    assert_state(entity, "1000", "hPa")


async def async_test_illuminance(
    server: Server, cluster: Cluster, entity: SensorEntity
) -> None:
    """Test illuminance sensor."""
    await send_attributes_report(server, cluster, {1: 1, 0: 10, 2: 20})
    assert_state(entity, "1.0", "lx")


async def async_test_metering(
    server: Server, cluster: Cluster, entity: SmartEnergyMeteringEntity
) -> None:
    """Test Smart Energy metering sensor."""
    await send_attributes_report(server, cluster, {1025: 1, 1024: 12345, 1026: 100})
    assert_state(entity, "12345.0", None)
    assert entity.state.status == "NO_ALARMS"
    assert entity.state.device_type == "Electric Metering"

    await send_attributes_report(server, cluster, {1024: 12346, "status": 64 + 8})
    assert_state(entity, "12346.0", None)
    assert entity.state.status == "SERVICE_DISCONNECT|POWER_FAILURE"

    await send_attributes_report(
        server, cluster, {"status": 32, "metering_device_type": 1}
    )
    # currently only statuses for electric meters are supported
    assert entity.state.status == "<bitmap8.32: 32>"


async def async_test_smart_energy_summation(
    server: Server, cluster: Cluster, entity: SmartEnergyMeteringEntity
) -> None:
    """Test SmartEnergy Summation delivered sensro."""

    await send_attributes_report(
        server, cluster, {1025: 1, "current_summ_delivered": 12321, 1026: 100}
    )
    assert_state(entity, "12.32", "m³")
    assert entity.state.status == "NO_ALARMS"
    assert entity.state.device_type == "Electric Metering"


async def async_test_electrical_measurement(
    server: Server, cluster: Cluster, entity: ElectricalMeasurementEntity
) -> None:
    """Test electrical measurement sensor."""
    # update divisor cached value
    await send_attributes_report(server, cluster, {"ac_power_divisor": 1})
    await send_attributes_report(server, cluster, {0: 1, 1291: 100, 10: 1000})
    assert_state(entity, "100", "W")

    await send_attributes_report(server, cluster, {0: 1, 1291: 99, 10: 1000})
    assert_state(entity, "99", "W")

    await send_attributes_report(server, cluster, {"ac_power_divisor": 10})
    await send_attributes_report(server, cluster, {0: 1, 1291: 1000, 10: 5000})
    assert_state(entity, "100", "W")

    await send_attributes_report(server, cluster, {0: 1, 1291: 99, 10: 5000})
    assert_state(entity, "9.9", "W")

    await send_attributes_report(server, cluster, {0: 1, 0x050D: 88, 10: 5000})
    assert entity.state.active_power_max == "8.8"


async def async_test_em_apparent_power(
    server: Server, cluster: Cluster, entity: ElectricalMeasurementEntity
) -> None:
    """Test electrical measurement Apparent Power sensor."""
    # update divisor cached value
    await send_attributes_report(server, cluster, {"ac_power_divisor": 1})
    await send_attributes_report(server, cluster, {0: 1, 0x050F: 100, 10: 1000})
    assert_state(entity, "100", "VA")

    await send_attributes_report(server, cluster, {0: 1, 0x050F: 99, 10: 1000})
    assert_state(entity, "99", "VA")

    await send_attributes_report(server, cluster, {"ac_power_divisor": 10})
    await send_attributes_report(server, cluster, {0: 1, 0x050F: 1000, 10: 5000})
    assert_state(entity, "100", "VA")

    await send_attributes_report(server, cluster, {0: 1, 0x050F: 99, 10: 5000})
    assert_state(entity, "9.9", "VA")


async def async_test_em_rms_current(
    server: Server, cluster: Cluster, entity: ElectricalMeasurementEntity
) -> None:
    """Test electrical measurement RMS Current sensor."""

    await send_attributes_report(server, cluster, {0: 1, 0x0508: 1234, 10: 1000})
    assert_state(entity, "1.2", "A")

    await send_attributes_report(server, cluster, {"ac_current_divisor": 10})
    await send_attributes_report(server, cluster, {0: 1, 0x0508: 236, 10: 1000})
    assert_state(entity, "23.6", "A")

    await send_attributes_report(server, cluster, {0: 1, 0x0508: 1236, 10: 1000})
    assert_state(entity, "124", "A")

    await send_attributes_report(server, cluster, {0: 1, 0x050A: 88, 10: 5000})
    assert entity.state.rms_current_max == "8.8"


async def async_test_em_rms_voltage(
    server: Server, cluster: Cluster, entity: ElectricalMeasurementEntity
) -> None:
    """Test electrical measurement RMS Voltage sensor."""

    await send_attributes_report(server, cluster, {0: 1, 0x0505: 1234, 10: 1000})
    assert_state(entity, "123", "V")

    await send_attributes_report(server, cluster, {0: 1, 0x0505: 234, 10: 1000})
    assert_state(entity, "23.4", "V")

    await send_attributes_report(server, cluster, {"ac_voltage_divisor": 100})
    await send_attributes_report(server, cluster, {0: 1, 0x0505: 2236, 10: 1000})
    assert_state(entity, "22.4", "V")

    await send_attributes_report(server, cluster, {0: 1, 0x0507: 888, 10: 5000})
    assert entity.state.rms_voltage_max == "8.9"


async def async_test_powerconfiguration(
    server: Server, cluster: Cluster, entity: BatteryEntity
) -> None:
    """Test powerconfiguration/battery sensor."""
    await send_attributes_report(server, cluster, {33: 98})
    assert_state(entity, "49", "%")
    assert entity.state.battery_voltage == 2.9
    assert entity.state.battery_quantity == 3
    assert entity.state.battery_size == "AAA"
    await send_attributes_report(server, cluster, {32: 20})
    assert entity.state.battery_voltage == 2.0


async def async_test_device_temperature(
    server: Server, cluster: Cluster, entity: SensorEntity
) -> None:
    """Test temperature sensor."""
    await send_attributes_report(server, cluster, {0: 2900})
    assert_state(entity, "29.0", "°C")


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
    ),
)
async def test_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
    cluster_id: int,
    entity_suffix: str,
    test_func: Callable[[Cluster, SensorEntity], Awaitable[None]],
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
    controller, server = connected_client_and_server
    zha_device = await device_joined(zigpy_device)
    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None

    entity_id = ENTITY_ID_PREFIX.format(entity_suffix)
    entity = get_entity(client_device, entity_id)

    await server.block_till_done()
    # test sensor associated logic
    await test_func(server, cluster, entity)


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> SensorEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]


def assert_state(entity: SensorEntity, state: Any, unit_of_measurement: str) -> None:
    """Check that the state is what is expected.

    This is used to ensure that the logic in each sensor class handled the
    attribute report it received correctly.
    """
    assert entity.state.state == state
    # assert entity.unit == unit_of_measurement TODO do we want these in zhaws or only in HA?


async def test_electrical_measurement_init(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
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
    controller, server = connected_client_and_server
    cluster = zigpy_device.endpoints[1].in_clusters[cluster_id]
    zha_device = await device_joined(zigpy_device)
    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity_id = find_entity_id(Platform.SENSOR, zha_device)
    assert entity_id is not None
    entity = get_entity(client_device, entity_id)

    await send_attributes_report(server, cluster, {0: 1, 1291: 100, 10: 1000})
    assert int(entity.state.state) == 100  # type: ignore

    cluster_handler = list(zha_device._endpoints.values())[0].all_cluster_handlers[
        "1:0x0b04"
    ]
    assert cluster_handler.ac_power_divisor == 1
    assert cluster_handler.ac_power_multiplier == 1

    # update power divisor
    await send_attributes_report(server, cluster, {0: 1, 1291: 20, 0x0403: 5, 10: 1000})
    assert cluster_handler.ac_power_divisor == 5
    assert cluster_handler.ac_power_multiplier == 1
    assert entity.state.state == "4.0"

    await send_attributes_report(
        server, cluster, {0: 1, 1291: 30, 0x0605: 10, 10: 1000}
    )
    assert cluster_handler.ac_power_divisor == 10
    assert cluster_handler.ac_power_multiplier == 1
    assert entity.state.state == "3.0"

    # update power multiplier
    await send_attributes_report(server, cluster, {0: 1, 1291: 20, 0x0402: 6, 10: 1000})
    assert cluster_handler.ac_power_divisor == 10
    assert cluster_handler.ac_power_multiplier == 6
    assert entity.state.state == "12.0"

    await send_attributes_report(
        server, cluster, {0: 1, 1291: 30, 0x0604: 20, 10: 1000}
    )
    assert cluster_handler.ac_power_divisor == 10
    assert cluster_handler.ac_power_multiplier == 20
    assert entity.state.state == "60.0"


@pytest.mark.parametrize(
    "cluster_id, unsupported_attributes, entity_ids, missing_entity_ids",
    (
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            {"apparent_power", "rms_voltage", "rms_current"},
            {"electrical_measurement"},
            {
                "electrical_measurement_apparent_power",
                "electrical_measurement_rms_voltage",
                "electrical_measurement_rms_current",
            },
        ),
        (
            homeautomation.ElectricalMeasurement.cluster_id,
            {"apparent_power", "rms_current"},
            {"electrical_measurement_rms_voltage", "electrical_measurement"},
            {
                "electrical_measurement_apparent_power",
                "electrical_measurement_rms_current",
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
                "smartenergy_metering",
            },
        ),
        (
            smartenergy.Metering.cluster_id,
            {"instantaneous_demand", "current_summ_delivered"},
            {},
            {
                "smartenergy_metering_summation_delivered",
                "smartenergy_metering",
            },
        ),
        (
            smartenergy.Metering.cluster_id,
            {},
            {
                "smartenergy_metering_summation_delivered",
                "smartenergy_metering",
            },
            {},
        ),
    ),
)
async def test_unsupported_attributes_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
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
    controller, server = connected_client_and_server
    zha_device = await device_joined(zigpy_device)
    await server.block_till_done()
    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None

    present_entity_ids = set(
        find_entity_ids(Platform.SENSOR, zha_device, omit=["lqi", "rssi"])
    )
    assert present_entity_ids == entity_ids
    assert missing_entity_ids not in present_entity_ids


@pytest.mark.parametrize(
    "raw_uom, raw_value, expected_state, expected_uom",
    (
        (
            1,
            12320,
            "1.23",
            "m³",
        ),
        (
            1,
            1232000,
            "123.20",
            "m³",
        ),
        (
            3,
            2340,
            "0.23",
            "100 ft³",
        ),
        (
            3,
            2360,
            "0.24",
            "100 ft³",
        ),
        (
            8,
            23660,
            "2.37",
            "kPa",
        ),
        (
            0,
            9366,
            "0.937",
            "kWh",
        ),
        (
            0,
            999,
            "0.1",
            "kWh",
        ),
        (
            0,
            10091,
            "1.009",
            "kWh",
        ),
        (
            0,
            10099,
            "1.01",
            "kWh",
        ),
        (
            0,
            100999,
            "10.1",
            "kWh",
        ),
        (
            0,
            100023,
            "10.002",
            "kWh",
        ),
        (
            0,
            102456,
            "10.246",
            "kWh",
        ),
    ),
)
async def test_se_summation_uom(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
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
    controller, server = connected_client_and_server
    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None

    entity = get_entity(client_device, entity_id)

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
    elec_measurement_zigpy_dev: ZigpyDevice,
    raw_measurement_type: int,
    expected_type: str,
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha electrical measurement sensor type."""

    entity_id = ENTITY_ID_PREFIX.format("electrical_measurement")
    zigpy_dev = elec_measurement_zigpy_dev
    zigpy_dev.endpoints[1].electrical_measurement.PLUGGED_ATTR_READS[
        "measurement_type"
    ] = raw_measurement_type

    controller, server = connected_client_and_server
    await device_joined(zigpy_dev)

    client_device: Optional[DeviceProxy] = controller.devices.get(zigpy_dev.ieee)
    assert client_device is not None

    entity = get_entity(client_device, entity_id)
    assert entity is not None
    assert entity.state.measurement_type == expected_type


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
    elec_measurement_zha_dev: Device,
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
    }
    for attr in all_attrs - supported_attributes:
        cluster.add_unsupported_attribute(attr)
    cluster.read_attributes.reset_mock()

    await entity.async_update()
    await zha_dev.controller.server.block_till_done()
    assert cluster.read_attributes.call_count == math.ceil(
        len(supported_attributes) / 5  # ZHA_CHANNEL_READS_PER_REQ
    )
    read_attrs = {
        a for call in cluster.read_attributes.call_args_list for a in call[0][0]
    }
    assert read_attrs == supported_attributes
