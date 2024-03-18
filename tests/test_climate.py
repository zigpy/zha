"""Test zha climate."""
from collections.abc import Awaitable, Callable
import logging
from typing import Optional
from unittest.mock import patch

import pytest
from slugify import slugify
import zhaquirks.sinope.thermostat
import zhaquirks.tuya.ts0601_trv
from zhaws.client.controller import Controller
from zhaws.client.model.types import SensorEntity, ThermostatEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.climate import (
    HVAC_MODE_2_SYSTEM,
    SEQ_OF_OPERATION,
    FanState,
)
from zhaws.server.platforms.registries import Platform
from zhaws.server.platforms.sensor import SinopeHVACAction, ThermostatHVACAction
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles
import zigpy.zcl.clusters
from zigpy.zcl.clusters.hvac import Thermostat
import zigpy.zcl.foundation as zcl_f

from .common import find_entity_id, send_attributes_report
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

_LOGGER = logging.getLogger(__name__)

CLIMATE = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Identify.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            zigpy.zcl.clusters.hvac.UserInterface.cluster_id,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id],
    }
}

CLIMATE_FAN = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Identify.cluster_id,
            zigpy.zcl.clusters.hvac.Fan.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            zigpy.zcl.clusters.hvac.UserInterface.cluster_id,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id],
    }
}

CLIMATE_SINOPE = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Identify.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            zigpy.zcl.clusters.hvac.UserInterface.cluster_id,
            65281,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id, 65281],
    },
    196: {
        SIG_EP_PROFILE: 0xC25D,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [zigpy.zcl.clusters.general.PowerConfiguration.cluster_id],
        SIG_EP_OUTPUT: [],
    },
}

CLIMATE_ZEN = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Identify.cluster_id,
            zigpy.zcl.clusters.hvac.Fan.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            zigpy.zcl.clusters.hvac.UserInterface.cluster_id,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id],
    }
}

CLIMATE_MOES = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Identify.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            zigpy.zcl.clusters.hvac.UserInterface.cluster_id,
            61148,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id],
    }
}
MANUF_SINOPE = "Sinope Technologies"
MANUF_ZEN = "Zen Within"
MANUF_MOES = "_TZE200_ckud7u2l"

ZCL_ATTR_PLUG = {
    "abs_min_heat_setpoint_limit": 800,
    "abs_max_heat_setpoint_limit": 3000,
    "abs_min_cool_setpoint_limit": 2000,
    "abs_max_cool_setpoint_limit": 4000,
    "ctrl_sequence_of_oper": Thermostat.ControlSequenceOfOperation.Cooling_and_Heating,
    "local_temperature": None,
    "max_cool_setpoint_limit": 3900,
    "max_heat_setpoint_limit": 2900,
    "min_cool_setpoint_limit": 2100,
    "min_heat_setpoint_limit": 700,
    "occupancy": 1,
    "occupied_cooling_setpoint": 2500,
    "occupied_heating_setpoint": 2200,
    "pi_cooling_demand": None,
    "pi_heating_demand": None,
    "running_mode": Thermostat.RunningMode.Off,
    "running_state": None,
    "system_mode": Thermostat.SystemMode.Off,
    "unoccupied_heating_setpoint": 2200,
    "unoccupied_cooling_setpoint": 2300,
}


@pytest.fixture
def device_climate_mock(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Callable[..., Device]:
    """Test regular thermostat device."""

    async def _dev(clusters, plug=None, manuf=None, quirk=None):
        if plug is None:
            plugged_attrs = ZCL_ATTR_PLUG
        else:
            plugged_attrs = {**ZCL_ATTR_PLUG, **plug}

        zigpy_device = zigpy_device_mock(clusters, manufacturer=manuf, quirk=quirk)
        zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
        zigpy_device.endpoints[1].thermostat.PLUGGED_ATTR_READS = plugged_attrs
        zha_device = await device_joined(zigpy_device)
        return zha_device

    return _dev


@pytest.fixture
async def device_climate(device_climate_mock):
    """Plain Climate device."""

    return await device_climate_mock(CLIMATE)


@pytest.fixture
async def device_climate_fan(device_climate_mock):
    """Test thermostat with fan device."""

    return await device_climate_mock(CLIMATE_FAN)


@pytest.fixture
@patch.object(
    zigpy.zcl.clusters.manufacturer_specific.ManufacturerSpecificCluster,
    "ep_attribute",
    "sinope_manufacturer_specific",
)
async def device_climate_sinope(device_climate_mock):
    """Sinope thermostat."""

    return await device_climate_mock(
        CLIMATE_SINOPE,
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )


@pytest.fixture
async def device_climate_zen(device_climate_mock):
    """Zen Within thermostat."""

    return await device_climate_mock(CLIMATE_ZEN, manuf=MANUF_ZEN)


@pytest.fixture
async def device_climate_moes(device_climate_mock):
    """MOES thermostat."""

    return await device_climate_mock(
        CLIMATE_MOES, manuf=MANUF_MOES, quirk=zhaquirks.tuya.ts0601_trv.MoesHY368_Type1
    )


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> ThermostatEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]


def get_sensor_entity(zha_dev: DeviceProxy, entity_id: str) -> SensorEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]


def test_sequence_mappings():
    """Test correct mapping between control sequence -> HVAC Mode -> Sysmode."""

    for hvac_modes in SEQ_OF_OPERATION.values():
        for hvac_mode in hvac_modes:
            assert hvac_mode in HVAC_MODE_2_SYSTEM
            assert Thermostat.SystemMode(HVAC_MODE_2_SYSTEM[hvac_mode]) is not None


async def test_climate_local_temperature(
    device_climate: Device,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test local temperature."""
    controller, server = connected_client_and_server
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None

    assert isinstance(entity, ThermostatEntity)
    assert entity.state.current_temperature is None

    await send_attributes_report(server, thrm_cluster, {0: 2100})
    assert entity.state.current_temperature == 21.0


async def test_climate_hvac_action_running_state(
    device_climate_sinope: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test hvac action via running state."""

    controller, server = connected_client_and_server
    thrm_cluster = device_climate_sinope.device.endpoints[1].thermostat
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_sinope)
    sensor_entity_id = find_entity_id(Platform.SENSOR, device_climate_sinope, "hvac")
    assert entity_id is not None
    assert sensor_entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_sinope.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    sensor_entity: SensorEntity = get_entity(client_device, sensor_entity_id)
    assert sensor_entity is not None
    assert isinstance(sensor_entity, SensorEntity)
    assert sensor_entity.class_name == SinopeHVACAction.__name__

    assert entity.state.hvac_action == "off"
    assert sensor_entity.state.state == "off"

    await send_attributes_report(
        server, thrm_cluster, {0x001E: Thermostat.RunningMode.Off}
    )
    assert entity.state.hvac_action == "off"
    assert sensor_entity.state.state == "off"

    await send_attributes_report(
        server, thrm_cluster, {0x001C: Thermostat.SystemMode.Auto}
    )
    assert entity.state.hvac_action == "idle"
    assert sensor_entity.state.state == "idle"

    await send_attributes_report(
        server, thrm_cluster, {0x001E: Thermostat.RunningMode.Cool}
    )
    assert entity.state.hvac_action == "cooling"
    assert sensor_entity.state.state == "cooling"

    await send_attributes_report(
        server, thrm_cluster, {0x001E: Thermostat.RunningMode.Heat}
    )
    assert entity.state.hvac_action == "heating"
    assert sensor_entity.state.state == "heating"

    await send_attributes_report(
        server, thrm_cluster, {0x001E: Thermostat.RunningMode.Off}
    )
    assert entity.state.hvac_action == "idle"
    assert sensor_entity.state.state == "idle"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_State_On}
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.state == "fan"


async def test_climate_hvac_action_running_state_zen(
    device_climate_zen: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test Zen hvac action via running state."""

    controller, server = connected_client_and_server
    thrm_cluster = device_climate_zen.device.endpoints[1].thermostat
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_zen)
    sensor_entity_id = find_entity_id(Platform.SENSOR, device_climate_zen, "hvac")
    assert entity_id is not None
    assert sensor_entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_zen.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    sensor_entity: SensorEntity = get_entity(client_device, sensor_entity_id)
    assert sensor_entity is not None
    assert isinstance(sensor_entity, SensorEntity)
    assert sensor_entity.class_name == ThermostatHVACAction.__name__

    assert entity.state.hvac_action is None
    assert sensor_entity.state.state is None

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Cool_2nd_Stage_On}
    )
    assert entity.state.hvac_action == "cooling"
    assert sensor_entity.state.state == "cooling"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_State_On}
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.state == "fan"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Heat_2nd_Stage_On}
    )
    assert entity.state.hvac_action == "heating"
    assert sensor_entity.state.state == "heating"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_2nd_Stage_On}
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.state == "fan"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Cool_State_On}
    )
    assert entity.state.hvac_action == "cooling"
    assert sensor_entity.state.state == "cooling"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_3rd_Stage_On}
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.state == "fan"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Heat_State_On}
    )
    assert entity.state.hvac_action == "heating"
    assert sensor_entity.state.state == "heating"

    await send_attributes_report(
        server, thrm_cluster, {0x0029: Thermostat.RunningState.Idle}
    )
    assert entity.state.hvac_action == "off"
    assert sensor_entity.state.state == "off"

    await send_attributes_report(
        server, thrm_cluster, {0x001C: Thermostat.SystemMode.Heat}
    )
    assert entity.state.hvac_action == "idle"
    assert sensor_entity.state.state == "idle"


async def test_climate_hvac_action_pi_demand(
    device_climate: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test hvac action based on pi_heating/cooling_demand attrs."""

    controller, server = connected_client_and_server
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_action is None

    await send_attributes_report(server, thrm_cluster, {0x0007: 10})
    assert entity.state.hvac_action == "cooling"

    await send_attributes_report(server, thrm_cluster, {0x0008: 20})
    assert entity.state.hvac_action == "heating"

    await send_attributes_report(server, thrm_cluster, {0x0007: 0})
    await send_attributes_report(server, thrm_cluster, {0x0008: 0})

    assert entity.state.hvac_action == "off"

    await send_attributes_report(
        server, thrm_cluster, {0x001C: Thermostat.SystemMode.Heat}
    )
    assert entity.state.hvac_action == "idle"

    await send_attributes_report(
        server, thrm_cluster, {0x001C: Thermostat.SystemMode.Cool}
    )
    assert entity.state.hvac_action == "idle"


@pytest.mark.parametrize(
    "sys_mode, hvac_mode",
    (
        (Thermostat.SystemMode.Auto, "heat_cool"),
        (Thermostat.SystemMode.Cool, "cool"),
        (Thermostat.SystemMode.Heat, "heat"),
        (Thermostat.SystemMode.Pre_cooling, "cool"),
        (Thermostat.SystemMode.Fan_only, "fan_only"),
        (Thermostat.SystemMode.Dry, "dry"),
    ),
)
async def test_hvac_mode(
    device_climate: Device,
    connected_client_and_server: tuple[Controller, Server],
    sys_mode,
    hvac_mode,
):
    """Test HVAC modee."""

    controller, server = connected_client_and_server
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "off"

    await send_attributes_report(server, thrm_cluster, {0x001C: sys_mode})
    assert entity.state.hvac_mode == hvac_mode

    await send_attributes_report(
        server, thrm_cluster, {0x001C: Thermostat.SystemMode.Off}
    )
    assert entity.state.hvac_mode == "off"

    await send_attributes_report(server, thrm_cluster, {0x001C: 0xFF})
    assert entity.state.hvac_mode is None


@pytest.mark.parametrize(
    "seq_of_op, modes",
    (
        (0xFF, {"off"}),
        (0x00, {"off", "cool"}),
        (0x01, {"off", "cool"}),
        (0x02, {"off", "heat"}),
        (0x03, {"off", "heat"}),
        (0x04, {"off", "cool", "heat", "heat_cool"}),
        (0x05, {"off", "cool", "heat", "heat_cool"}),
    ),
)
async def test_hvac_modes(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
    seq_of_op,
    modes,
):
    """Test HVAC modes from sequence of operations."""

    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE, {"ctrl_sequence_of_oper": seq_of_op}
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)
    assert set(entity.hvac_modes) == modes


@pytest.mark.parametrize(
    "sys_mode, preset, target_temp",
    (
        (Thermostat.SystemMode.Heat, None, 22),
        (Thermostat.SystemMode.Heat, "away", 16),
        (Thermostat.SystemMode.Cool, None, 25),
        (Thermostat.SystemMode.Cool, "away", 27),
    ),
)
async def test_target_temperature(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
    sys_mode,
    preset,
    target_temp,
):
    """Test target temperature property."""
    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE_SINOPE,
        {
            "occupied_cooling_setpoint": 2500,
            "occupied_heating_setpoint": 2200,
            "system_mode": sys_mode,
            "unoccupied_heating_setpoint": 1600,
            "unoccupied_cooling_setpoint": 2700,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)
    if preset:
        await controller.thermostats.set_preset_mode(entity, preset)
        await server.block_till_done()

    assert entity.state.target_temperature == target_temp


@pytest.mark.parametrize(
    "preset, unoccupied, target_temp",
    (
        (None, 1800, 17),
        ("away", 1800, 18),
        ("away", None, None),
    ),
)
async def test_target_temperature_high(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
    preset,
    unoccupied,
    target_temp,
):
    """Test target temperature high property."""

    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE_SINOPE,
        {
            "occupied_cooling_setpoint": 1700,
            "system_mode": Thermostat.SystemMode.Auto,
            "unoccupied_cooling_setpoint": unoccupied,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)
    if preset:
        await controller.thermostats.set_preset_mode(entity, preset)
        await server.block_till_done()

    assert entity.state.target_temperature_high == target_temp


@pytest.mark.parametrize(
    "preset, unoccupied, target_temp",
    (
        (None, 1600, 21),
        ("away", 1600, 16),
        ("away", None, None),
    ),
)
async def test_target_temperature_low(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
    preset,
    unoccupied,
    target_temp,
):
    """Test target temperature low property."""

    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE_SINOPE,
        {
            "occupied_heating_setpoint": 2100,
            "system_mode": Thermostat.SystemMode.Auto,
            "unoccupied_heating_setpoint": unoccupied,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)
    if preset:
        await controller.thermostats.set_preset_mode(entity, preset)
        await server.block_till_done()

    assert entity.state.target_temperature_low == target_temp


@pytest.mark.parametrize(
    "hvac_mode, sys_mode",
    (
        ("auto", None),
        ("cool", Thermostat.SystemMode.Cool),
        ("dry", None),
        ("fan_only", None),
        ("heat", Thermostat.SystemMode.Heat),
        ("heat_cool", Thermostat.SystemMode.Auto),
    ),
)
async def test_set_hvac_mode(
    device_climate: Device,
    connected_client_and_server: tuple[Controller, Server],
    hvac_mode,
    sys_mode,
):
    """Test setting hvac mode."""

    controller, server = connected_client_and_server
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "off"

    await controller.thermostats.set_hvac_mode(entity, hvac_mode)
    await server.block_till_done()

    if sys_mode is not None:
        assert entity.state.hvac_mode == hvac_mode
        assert thrm_cluster.write_attributes.call_count == 1
        assert thrm_cluster.write_attributes.call_args[0][0] == {
            "system_mode": sys_mode
        }
    else:
        assert thrm_cluster.write_attributes.call_count == 0
        assert entity.state.hvac_mode == "off"

    # turn off
    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_hvac_mode(entity, "off")
    await server.block_till_done()

    assert entity.state.hvac_mode == "off"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {
        "system_mode": Thermostat.SystemMode.Off
    }


async def test_preset_setting(
    device_climate_sinope: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test preset setting."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_sinope)
    thrm_cluster = device_climate_sinope.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_sinope.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.preset_mode == "none"

    # unsuccessful occupancy change
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x01\x00\x00")[0]
    ]

    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()

    assert entity.state.preset_mode == "none"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 0}

    # successful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]
    ]
    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()

    assert entity.state.preset_mode == "away"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 0}

    # unsuccessful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x01\x01\x01")[0]
    ]
    await controller.thermostats.set_preset_mode(entity, "none")
    await server.block_till_done()

    assert entity.state.preset_mode == "away"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 1}

    # successful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]
    ]
    await controller.thermostats.set_preset_mode(entity, "none")
    await server.block_till_done()

    assert entity.state.preset_mode == "none"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 1}


async def test_preset_setting_invalid(
    device_climate_sinope: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test invalid preset setting."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_sinope)
    thrm_cluster = device_climate_sinope.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_sinope.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.preset_mode == "none"
    await controller.thermostats.set_preset_mode(entity, "invalid_preset")
    await server.block_till_done()

    assert entity.state.preset_mode == "none"
    assert thrm_cluster.write_attributes.call_count == 0


async def test_set_temperature_hvac_mode(
    device_climate: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test setting HVAC mode in temperature service call."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "off"
    await controller.thermostats.set_temperature(entity, "heat_cool", 20)
    await server.block_till_done()

    assert entity.state.hvac_mode == "heat_cool"
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {
        "system_mode": Thermostat.SystemMode.Auto
    }


async def test_set_temperature_heat_cool(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
):
    """Test setting temperature service call in heating/cooling HVAC mode."""

    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE_SINOPE,
        {
            "occupied_cooling_setpoint": 2500,
            "occupied_heating_setpoint": 2000,
            "system_mode": Thermostat.SystemMode.Auto,
            "unoccupied_heating_setpoint": 1600,
            "unoccupied_cooling_setpoint": 2700,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "heat_cool"

    await controller.thermostats.set_temperature(entity, temperature=20)
    await server.block_till_done()

    assert entity.state.target_temperature_low == 20.0
    assert entity.state.target_temperature_high == 25.0
    assert thrm_cluster.write_attributes.await_count == 0

    await controller.thermostats.set_temperature(
        entity, target_temp_high=26, target_temp_low=19
    )
    await server.block_till_done()

    assert entity.state.target_temperature_low == 19.0
    assert entity.state.target_temperature_high == 26.0
    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_heating_setpoint": 1900
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "occupied_cooling_setpoint": 2600
    }

    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await controller.thermostats.set_temperature(
        entity, target_temp_high=30, target_temp_low=15
    )
    await server.block_till_done()

    assert entity.state.target_temperature_low == 15.0
    assert entity.state.target_temperature_high == 30.0
    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "unoccupied_heating_setpoint": 1500
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "unoccupied_cooling_setpoint": 3000
    }


async def test_set_temperature_heat(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
):
    """Test setting temperature service call in heating HVAC mode."""

    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE_SINOPE,
        {
            "occupied_cooling_setpoint": 2500,
            "occupied_heating_setpoint": 2000,
            "system_mode": Thermostat.SystemMode.Heat,
            "unoccupied_heating_setpoint": 1600,
            "unoccupied_cooling_setpoint": 2700,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "heat"

    await controller.thermostats.set_temperature(
        entity, target_temp_high=30, target_temp_low=15
    )
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 20.0
    assert thrm_cluster.write_attributes.await_count == 0

    await controller.thermostats.set_temperature(entity, temperature=21)
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 21.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_heating_setpoint": 2100
    }

    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await controller.thermostats.set_temperature(entity, temperature=22)
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 22.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "unoccupied_heating_setpoint": 2200
    }


async def test_set_temperature_cool(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
):
    """Test setting temperature service call in cooling HVAC mode."""

    controller, server = connected_client_and_server
    device_climate = await device_climate_mock(
        CLIMATE_SINOPE,
        {
            "occupied_cooling_setpoint": 2500,
            "occupied_heating_setpoint": 2000,
            "system_mode": Thermostat.SystemMode.Cool,
            "unoccupied_cooling_setpoint": 1600,
            "unoccupied_heating_setpoint": 2700,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "cool"

    await controller.thermostats.set_temperature(
        entity, target_temp_high=30, target_temp_low=15
    )
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 25.0
    assert thrm_cluster.write_attributes.await_count == 0

    await controller.thermostats.set_temperature(entity, temperature=21)
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 21.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_cooling_setpoint": 2100
    }

    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await controller.thermostats.set_temperature(entity, temperature=22)
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 22.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "unoccupied_cooling_setpoint": 2200
    }


async def test_set_temperature_wrong_mode(
    device_climate_mock: Callable[..., Device],
    connected_client_and_server: tuple[Controller, Server],
):
    """Test setting temperature service call for wrong HVAC mode."""

    controller, server = connected_client_and_server
    with patch.object(
        zigpy.zcl.clusters.manufacturer_specific.ManufacturerSpecificCluster,
        "ep_attribute",
        "sinope_manufacturer_specific",
    ):
        device_climate = await device_climate_mock(
            CLIMATE_SINOPE,
            {
                "occupied_cooling_setpoint": 2500,
                "occupied_heating_setpoint": 2000,
                "system_mode": Thermostat.SystemMode.Dry,
                "unoccupied_cooling_setpoint": 1600,
                "unoccupied_heating_setpoint": 2700,
            },
            manuf=MANUF_SINOPE,
        )
    entity_id = find_entity_id(Platform.CLIMATE, device_climate)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(device_climate.ieee)
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.hvac_mode == "dry"

    await controller.thermostats.set_temperature(entity, temperature=24)
    await server.block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature is None
    assert thrm_cluster.write_attributes.await_count == 0


async def test_occupancy_reset(
    device_climate_sinope: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test away preset reset."""
    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_sinope)
    thrm_cluster = device_climate_sinope.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_sinope.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.preset_mode == "none"

    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    assert entity.state.preset_mode == "away"

    await send_attributes_report(
        server, thrm_cluster, {"occupied_heating_setpoint": zigpy.types.uint16_t(1950)}
    )
    assert entity.state.preset_mode == "none"


async def test_fan_mode(
    device_climate_fan: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test fan mode."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_fan)
    thrm_cluster = device_climate_fan.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_fan.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert set(entity.fan_modes) == {FanState.AUTO, FanState.ON}
    assert entity.state.fan_mode == FanState.AUTO

    await send_attributes_report(
        server, thrm_cluster, {"running_state": Thermostat.RunningState.Fan_State_On}
    )
    assert entity.state.fan_mode == FanState.ON

    await send_attributes_report(
        server, thrm_cluster, {"running_state": Thermostat.RunningState.Idle}
    )
    assert entity.state.fan_mode == FanState.AUTO

    await send_attributes_report(
        server,
        thrm_cluster,
        {"running_state": Thermostat.RunningState.Fan_2nd_Stage_On},
    )
    assert entity.state.fan_mode == FanState.ON


async def test_set_fan_mode_not_supported(
    device_climate_fan: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test fan setting unsupported mode."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_fan)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_fan.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    await controller.thermostats.set_fan_mode(entity, FanState.LOW)
    await server.block_till_done()
    assert fan_cluster.write_attributes.await_count == 0


async def test_set_fan_mode(
    device_climate_fan: Device,
    connected_client_and_server: tuple[Controller, Server],
):
    """Test fan mode setting."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_fan)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_fan.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.fan_mode == FanState.AUTO

    await controller.thermostats.set_fan_mode(entity, FanState.ON)
    await server.block_till_done()

    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 4}

    fan_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_fan_mode(entity, FanState.AUTO)
    await server.block_till_done()
    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 5}


async def test_set_moes_preset(
    device_climate_moes: Device, connected_client_and_server: tuple[Controller, Server]
):
    """Test setting preset for moes trv."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_moes)
    thrm_cluster = device_climate_moes.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_moes.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    assert entity.state.preset_mode == "none"

    await controller.thermostats.set_preset_mode(entity, "away")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 0
    }

    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_preset_mode(entity, "Schedule")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 1
    }

    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_preset_mode(entity, "comfort")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 3
    }

    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_preset_mode(entity, "eco")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 4
    }

    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_preset_mode(entity, "boost")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 5
    }

    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_preset_mode(entity, "Complex")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 6
    }

    thrm_cluster.write_attributes.reset_mock()
    await controller.thermostats.set_preset_mode(entity, "none")
    await server.block_till_done()

    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }


async def test_set_moes_operation_mode(
    device_climate_moes: Device, connected_client_and_server: tuple[Controller, Server]
):
    """Test setting preset for moes trv."""

    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.CLIMATE, device_climate_moes)
    thrm_cluster = device_climate_moes.device.endpoints[1].thermostat
    assert entity_id is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(
        device_climate_moes.ieee
    )
    assert client_device is not None
    entity: ThermostatEntity = get_entity(client_device, entity_id)
    assert entity is not None
    assert isinstance(entity, ThermostatEntity)

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 0})

    assert entity.state.preset_mode == "away"

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 1})

    assert entity.state.preset_mode == "Schedule"

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 2})

    assert entity.state.preset_mode == "none"

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 3})

    assert entity.state.preset_mode == "comfort"

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 4})

    assert entity.state.preset_mode == "eco"

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 5})

    assert entity.state.preset_mode == "boost"

    await send_attributes_report(server, thrm_cluster, {"operation_preset": 6})

    assert entity.state.preset_mode == "Complex"
