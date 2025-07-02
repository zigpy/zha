"""Test zha climate."""

# pylint: disable=redefined-outer-name,too-many-lines

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch
import zoneinfo

from freezegun import freeze_time
import pytest
import zhaquirks.sinope.thermostat
from zhaquirks.sinope.thermostat import SinopeTechnologiesThermostatCluster
import zhaquirks.tuya.ts0601_trv
import zigpy.profiles
import zigpy.quirks
from zigpy.quirks.v2 import QuirkBuilder
import zigpy.zcl.clusters
from zigpy.zcl.clusters.hvac import Thermostat
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    send_attributes_report,
)
from zha.application import Platform
from zha.application.const import (
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_NONE,
    PRESET_SCHEDULE,
    PRESET_TEMP_MANUAL,
)
from zha.application.gateway import Gateway
from zha.application.platforms.climate import (
    HVAC_MODE_2_SYSTEM,
    SEQ_OF_OPERATION,
    Thermostat as ThermostatEntity,
    ZehnderThermostat,
)
from zha.application.platforms.climate.const import FanState
from zha.application.platforms.number import NumberConfigurationEntity
from zha.application.platforms.sensor import (
    Sensor,
    SinopeHVACAction,
    ThermostatHVACAction,
)
from zha.const import STATE_CHANGED
from zha.exceptions import ZHAException
from zha.zigbee.device import Device

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

CLIMATE_ZEHNDER = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Identify.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Identify.cluster_id],
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

CLIMATE_BECA = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SMART_PLUG,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.general.Groups.cluster_id,
            zigpy.zcl.clusters.general.Scenes.cluster_id,
            61148,
        ],
        SIG_EP_OUTPUT: [
            zigpy.zcl.clusters.general.Time.cluster_id,
            zigpy.zcl.clusters.general.Ota.cluster_id,
        ],
    }
}

CLIMATE_ZONNSMART = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.THERMOSTAT,
        SIG_EP_INPUT: [
            zigpy.zcl.clusters.general.Basic.cluster_id,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            zigpy.zcl.clusters.hvac.UserInterface.cluster_id,
            61148,
        ],
        SIG_EP_OUTPUT: [zigpy.zcl.clusters.general.Ota.cluster_id],
    }
}

MANUF_SINOPE = "Sinope Technologies"
MANUF_ZEN = "Zen Within"
MANUF_ZEHNDER = "ZEHNDER GROUP VAUX ANDIGNY      "
MANUF_MOES = "_TZE200_ckud7u2l"
MANUF_BECA = "_TZE200_b6wax7g0"
MANUF_ZONNSMART = "_TZE200_hue3yfsn"

ZCL_ATTR_PLUG = {
    "abs_min_heat_setpoint_limit": 800,
    "abs_max_heat_setpoint_limit": 3000,
    "abs_min_cool_setpoint_limit": 2000,
    "abs_max_cool_setpoint_limit": 4000,
    "ctrl_sequence_of_oper": Thermostat.ControlSequenceOfOperation.Cooling_and_Heating,
    "local_temperature": None,
    "local_temperature_calibration": 0,
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

ATTR_PRESET_MODE = "preset_mode"


async def device_climate_mock(
    zha_gateway: Gateway,
    endpoints: dict[int, dict[str, Any]],
    plug: dict[str, Any] | None = None,
    manuf: str | None = None,
    quirk: type[zigpy.quirks.CustomDevice] | None = None,
) -> Device:
    """Test regular thermostat device."""

    plugged_attrs = ZCL_ATTR_PLUG if plug is None else {**ZCL_ATTR_PLUG, **plug}
    zigpy_device = create_mock_zigpy_device(
        zha_gateway, endpoints, manufacturer=manuf, quirk=quirk
    )
    zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    zigpy_device.endpoints[1].thermostat.PLUGGED_ATTR_READS = plugged_attrs
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device


@patch.object(
    zigpy.zcl.clusters.manufacturer_specific.ManufacturerSpecificCluster,
    "ep_attribute",
    "sinope_manufacturer_specific",
)
async def device_climate_sinope(zha_gateway: Gateway):
    """Sinope thermostat."""

    return await device_climate_mock(
        zha_gateway,
        CLIMATE_SINOPE,
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )


def test_sequence_mappings():
    """Test correct mapping between control sequence -> HVAC Mode -> Sysmode."""

    for hvac_modes in SEQ_OF_OPERATION.values():
        for hvac_mode in hvac_modes:
            assert hvac_mode in HVAC_MODE_2_SYSTEM
            assert Thermostat.SystemMode(HVAC_MODE_2_SYSTEM[hvac_mode]) is not None


async def test_climate_local_temperature(
    zha_gateway: Gateway,
) -> None:
    """Test local temperature."""
    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    assert entity.state["current_temperature"] is None

    await send_attributes_report(zha_gateway, thrm_cluster, {0: 2100})
    assert entity.state["current_temperature"] == 21.0


async def test_climate_outdoor_temperature(
    zha_gateway: Gateway,
) -> None:
    """Test outdoor temperature."""
    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    assert entity.state["outdoor_temperature"] is None

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.outdoor_temperature.id: 2150},
    )
    assert entity.state["outdoor_temperature"] == 21.5


async def test_climate_hvac_action_running_state(
    zha_gateway: Gateway,
):
    """Test hvac action via running state."""
    dev_climate_sinope = await device_climate_sinope(zha_gateway)
    thrm_cluster = dev_climate_sinope.device.endpoints[1].thermostat

    entity: ThermostatEntity = get_entity(
        dev_climate_sinope, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    sensor_entity: SinopeHVACAction = get_entity(
        dev_climate_sinope, platform=Platform.SENSOR, entity_type=SinopeHVACAction
    )

    subscriber1 = MagicMock()
    subscriber2 = MagicMock()
    entity.on_event(STATE_CHANGED, subscriber1)
    sensor_entity.on_event(STATE_CHANGED, subscriber2)

    assert entity.state["hvac_action"] == "off"
    assert sensor_entity.state["state"] == "off"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001E: Thermostat.RunningMode.Off}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state["hvac_action"] == "off"
    assert sensor_entity.state["state"] == "off"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 0

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001C: Thermostat.SystemMode.Auto}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state["hvac_action"] == "idle"
    assert sensor_entity.state["state"] == "idle"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 1

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001E: Thermostat.RunningMode.Cool}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state["hvac_action"] == "cooling"
    assert sensor_entity.state["state"] == "cooling"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 2

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001E: Thermostat.RunningMode.Heat}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state["hvac_action"] == "heating"
    assert sensor_entity.state["state"] == "heating"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 3

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001E: Thermostat.RunningMode.Off}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state["hvac_action"] == "idle"
    assert sensor_entity.state["state"] == "idle"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 4

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_State_On}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state["hvac_action"] == "fan"
    assert sensor_entity.state["state"] == "fan"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 5


async def test_sinope_time(
    zha_gateway: Gateway,
):
    """Test hvac action via running state."""

    dev_climate_sinope = await device_climate_sinope(zha_gateway)
    mfg_cluster = dev_climate_sinope.device.endpoints[1].sinope_manufacturer_specific
    assert mfg_cluster is not None

    entity: ThermostatEntity = get_entity(
        dev_climate_sinope, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    entity._async_update_time = AsyncMock(wraps=entity._async_update_time)

    await asyncio.sleep(4600)

    write_attributes = mfg_cluster.write_attributes
    assert entity._async_update_time.await_count == 1
    assert write_attributes.await_count == 1
    assert "secs_since_2k" in write_attributes.mock_calls[0].args[0]

    write_attributes.reset_mock()

    # Default time zone of UTC
    with freeze_time("2000-01-02 00:00:00"):
        await entity._async_update_time()
        secs_since_2k = write_attributes.mock_calls[0].args[0]["secs_since_2k"]
        assert secs_since_2k == pytest.approx(60 * 60 * 24)

    write_attributes.reset_mock()

    # New time zone
    zha_gateway.config.local_timezone = zoneinfo.ZoneInfo("America/New_York")

    with freeze_time("2000-01-02 00:00:00"):
        await entity._async_update_time()
        secs_since_2k = write_attributes.mock_calls[0].args[0]["secs_since_2k"]
        assert secs_since_2k == pytest.approx(60 * 60 * 24 - 5 * 60 * 60)

    write_attributes.reset_mock()
    entity._async_update_time.reset_mock()

    entity.disable()

    assert entity.enabled is False

    await asyncio.sleep(4600)

    assert entity._async_update_time.await_count == 0
    assert mfg_cluster.write_attributes.await_count == 0

    entity.enable()

    assert entity.enabled is True

    await asyncio.sleep(4600)

    assert entity._async_update_time.await_count == 1
    assert mfg_cluster.write_attributes.await_count == 1

    write_attributes.reset_mock()
    entity._async_update_time.reset_mock()


async def test_climate_hvac_action_running_state_zen(
    zha_gateway: Gateway,
):
    """Test Zen hvac action via running state."""
    device_climate_zen = await device_climate_mock(
        zha_gateway, CLIMATE_ZEN, manuf=MANUF_ZEN
    )

    thrm_cluster = device_climate_zen.device.endpoints[1].thermostat

    entity: ThermostatEntity = get_entity(
        device_climate_zen, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    sensor_entity: Sensor = get_entity(
        device_climate_zen, platform=Platform.SENSOR, entity_type=ThermostatHVACAction
    )
    assert isinstance(sensor_entity, ThermostatHVACAction)

    assert entity.state["hvac_action"] is None
    assert sensor_entity.state["state"] is None

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Cool_2nd_Stage_On}
    )
    assert entity.state["hvac_action"] == "cooling"
    assert sensor_entity.state["state"] == "cooling"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_State_On}
    )
    assert entity.state["hvac_action"] == "fan"
    assert sensor_entity.state["state"] == "fan"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Heat_2nd_Stage_On}
    )
    assert entity.state["hvac_action"] == "heating"
    assert sensor_entity.state["state"] == "heating"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_2nd_Stage_On}
    )
    assert entity.state["hvac_action"] == "fan"
    assert sensor_entity.state["state"] == "fan"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Cool_State_On}
    )
    assert entity.state["hvac_action"] == "cooling"
    assert sensor_entity.state["state"] == "cooling"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_3rd_Stage_On}
    )
    assert entity.state["hvac_action"] == "fan"
    assert sensor_entity.state["state"] == "fan"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Heat_State_On}
    )
    assert entity.state["hvac_action"] == "heating"
    assert sensor_entity.state["state"] == "heating"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Idle}
    )
    assert entity.state["hvac_action"] == "off"
    assert sensor_entity.state["state"] == "off"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001C: Thermostat.SystemMode.Heat}
    )
    assert entity.state["hvac_action"] == "idle"
    assert sensor_entity.state["state"] == "idle"


async def test_climate_hvac_action_running_state_zehnder(
    zha_gateway: Gateway,
):
    """Test Zehnder hvac action via running state."""
    device_climate_zehnder = await device_climate_mock(
        zha_gateway, CLIMATE_ZEHNDER, manuf=MANUF_ZEHNDER
    )

    thrm_cluster = device_climate_zehnder.device.endpoints[1].thermostat

    entity: ThermostatEntity = get_entity(
        device_climate_zehnder, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_action"] is None

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Cool_2nd_Stage_On}
    )
    assert entity.state["hvac_action"] == "cooling"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_State_On}
    )
    assert entity.state["hvac_action"] == "fan"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Heat_2nd_Stage_On}
    )
    assert entity.state["hvac_action"] == "heating"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_2nd_Stage_On}
    )
    assert entity.state["hvac_action"] == "fan"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Cool_State_On}
    )
    assert entity.state["hvac_action"] == "cooling"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Fan_3rd_Stage_On}
    )
    assert entity.state["hvac_action"] == "fan"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Heat_State_On}
    )
    assert entity.state["hvac_action"] == "heating"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x0029: Thermostat.RunningState.Idle}
    )
    assert entity.state["hvac_action"] == "off"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001C: Thermostat.SystemMode.Heat}
    )
    assert entity.state["hvac_action"] == "idle"


@pytest.mark.parametrize(
    "hvac_mode, sys_mode",
    (
        ("heat", Thermostat.SystemMode.Auto),
        ("off", Thermostat.SystemMode.Off),
        ("heat_cool", None),
    ),
)
async def test_set_hvac_mode_zehnder(
    zha_gateway: Gateway,
    hvac_mode,
    sys_mode,
):
    """Test setting hvac mode."""
    device_climate_zehnder = await device_climate_mock(
        zha_gateway, CLIMATE_ZEHNDER, manuf=MANUF_ZEHNDER
    )

    thrm_cluster = device_climate_zehnder.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_zehnder, platform=Platform.CLIMATE, entity_type=ZehnderThermostat
    )

    assert entity.state["hvac_mode"] == "off"

    await entity.async_set_hvac_mode(hvac_mode)
    await zha_gateway.async_block_till_done()

    if sys_mode is not None:
        assert entity.state["hvac_mode"] == hvac_mode
        assert thrm_cluster.write_attributes.call_count == 1
        assert thrm_cluster.write_attributes.call_args[0][0] == {
            "system_mode": sys_mode
        }
    else:
        assert thrm_cluster.write_attributes.call_count == 0
        assert entity.state["hvac_mode"] == "off"

    # turn off
    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_hvac_mode("off")
    await zha_gateway.async_block_till_done()

    assert entity.state["hvac_mode"] == "off"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {
        "system_mode": Thermostat.SystemMode.Off
    }


async def test_climate_hvac_action_pi_demand(
    zha_gateway: Gateway,
):
    """Test hvac action based on pi_heating/cooling_demand attrs."""
    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_action"] is None

    await send_attributes_report(zha_gateway, thrm_cluster, {0x0007: 10})
    assert entity.state["hvac_action"] == "cooling"

    await send_attributes_report(zha_gateway, thrm_cluster, {0x0008: 20})
    assert entity.state["hvac_action"] == "heating"

    await send_attributes_report(zha_gateway, thrm_cluster, {0x0007: 0})
    await send_attributes_report(zha_gateway, thrm_cluster, {0x0008: 0})

    assert entity.state["hvac_action"] == "off"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001C: Thermostat.SystemMode.Heat}
    )
    assert entity.state["hvac_action"] == "idle"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001C: Thermostat.SystemMode.Cool}
    )
    assert entity.state["hvac_action"] == "idle"


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
    zha_gateway: Gateway,
    sys_mode,
    hvac_mode,
):
    """Test HVAC mode."""
    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "off"

    await send_attributes_report(zha_gateway, thrm_cluster, {0x001C: sys_mode})
    assert entity.state["hvac_mode"] == hvac_mode

    await send_attributes_report(
        zha_gateway, thrm_cluster, {0x001C: Thermostat.SystemMode.Off}
    )
    assert entity.state["hvac_mode"] == "off"

    await send_attributes_report(zha_gateway, thrm_cluster, {0x001C: 0xFF})
    assert entity.state["hvac_mode"] is None


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
async def test_hvac_modes(  # pylint: disable=unused-argument
    zha_gateway: Gateway,
    seq_of_op,
    modes,
):
    """Test HVAC modes from sequence of operations."""

    dev_climate = await device_climate_mock(
        zha_gateway, CLIMATE, {"ctrl_sequence_of_oper": seq_of_op}
    )
    entity: ThermostatEntity = get_entity(
        dev_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
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
    zha_gateway: Gateway,
    sys_mode,
    preset,
    target_temp,
):
    """Test target temperature property."""

    dev_climate = await device_climate_mock(
        zha_gateway,
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
    entity: ThermostatEntity = get_entity(
        dev_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    if preset:
        await entity.async_set_preset_mode(preset)
        await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature"] == target_temp


@pytest.mark.parametrize(
    "preset, unoccupied, target_temp",
    (
        (None, 1800, 17),
        ("away", 1800, 18),
        ("away", None, None),
    ),
)
async def test_target_temperature_high(
    zha_gateway: Gateway,
    preset,
    unoccupied,
    target_temp,
):
    """Test target temperature high property."""

    dev_climate = await device_climate_mock(
        zha_gateway,
        CLIMATE_SINOPE,
        {
            "occupied_cooling_setpoint": 1700,
            "system_mode": Thermostat.SystemMode.Auto,
            "unoccupied_cooling_setpoint": unoccupied,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity: ThermostatEntity = get_entity(
        dev_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    if preset:
        await entity.async_set_preset_mode(preset)
        await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_high"] == target_temp


@pytest.mark.parametrize(
    "preset, unoccupied, target_temp",
    (
        (None, 1600, 21),
        ("away", 1600, 16),
        ("away", None, None),
    ),
)
async def test_target_temperature_low(
    zha_gateway: Gateway,
    preset,
    unoccupied,
    target_temp,
):
    """Test target temperature low property."""

    dev_climate = await device_climate_mock(
        zha_gateway,
        CLIMATE_SINOPE,
        {
            "occupied_heating_setpoint": 2100,
            "system_mode": Thermostat.SystemMode.Auto,
            "unoccupied_heating_setpoint": unoccupied,
        },
        manuf=MANUF_SINOPE,
        quirk=zhaquirks.sinope.thermostat.SinopeTechnologiesThermostat,
    )
    entity: ThermostatEntity = get_entity(
        dev_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    if preset:
        await entity.async_set_preset_mode(preset)
        await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] == target_temp


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
    zha_gateway: Gateway,
    hvac_mode,
    sys_mode,
):
    """Test setting hvac mode."""

    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "off"

    await entity.async_set_hvac_mode(hvac_mode)
    await zha_gateway.async_block_till_done()

    if sys_mode is not None:
        assert entity.state["hvac_mode"] == hvac_mode
        assert thrm_cluster.write_attributes.call_count == 1
        assert thrm_cluster.write_attributes.call_args[0][0] == {
            "system_mode": sys_mode
        }
    else:
        assert thrm_cluster.write_attributes.call_count == 0
        assert entity.state["hvac_mode"] == "off"

    # turn off
    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_hvac_mode("off")
    await zha_gateway.async_block_till_done()

    assert entity.state["hvac_mode"] == "off"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {
        "system_mode": Thermostat.SystemMode.Off
    }


async def test_preset_setting(
    zha_gateway: Gateway,
):
    """Test preset setting."""
    dev_climate_sinope = await device_climate_sinope(zha_gateway)
    thrm_cluster = dev_climate_sinope.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        dev_climate_sinope, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["preset_mode"] == "none"

    # unsuccessful occupancy change
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse(
            [
                zcl_f.WriteAttributesStatusRecord(
                    status=zcl_f.Status.FAILURE,
                    attrid=SinopeTechnologiesThermostatCluster.AttributeDefs.set_occupancy.id,  # pylint: disable=no-member
                )
            ]
        )
    ]

    with pytest.raises(ZHAException):
        await entity.async_set_preset_mode("away")
        await zha_gateway.async_block_till_done()

    assert entity.state["preset_mode"] == "none"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 0}

    # successful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]
    ]
    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()

    assert entity.state["preset_mode"] == "away"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 0}

    # unsuccessful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse(
            [
                zcl_f.WriteAttributesStatusRecord(
                    status=zcl_f.Status.FAILURE,
                    attrid=SinopeTechnologiesThermostatCluster.AttributeDefs.set_occupancy.id,  # pylint: disable=no-member
                )
            ]
        )
    ]

    with pytest.raises(ZHAException):
        # unsuccessful occupancy change
        await entity.async_set_preset_mode("none")
        await zha_gateway.async_block_till_done()

    assert entity.state["preset_mode"] == "away"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 1}

    # successful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]
    ]

    await entity.async_set_preset_mode("none")
    await zha_gateway.async_block_till_done()

    assert entity.state["preset_mode"] == "none"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 1}


async def test_preset_setting_invalid(
    zha_gateway: Gateway,
):
    """Test invalid preset setting."""
    dev_climate_sinope = await device_climate_sinope(zha_gateway)
    thrm_cluster = dev_climate_sinope.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        dev_climate_sinope, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["preset_mode"] == "none"
    await entity.async_set_preset_mode("invalid_preset")
    await zha_gateway.async_block_till_done()

    assert entity.state["preset_mode"] == "none"
    assert thrm_cluster.write_attributes.call_count == 0


async def test_set_temperature_hvac_mode(
    zha_gateway: Gateway,
):
    """Test setting HVAC mode in temperature service call."""

    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "off"
    await entity.async_set_temperature(hvac_mode="heat_cool", temperature=20)
    await zha_gateway.async_block_till_done()

    assert entity.state["hvac_mode"] == "heat_cool"
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {
        "system_mode": Thermostat.SystemMode.Auto
    }


async def test_set_temperature_heat_cool(
    zha_gateway: Gateway,
):
    """Test setting temperature service call in heating/cooling HVAC mode."""

    device_climate = await device_climate_mock(
        zha_gateway,
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
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "heat_cool"

    await entity.async_set_temperature(temperature=20)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] == 20.0
    assert entity.state["target_temperature_high"] == 25.0
    assert thrm_cluster.write_attributes.await_count == 0

    await entity.async_set_temperature(target_temp_high=26, target_temp_low=19)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] == 19.0
    assert entity.state["target_temperature_high"] == 26.0
    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_heating_setpoint": 1900
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "occupied_cooling_setpoint": 2600
    }

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await entity.async_set_temperature(target_temp_high=30, target_temp_low=15)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] == 15.0
    assert entity.state["target_temperature_high"] == 30.0
    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "unoccupied_heating_setpoint": 1500
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "unoccupied_cooling_setpoint": 3000
    }


async def test_set_temperature_heat(
    zha_gateway: Gateway,
):
    """Test setting temperature service call in heating HVAC mode."""

    device_climate = await device_climate_mock(
        zha_gateway,
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
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "heat"

    await entity.async_set_temperature(target_temp_high=30, target_temp_low=15)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] == 20.0
    assert thrm_cluster.write_attributes.await_count == 0

    await entity.async_set_temperature(temperature=21)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] == 21.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_heating_setpoint": 2100
    }

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await entity.async_set_temperature(temperature=22)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] == 22.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "unoccupied_heating_setpoint": 2200
    }


async def test_set_temperature_cool(
    zha_gateway: Gateway,
):
    """Test setting temperature service call in cooling HVAC mode."""

    device_climate = await device_climate_mock(
        zha_gateway,
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
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "cool"

    await entity.async_set_temperature(target_temp_high=30, target_temp_low=15)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] == 25.0
    assert thrm_cluster.write_attributes.await_count == 0

    await entity.async_set_temperature(temperature=21)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] == 21.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_cooling_setpoint": 2100
    }

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await entity.async_set_temperature(temperature=22)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] == 22.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "unoccupied_cooling_setpoint": 2200
    }


async def test_set_temperature_wrong_mode(
    zha_gateway: Gateway,
):
    """Test setting temperature service call for wrong HVAC mode."""

    with patch.object(
        zigpy.zcl.clusters.manufacturer_specific.ManufacturerSpecificCluster,
        "ep_attribute",
        "sinope_manufacturer_specific",
    ):
        device_climate = await device_climate_mock(
            zha_gateway,
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
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["hvac_mode"] == "dry"

    await entity.async_set_temperature(temperature=24)
    await zha_gateway.async_block_till_done()

    assert entity.state["target_temperature_low"] is None
    assert entity.state["target_temperature_high"] is None
    assert entity.state["target_temperature"] is None
    assert thrm_cluster.write_attributes.await_count == 0


async def test_occupancy_reset(
    zha_gateway: Gateway,
):
    """Test away preset reset."""
    dev_climate_sinope = await device_climate_sinope(zha_gateway)
    thrm_cluster = dev_climate_sinope.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        dev_climate_sinope, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["preset_mode"] == "none"

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    assert entity.state["preset_mode"] == "away"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {"occupied_heating_setpoint": zigpy.types.uint16_t(1950)},
    )
    assert entity.state["preset_mode"] == "none"


async def test_fan_mode(
    zha_gateway: Gateway,
):
    """Test fan mode."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    thrm_cluster = device_climate_fan.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert set(entity.fan_modes) == {FanState.AUTO, FanState.ON}
    assert entity.state["fan_mode"] == FanState.AUTO

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {"running_state": Thermostat.RunningState.Fan_State_On},
    )
    assert entity.state["fan_mode"] == FanState.ON

    await send_attributes_report(
        zha_gateway, thrm_cluster, {"running_state": Thermostat.RunningState.Idle}
    )
    assert entity.state["fan_mode"] == FanState.AUTO

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {"running_state": Thermostat.RunningState.Fan_2nd_Stage_On},
    )
    assert entity.state["fan_mode"] == FanState.ON


async def test_set_fan_mode_not_supported(
    zha_gateway: Gateway,
):
    """Test fan setting unsupported mode."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await entity.async_set_fan_mode(FanState.LOW)
    await zha_gateway.async_block_till_done()
    assert fan_cluster.write_attributes.await_count == 0


async def test_set_fan_mode(
    zha_gateway: Gateway,
):
    """Test fan mode setting."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["fan_mode"] == FanState.AUTO

    await entity.async_set_fan_mode(FanState.ON)
    await zha_gateway.async_block_till_done()

    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 4}

    fan_cluster.write_attributes.reset_mock()
    await entity.async_set_fan_mode(FanState.AUTO)
    await zha_gateway.async_block_till_done()
    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 5}


async def test_set_moes_preset(zha_gateway: Gateway):
    """Test setting preset for moes trv."""

    device_climate_moes = await device_climate_mock(
        zha_gateway,
        CLIMATE_MOES,
        manuf=MANUF_MOES,
        quirk=zhaquirks.tuya.ts0601_trv.MoesHY368_Type1,
    )
    thrm_cluster = device_climate_moes.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_moes, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state["preset_mode"] == "none"

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 0
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("Schedule")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 1
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("comfort")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 3
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("eco")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 4
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("boost")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 5
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("Complex")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 6
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("none")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 2
    }


async def test_set_moes_operation_mode(zha_gateway: Gateway):
    """Test setting preset for moes trv."""
    device_climate_moes = await device_climate_mock(
        zha_gateway,
        CLIMATE_MOES,
        manuf=MANUF_MOES,
        quirk=zhaquirks.tuya.ts0601_trv.MoesHY368_Type1,
    )
    thrm_cluster = device_climate_moes.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_moes, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 0})

    assert entity.state["preset_mode"] == "away"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 1})

    assert entity.state["preset_mode"] == "Schedule"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 2})

    assert entity.state["preset_mode"] == "none"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 3})

    assert entity.state["preset_mode"] == "comfort"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 4})

    assert entity.state["preset_mode"] == "eco"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 5})

    assert entity.state["preset_mode"] == "boost"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 6})

    assert entity.state["preset_mode"] == "Complex"


# Device is running an energy-saving mode
PRESET_ECO = "eco"


@pytest.mark.parametrize(
    ("preset_attr", "preset_mode"),
    [
        (0, PRESET_AWAY),
        (1, PRESET_SCHEDULE),
        # (2, PRESET_NONE),  # TODO: why does this not work?
        (4, PRESET_ECO),
        (5, PRESET_BOOST),
        (7, PRESET_TEMP_MANUAL),
    ],
)
async def test_beca_operation_mode_update(
    zha_gateway: Gateway,
    preset_attr: int,
    preset_mode: str,
) -> None:
    """Test beca trv operation mode attribute update."""
    device_climate_beca = await device_climate_mock(
        zha_gateway,
        CLIMATE_BECA,
        manuf=MANUF_BECA,
        quirk=zhaquirks.tuya.ts0601_trv.MoesHY368_Type1new,
    )
    thrm_cluster = device_climate_beca.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_beca, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    # Test sending an attribute report
    await send_attributes_report(
        zha_gateway, thrm_cluster, {"operation_preset": preset_attr}
    )

    assert entity.state[ATTR_PRESET_MODE] == preset_mode

    await entity.async_set_preset_mode(preset_mode)
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.mock_calls == [
        call(
            {"operation_preset": preset_attr},
            manufacturer=device_climate_beca.manufacturer_code,
        )
    ]


async def test_set_zonnsmart_preset(zha_gateway: Gateway) -> None:
    """Test setting preset from homeassistant for zonnsmart trv."""
    device_climate_zonnsmart = await device_climate_mock(
        zha_gateway,
        CLIMATE_ZONNSMART,
        manuf=MANUF_ZONNSMART,
        quirk=zhaquirks.tuya.ts0601_trv.ZonnsmartTV01_ZG,
    )
    thrm_cluster = device_climate_zonnsmart.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_zonnsmart,
        platform=Platform.CLIMATE,
        entity_type=ThermostatEntity,
    )

    assert entity.state[ATTR_PRESET_MODE] == PRESET_NONE

    await entity.async_set_preset_mode(PRESET_SCHEDULE)
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 0
    }

    thrm_cluster.write_attributes.reset_mock()

    await entity.async_set_preset_mode("holiday")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 1
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 3
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode("frost protect")
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 2
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 1
    }
    assert thrm_cluster.write_attributes.call_args_list[1][0][0] == {
        "operation_preset": 4
    }

    thrm_cluster.write_attributes.reset_mock()
    await entity.async_set_preset_mode(PRESET_NONE)
    await zha_gateway.async_block_till_done()

    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "operation_preset": 1
    }


async def test_set_zonnsmart_operation_mode(zha_gateway: Gateway) -> None:
    """Test setting preset from trv for zonnsmart trv."""
    device_climate_zonnsmart = await device_climate_mock(
        zha_gateway,
        CLIMATE_ZONNSMART,
        manuf=MANUF_ZONNSMART,
        quirk=zhaquirks.tuya.ts0601_trv.ZonnsmartTV01_ZG,
    )
    thrm_cluster = device_climate_zonnsmart.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate_zonnsmart,
        platform=Platform.CLIMATE,
        entity_type=ThermostatEntity,
    )

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 0})

    assert entity.state[ATTR_PRESET_MODE] == PRESET_SCHEDULE

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 1})

    assert entity.state[ATTR_PRESET_MODE] == PRESET_NONE

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 2})

    assert entity.state[ATTR_PRESET_MODE] == "holiday"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 3})

    assert entity.state[ATTR_PRESET_MODE] == "holiday"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 4})

    assert entity.state[ATTR_PRESET_MODE] == "frost protect"


async def test_thermostat_default_local_temperature_calibration_config(
    zha_gateway: Gateway,
) -> None:
    """Test that a default local temperature calibration config gets attached to a thermostat entity."""

    zha_device = await device_climate_mock(zha_gateway, CLIMATE)

    assert zha_device.model == "FakeModel"
    assert zha_device.manufacturer == "unk_manufacturer"

    local_temperature_calibration_entity = zha_device.platform_entities[
        (
            Platform.NUMBER,
            "00:0d:6f:00:0a:90:69:e7-1-513-local_temperature_calibration",
        )
    ]
    assert local_temperature_calibration_entity
    assert isinstance(local_temperature_calibration_entity, NumberConfigurationEntity)
    assert local_temperature_calibration_entity.info_object.native_min_value == -2.5
    assert local_temperature_calibration_entity.info_object.native_max_value == 2.5
    assert local_temperature_calibration_entity.info_object.native_step == 0.1
    assert local_temperature_calibration_entity._multiplier == 0.1


async def test_thermostat_quirkv2_local_temperature_calibration_config_overwrite(
    zha_gateway: Gateway,
) -> None:
    """Test that a quirk v2 local temperature calibration config overwrites the default one."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway, CLIMATE, manufacturer="unk_manufacturer", model="FakeModel"
    )
    zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    zigpy_device.endpoints[1].thermostat.PLUGGED_ATTR_READS = ZCL_ATTR_PLUG

    (
        QuirkBuilder("unk_manufacturer", "FakeModel", zigpy.quirks._DEVICE_REGISTRY)
        # Local temperature calibration.
        .number(
            Thermostat.AttributeDefs.local_temperature_calibration.name,
            zigpy.zcl.clusters.hvac.Thermostat.cluster_id,
            min_value=-5,
            max_value=5,
            step=0.1,
            multiplier=0.1,
            translation_key="local_temperature_calibration",
            fallback_name="Local temperature offset",
        )
        .add_to_registry()
    )

    zigpy_device = zigpy.quirks._DEVICE_REGISTRY.get_device(zigpy_device)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    assert zha_device.model == "FakeModel"
    assert zha_device.manufacturer == "unk_manufacturer"

    local_temperature_calibration_entity = zha_device.platform_entities[
        (Platform.NUMBER, "00:0d:6f:00:0a:90:69:e7-1-local_temperature_calibration")
    ]
    assert local_temperature_calibration_entity
    assert isinstance(local_temperature_calibration_entity, NumberConfigurationEntity)
    assert local_temperature_calibration_entity.info_object.native_min_value == -5.0
    assert local_temperature_calibration_entity.info_object.native_max_value == 5.0
    assert local_temperature_calibration_entity.info_object.native_step == 0.1
    assert local_temperature_calibration_entity._multiplier == 0.1
