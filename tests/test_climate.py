"""Test zha climate."""

# pylint: disable=redefined-outer-name,too-many-lines

import asyncio
from collections.abc import Iterator
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, call, patch
import zoneinfo

from freezegun import freeze_time
import pytest
from zhaquirks.legacy import CustomDevice
import zhaquirks.sinope.thermostat
from zhaquirks.sinope.thermostat import SinopeTechnologiesThermostatCluster
import zhaquirks.tuya.ts0601_trv
import zigpy.profiles
from zigpy.typing import UNDEFINED
import zigpy.zcl.clusters
from zigpy.zcl.clusters.hvac import FanMode, FanModeSequence, SeqMode, Thermostat
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
    zigpy_device_from_json,
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
from zha.application.platforms import PlatformEntity
from zha.application.platforms.climate import (
    HVAC_MODE_2_SYSTEM,
    SEQ_OF_OPERATION,
    Thermostat as ThermostatEntity,
    ZehnderThermostat,
)
from zha.application.platforms.climate.const import SEQ_FAN_MODES, FanState, HVACMode
from zha.application.platforms.number import NumberConfigurationEntity
from zha.application.platforms.sensor import (
    Sensor,
    SinopeHVACAction,
    ThermostatHVACAction,
)
from zha.const import STATE_CHANGED
from zha.exceptions import ZHAException
from zha.quirks import (
    THERMOSTAT_FAN_ONLY_HVAC,
    THERMOSTAT_WEEKLY_SCHEDULE,
    DeviceMatch,
    DeviceRegistry,
    ModelInfo,
)
from zha.zigbee.device import Device
from zha.zigbee.weekly_schedule import (
    Transition,
    WeeklyScheduleCapabilities,
    WeeklyScheduleProvider,
    WriteAcknowledgement,
    ZclWeeklySchedule,
)

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
    quirk: type[CustomDevice] | None = None,
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
    assert entity.state.current_temperature is None

    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.local_temperature: 2100}
    )
    assert entity.state.current_temperature == 21.0


async def test_climate_outdoor_temperature(
    zha_gateway: Gateway,
) -> None:
    """Test outdoor temperature."""
    device_climate = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = device_climate.device.endpoints[1].thermostat
    entity: ThermostatEntity = get_entity(
        device_climate, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    assert entity.state.outdoor_temperature is None

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.outdoor_temperature: 2150},
    )
    assert entity.state.outdoor_temperature == 21.5


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

    assert entity.state.hvac_action == "off"
    assert sensor_entity.state.native_value == "off"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_mode: Thermostat.RunningMode.Off},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state.hvac_action == "off"
    assert sensor_entity.state.native_value == "off"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 0

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.system_mode: Thermostat.SystemMode.Auto},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state.hvac_action == "idle"
    assert sensor_entity.state.native_value == "idle"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 1

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_mode: Thermostat.RunningMode.Cool},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state.hvac_action == "cooling"
    assert sensor_entity.state.native_value == "cooling"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 2

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_mode: Thermostat.RunningMode.Heat},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state.hvac_action == "heating"
    assert sensor_entity.state.native_value == "heating"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 3

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_mode: Thermostat.RunningMode.Off},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state.hvac_action == "idle"
    assert sensor_entity.state.native_value == "idle"
    assert len(subscriber1.mock_calls) == len(subscriber2.mock_calls) == 4

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_State_On},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.native_value == "fan"
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

    # No configured timezone (local_timezone is None): falls back to UTC.
    assert zha_gateway.config.local_timezone is None
    with freeze_time("2000-01-02 00:00:00"):
        await entity._async_update_time()
        secs_since_2k = write_attributes.mock_calls[0].args[0]["secs_since_2k"]
        assert secs_since_2k == pytest.approx(60 * 60 * 24)

    write_attributes.reset_mock()

    # New time zone
    zha_gateway.update_local_timezone(zoneinfo.ZoneInfo("America/New_York"))

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

    assert entity.state.hvac_action is None
    assert sensor_entity.state.native_value is None

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Cool_2nd_Stage_On
        },
    )
    assert entity.state.hvac_action == "cooling"
    assert sensor_entity.state.native_value == "cooling"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_State_On},
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.native_value == "fan"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Heat_2nd_Stage_On
        },
    )
    assert entity.state.hvac_action == "heating"
    assert sensor_entity.state.native_value == "heating"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_2nd_Stage_On
        },
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.native_value == "fan"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Cool_State_On},
    )
    assert entity.state.hvac_action == "cooling"
    assert sensor_entity.state.native_value == "cooling"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_3rd_Stage_On
        },
    )
    assert entity.state.hvac_action == "fan"
    assert sensor_entity.state.native_value == "fan"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Heat_State_On},
    )
    assert entity.state.hvac_action == "heating"
    assert sensor_entity.state.native_value == "heating"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Idle},
    )
    assert entity.state.hvac_action == "off"
    assert sensor_entity.state.native_value == "off"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.system_mode: Thermostat.SystemMode.Heat},
    )
    assert entity.state.hvac_action == "idle"
    assert sensor_entity.state.native_value == "idle"


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

    assert entity.state.hvac_action is None

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Cool_2nd_Stage_On
        },
    )
    assert entity.state.hvac_action == "cooling"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_State_On},
    )
    assert entity.state.hvac_action == "fan"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Heat_2nd_Stage_On
        },
    )
    assert entity.state.hvac_action == "heating"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_2nd_Stage_On
        },
    )
    assert entity.state.hvac_action == "fan"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Cool_State_On},
    )
    assert entity.state.hvac_action == "cooling"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {
            Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Fan_3rd_Stage_On
        },
    )
    assert entity.state.hvac_action == "fan"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Heat_State_On},
    )
    assert entity.state.hvac_action == "heating"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.running_state: Thermostat.RunningState.Idle},
    )
    assert entity.state.hvac_action == "off"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.system_mode: Thermostat.SystemMode.Heat},
    )
    assert entity.state.hvac_action == "idle"


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

    assert entity.state.hvac_mode == "off"

    await entity.async_set_hvac_mode(hvac_mode)
    await zha_gateway.async_block_till_done()

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
    await entity.async_set_hvac_mode("off")
    await zha_gateway.async_block_till_done()

    assert entity.state.hvac_mode == "off"
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

    assert entity.state.hvac_action is None

    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.pi_cooling_demand: 10}
    )
    assert entity.state.hvac_action == "cooling"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.pi_heating_demand: 20}
    )
    assert entity.state.hvac_action == "heating"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.pi_cooling_demand: 0}
    )
    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.pi_heating_demand: 0}
    )

    assert entity.state.hvac_action == "off"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.system_mode: Thermostat.SystemMode.Heat},
    )
    assert entity.state.hvac_action == "idle"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.system_mode: Thermostat.SystemMode.Cool},
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

    assert entity.state.hvac_mode == "off"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.system_mode: sys_mode}
    )
    assert entity.state.hvac_mode == hvac_mode

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {Thermostat.AttributeDefs.system_mode: Thermostat.SystemMode.Off},
    )
    assert entity.state.hvac_mode == "off"

    await send_attributes_report(
        zha_gateway, thrm_cluster, {Thermostat.AttributeDefs.system_mode: 0xFF}
    )
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


async def test_weekly_schedule_adds_auto_mode(
    zha_gateway: Gateway,
) -> None:
    """Expose and set Auto only for heating-only thermostats with schedules."""
    device = await device_climate_mock(
        zha_gateway,
        CLIMATE,
        plug={
            "ctrl_sequence_of_oper": Thermostat.ControlSequenceOfOperation.Heating_Only
        },
    )
    entity: ThermostatEntity = get_entity(
        device, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    cluster = device.device.endpoints[1].thermostat

    assert HVACMode.AUTO not in entity.hvac_modes
    with patch.object(device, "weekly_schedule", return_value=object()):
        assert HVACMode.AUTO in entity.hvac_modes
        await entity.async_set_hvac_mode(HVACMode.AUTO)
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.call_args[0][0] == {
            "system_mode": Thermostat.SystemMode.Auto
        }

        await send_attributes_report(
            zha_gateway, cluster, {0x001C: Thermostat.SystemMode.Auto}
        )
        assert entity.state.hvac_mode == HVACMode.AUTO


@pytest.mark.parametrize(
    ("preset", "target", "attribute"),
    (
        (PRESET_NONE, 21, "occupied_heating_setpoint"),
        (PRESET_AWAY, 16, "unoccupied_heating_setpoint"),
    ),
)
async def test_weekly_schedule_auto_temperature(
    zha_gateway: Gateway, preset: str, target: int, attribute: str
) -> None:
    """Auto reports and writes the appropriate heating target."""
    device = await device_climate_mock(
        zha_gateway,
        CLIMATE,
        plug={
            "ctrl_sequence_of_oper": Thermostat.ControlSequenceOfOperation.Heating_Only,
            "system_mode": Thermostat.SystemMode.Auto,
            "occupied_heating_setpoint": 2100,
            "unoccupied_heating_setpoint": 1600,
        },
    )
    entity: ThermostatEntity = get_entity(
        device, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    cluster = device.device.endpoints[1].thermostat
    entity._preset = preset

    with patch.object(device, "weekly_schedule", return_value=object()):
        assert entity.state.hvac_mode == HVACMode.AUTO
        assert entity.state.target_temperature == target
        await entity.async_set_temperature(temperature=22)
        await zha_gateway.async_block_till_done()

        assert entity.state.target_temperature == 22
        assert cluster.write_attributes.call_args.args[0] == {attribute: 2200}


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

    assert entity.state.hvac_mode == "off"

    await entity.async_set_hvac_mode(hvac_mode)
    await zha_gateway.async_block_till_done()

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
    await entity.async_set_hvac_mode("off")
    await zha_gateway.async_block_till_done()

    assert entity.state.hvac_mode == "off"
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

    assert entity.state.preset_mode == "none"

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

    assert entity.state.preset_mode == "none"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 0}

    # successful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]
    ]
    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()

    assert entity.state.preset_mode == "away"
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

    assert entity.state.preset_mode == "away"
    assert thrm_cluster.write_attributes.call_count == 1
    assert thrm_cluster.write_attributes.call_args[0][0] == {"set_occupancy": 1}

    # successful occupancy change
    thrm_cluster.write_attributes.reset_mock()
    thrm_cluster.write_attributes.return_value = [
        zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]
    ]

    await entity.async_set_preset_mode("none")
    await zha_gateway.async_block_till_done()

    assert entity.state.preset_mode == "none"
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

    assert entity.state.preset_mode == "none"
    await entity.async_set_preset_mode("invalid_preset")
    await zha_gateway.async_block_till_done()

    assert entity.state.preset_mode == "none"
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

    assert entity.state.hvac_mode == "off"
    await entity.async_set_temperature(hvac_mode="heat_cool", temperature=20)
    await zha_gateway.async_block_till_done()

    assert entity.state.hvac_mode == "heat_cool"
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

    assert entity.state.hvac_mode == "heat_cool"

    await entity.async_set_temperature(temperature=20)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low == 20.0
    assert entity.state.target_temperature_high == 25.0
    assert thrm_cluster.write_attributes.await_count == 0

    await entity.async_set_temperature(target_temp_high=26, target_temp_low=19)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low == 19.0
    assert entity.state.target_temperature_high == 26.0
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

    assert entity.state.hvac_mode == "heat"

    await entity.async_set_temperature(target_temp_high=30, target_temp_low=15)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 20.0
    assert thrm_cluster.write_attributes.await_count == 0

    await entity.async_set_temperature(temperature=21)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 21.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_heating_setpoint": 2100
    }

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await entity.async_set_temperature(temperature=22)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 22.0
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

    assert entity.state.hvac_mode == "cool"

    await entity.async_set_temperature(target_temp_high=30, target_temp_low=15)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 25.0
    assert thrm_cluster.write_attributes.await_count == 0

    await entity.async_set_temperature(temperature=21)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 21.0
    assert thrm_cluster.write_attributes.await_count == 1
    assert thrm_cluster.write_attributes.call_args_list[0][0][0] == {
        "occupied_cooling_setpoint": 2100
    }

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    await entity.async_set_temperature(temperature=22)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature == 22.0
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

    assert entity.state.hvac_mode == "dry"

    await entity.async_set_temperature(temperature=24)
    await zha_gateway.async_block_till_done()

    assert entity.state.target_temperature_low is None
    assert entity.state.target_temperature_high is None
    assert entity.state.target_temperature is None
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

    assert entity.state.preset_mode == "none"

    await entity.async_set_preset_mode("away")
    await zha_gateway.async_block_till_done()
    thrm_cluster.write_attributes.reset_mock()

    assert entity.state.preset_mode == "away"

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {"occupied_heating_setpoint": zigpy.types.uint16_t(1950)},
    )
    assert entity.state.preset_mode == "none"


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
    assert entity.state.fan_mode == FanState.AUTO

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {"running_state": Thermostat.RunningState.Fan_State_On},
    )
    assert entity.state.fan_mode == FanState.ON

    await send_attributes_report(
        zha_gateway, thrm_cluster, {"running_state": Thermostat.RunningState.Idle}
    )
    assert entity.state.fan_mode == FanState.AUTO

    await send_attributes_report(
        zha_gateway,
        thrm_cluster,
        {"running_state": Thermostat.RunningState.Fan_2nd_Stage_On},
    )
    assert entity.state.fan_mode == FanState.ON


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


async def test_set_fan_mode_no_zcl_mapping(
    zha_gateway: Gateway,
):
    """Test fan mode with no ZCL mapping is rejected."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    # Patch `fan_modes` to include a string that is intentionally absent from
    # `FAN_MODE_TO_ZCL` so the defensive `.get(...) is None` branch in
    # `async_set_fan_mode` is exercised (the earlier "mode not in fan_modes"
    # rejection would otherwise short-circuit it).
    with patch.object(
        ThermostatEntity,
        "fan_modes",
        new_callable=PropertyMock,
        return_value=["bogus"],
    ):
        await entity.async_set_fan_mode("bogus")
        await zha_gateway.async_block_till_done()

    assert fan_cluster.write_attributes.await_count == 0


async def test_fan_only_hvac_mode_not_exposed_without_quirk_feature(
    zha_gateway: Gateway,
):
    """Fan cluster alone must not expose HVACMode.FAN_ONLY."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert THERMOSTAT_FAN_ONLY_HVAC not in device_climate_fan.exposes_features
    assert HVACMode.FAN_ONLY not in entity.hvac_modes


async def test_fan_only_hvac_mode_exposed_with_quirk_feature(
    zha_gateway: Gateway,
):
    """A quirk that opts in via exposes_features unlocks HVACMode.FAN_ONLY."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    device_climate_fan.exposes_features.add(THERMOSTAT_FAN_ONLY_HVAC)

    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert HVACMode.FAN_ONLY in entity.hvac_modes


async def test_set_fan_mode(
    zha_gateway: Gateway,
):
    """Test fan mode setting."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert entity.state.fan_mode == FanState.AUTO

    await entity.async_set_fan_mode(FanState.ON)
    await zha_gateway.async_block_till_done()

    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 4}

    fan_cluster.write_attributes.reset_mock()
    await entity.async_set_fan_mode(FanState.AUTO)
    await zha_gateway.async_block_till_done()
    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": 5}


@pytest.mark.parametrize(
    ("sequence", "expected_modes"),
    (
        (FanModeSequence.Low_Med_High, [FanState.LOW, FanState.MEDIUM, FanState.HIGH]),
        (FanModeSequence.Low_High, [FanState.LOW, FanState.HIGH]),
        (
            FanModeSequence.Low_Med_High_Auto,
            [FanState.LOW, FanState.MEDIUM, FanState.HIGH, FanState.AUTO],
        ),
        (FanModeSequence.Low_High_Auto, [FanState.LOW, FanState.HIGH, FanState.AUTO]),
        (FanModeSequence.On_Auto, [FanState.AUTO, FanState.ON]),
        (0xFF, [FanState.AUTO, FanState.ON]),  # unknown sequence → fallback
    ),
)
async def test_fan_modes_from_fan_mode_sequence(
    zha_gateway: Gateway,
    sequence: int,
    expected_modes: list[str],
):
    """fan_modes must be derived from the reported fan_mode_sequence."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await send_attributes_report(
        zha_gateway, fan_cluster, {"fan_mode_sequence": sequence}
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert entity.fan_modes == expected_modes
    # Sanity-check against the constant table for known sequences
    if sequence in SEQ_FAN_MODES:
        assert entity.fan_modes == SEQ_FAN_MODES[sequence]


@pytest.mark.parametrize(
    ("zcl_mode", "expected"),
    (
        (FanMode.Low, FanState.LOW),
        (FanMode.Medium, FanState.MEDIUM),
        (FanMode.High, FanState.HIGH),
        (FanMode.Auto, FanState.AUTO),
    ),
)
async def test_fan_mode_from_fan_cluster_report(
    zha_gateway: Gateway,
    zcl_mode: FanMode,
    expected: str,
):
    """fan_mode must reflect the Fan cluster attribute after a report."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    # Sequence that includes low/medium/high/auto so every tested value is in range
    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.Low_Med_High_Auto},
    )
    await send_attributes_report(zha_gateway, fan_cluster, {"fan_mode": zcl_mode})
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert entity.state.fan_mode == expected


@pytest.mark.parametrize(
    ("mode", "zcl_value"),
    (
        (FanState.LOW, FanMode.Low),
        (FanState.MEDIUM, FanMode.Medium),
        (FanState.HIGH, FanMode.High),
    ),
)
async def test_set_fan_mode_low_medium_high(
    zha_gateway: Gateway,
    mode: str,
    zcl_value: FanMode,
):
    """Setting low/medium/high must write the corresponding FanMode ZCL value."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.Low_Med_High_Auto},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    await entity.async_set_fan_mode(mode)
    await zha_gateway.async_block_till_done()

    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": zcl_value}


async def test_fan_mode_state_emission_on_fan_cluster_report(
    zha_gateway: Gateway,
):
    """A fan_mode report on the Fan cluster must emit STATE_CHANGED."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.Low_Med_High_Auto},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    subscriber = MagicMock()
    entity.on_event(STATE_CHANGED, subscriber)

    await send_attributes_report(zha_gateway, fan_cluster, {"fan_mode": FanMode.High})
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert subscriber.call_count >= 1
    assert entity.state.fan_mode == FanState.HIGH


async def test_fan_mode_outside_sequence_is_unioned(
    zha_gateway: Gateway,
):
    """A reported fan_mode outside the sequence must be appended to fan_modes."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    # Sequence without "on"; report FanMode.On (0x04) which is outside the list
    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.Low_Med_High},
    )
    await send_attributes_report(zha_gateway, fan_cluster, {"fan_mode": FanMode.On})
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert entity.fan_modes == [
        FanState.LOW,
        FanState.MEDIUM,
        FanState.HIGH,
        FanState.ON,
    ]
    assert entity.state.fan_mode == FanState.ON


async def test_fan_mode_running_state_fallback_clamped(
    zha_gateway: Gateway,
):
    """Uncached fan_mode must not return auto/on outside fan_modes via running_state."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    # Sequence with no auto/on; leave fan_mode uncached so the running_state
    # heuristic would otherwise return FAN_AUTO.
    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.Low_Med_High},
    )
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert fan_cluster.get("fan_mode") is None
    assert entity.fan_modes == [FanState.LOW, FanState.MEDIUM, FanState.HIGH]
    assert entity.state.fan_mode is None


async def test_fan_mode_off_mapped_correctly(
    zha_gateway: Gateway,
):
    """FanMode.Off must map to off (unioned into fan_modes) and be writable."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.On_Auto},
    )
    await send_attributes_report(zha_gateway, fan_cluster, {"fan_mode": FanMode.Off})
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert FanState.OFF in entity.fan_modes
    assert entity.state.fan_mode == FanState.OFF
    assert entity.state.fan_mode != FanState.AUTO

    fan_cluster.write_attributes.reset_mock()
    await entity.async_set_fan_mode(FanState.OFF)
    await zha_gateway.async_block_till_done()

    assert fan_cluster.write_attributes.await_count == 1
    assert fan_cluster.write_attributes.call_args[0][0] == {"fan_mode": FanMode.Off}


async def test_fan_mode_smart_returns_none(
    zha_gateway: Gateway,
):
    """FanMode.Smart has no HA equivalent and must return None."""
    device_climate_fan = await device_climate_mock(zha_gateway, CLIMATE_FAN)
    fan_cluster = device_climate_fan.device.endpoints[1].fan
    entity: ThermostatEntity = get_entity(
        device_climate_fan, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    await send_attributes_report(
        zha_gateway,
        fan_cluster,
        {"fan_mode_sequence": FanModeSequence.Low_Med_High_Auto},
    )
    await send_attributes_report(zha_gateway, fan_cluster, {"fan_mode": FanMode.Smart})
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert entity.state.fan_mode is None


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

    assert entity.state.preset_mode == "none"

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

    assert entity.state.preset_mode == "away"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 1})

    assert entity.state.preset_mode == "Schedule"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 2})

    assert entity.state.preset_mode == "none"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 3})

    assert entity.state.preset_mode == "comfort"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 4})

    assert entity.state.preset_mode == "eco"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 5})

    assert entity.state.preset_mode == "boost"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 6})

    assert entity.state.preset_mode == "Complex"


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

    assert entity.state.preset_mode == preset_mode

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

    assert entity.state.preset_mode == PRESET_NONE

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

    assert entity.state.preset_mode == PRESET_SCHEDULE

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 1})

    assert entity.state.preset_mode == PRESET_NONE

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 2})

    assert entity.state.preset_mode == "holiday"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 3})

    assert entity.state.preset_mode == "holiday"

    await send_attributes_report(zha_gateway, thrm_cluster, {"operation_preset": 4})

    assert entity.state.preset_mode == "frost protect"


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
    assert local_temperature_calibration_entity.state.native_min_value == -2.5
    assert local_temperature_calibration_entity.state.native_max_value == 2.5
    assert local_temperature_calibration_entity.state.native_step == 0.1
    assert local_temperature_calibration_entity._multiplier == 0.1


_WEEKDAY_BITS = {
    "monday": 2,
    "tuesday": 4,
    "wednesday": 8,
    "thursday": 16,
    "friday": 32,
    "saturday": 64,
    "sunday": 1,
}


@pytest.fixture
async def weekly_schedule_device(zha_gateway: Gateway):
    """Provide a thermostat with mocked device-side schedule commands."""
    device = await device_climate_mock(zha_gateway, CLIMATE, plug={})
    device.exposes_features.add(THERMOSTAT_WEEKLY_SCHEDULE)
    entity: ThermostatEntity = get_entity(
        device, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    cluster = device.device.endpoints[1].thermostat
    cluster.read_attributes.reset_mock()
    cluster.write_attributes.reset_mock()
    stored = {bit: [] for bit in _WEEKDAY_BITS.values()}

    async def command(command_id, **kwargs):
        if command_id == 0x02:
            day = int(kwargs["days_to_return"])
            values = stored[day]
            return Thermostat.ClientCommandDefs.get_weekly_schedule_response.schema(
                num_transitions_for_sequence=len(values) // 2,
                day_of_week_for_sequence=day,
                mode_for_sequence=SeqMode.Heat,
                values=values,
            )
        if command_id == 0x01:
            stored[int(kwargs["day_of_week_for_sequence"])] = list(kwargs["values"])
        elif command_id == 0x03:
            for day in stored:
                stored[day] = []
        else:
            raise AssertionError(f"Unexpected command {command_id}")
        return zcl_f.DefaultResponse(command_id=command_id, status=zcl_f.Status.SUCCESS)

    cluster.command = AsyncMock(side_effect=command)
    return entity, device, cluster, stored


async def test_weekly_schedule_upload_and_raw_invalidation(
    weekly_schedule_device,
) -> None:
    """Seven transitions per day are uploaded, verified and invalidated by raw writes."""
    entity, device, cluster, stored = weekly_schedule_device
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert not cached["complete"]
    assert cached["days"]["monday"]["transitions"] is None
    cluster.command.assert_not_awaited()

    transitions = [
        (0, 2000),
        (120, 1950),
        (240, 2050),
        (360, 2100),
        (480, 2000),
        (600, 1950),
        (720, 1900),
    ]
    schedule = {day: list(transitions) for day in _WEEKDAY_BITS}
    result = await entity.async_set_weekly_schedule(schedule)

    assert entity.weekly_schedule.has_verified_schedule
    assert result["complete"]
    assert result["pre_write_snapshot"]["complete"]
    assert result["pre_write_snapshot"]["days"]["monday"]["transitions"] == []
    assert result["days"]["monday"]["transitions"] == [
        {"time": f"{minute // 60:02}:{minute % 60:02}", "temperature": value / 100}
        for minute, value in transitions
    ]
    assert result["days"]["monday"]["updated_at"] is not None
    assert cluster.read_attributes.await_args.kwargs["allow_cache"] is False
    cluster.write_attributes.assert_not_awaited()

    writes = [
        item
        for item in cluster.command.await_args_list
        if item.args[0] == Thermostat.ServerCommandDefs.set_weekly_schedule.id
    ]
    assert len(writes) == 7
    expected_values = [
        value for minute, temperature in transitions for value in (minute, temperature)
    ]
    for (day, bit), write in zip(_WEEKDAY_BITS.items(), writes, strict=True):
        assert write.kwargs == {
            "num_transitions_for_sequence": 7,
            "day_of_week_for_sequence": bit,
            "mode_for_sequence": SeqMode.Heat,
            "values": expected_values,
            "retries": 0,
        }
        assert stored[bit] == expected_values, day

    raw_response = await device.issue_cluster_command(
        1,
        Thermostat.cluster_id,
        1,
        "server",
        None,
        {
            "num_transitions_for_sequence": 1,
            "day_of_week_for_sequence": 2,
            "mode_for_sequence": 1,
            "values": [0, 1800],
        },
        return_response=True,
    )
    assert raw_response.status == zcl_f.Status.SUCCESS
    assert not entity.weekly_schedule.has_verified_schedule
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert not cached["complete"]
    assert cached["days"]["monday"]["transitions"] is None
    assert cached["days"]["tuesday"]["transitions"] is not None
    assert cached["pre_write_snapshot"]["complete"]

    await device.issue_cluster_command(1, Thermostat.cluster_id, 3, "server", None, {})
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert all(day["transitions"] is None for day in cached["days"].values())
    fresh = await entity.async_get_weekly_schedule()
    assert fresh["complete"]
    assert all(day["transitions"] == [] for day in fresh["days"].values())


async def test_weekly_schedule_verification_tracks_device_changes(
    weekly_schedule_device,
) -> None:
    """Only a successful upload remains verified after matching reads."""
    entity, _device, cluster, stored = weekly_schedule_device
    provider = entity.weekly_schedule
    events: list[bool] = []
    provider.on_event(provider.EVENT_VERIFIED_CHANGED, events.append)
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}

    await entity.async_set_weekly_schedule(schedule)
    assert provider.has_verified_schedule
    assert events[-1] is True
    await entity.async_get_weekly_schedule()
    assert provider.has_verified_schedule

    stored[_WEEKDAY_BITS["monday"]] = [0, 1900]
    await entity.async_get_weekly_schedule()
    assert not provider.has_verified_schedule
    assert events[-1] is False

    await entity.async_set_weekly_schedule(schedule)
    assert provider.has_verified_schedule
    working = cluster.command.side_effect

    async def failed_write(command_id, **kwargs):
        if command_id == 1:
            raise zigpy.exceptions.DeliveryError("offline")
        return await working(command_id, **kwargs)

    with (
        patch.object(cluster, "command", side_effect=failed_write),
        pytest.raises(ZHAException, match="Schedule upload stopped"),
    ):
        await entity.async_set_weekly_schedule(
            {day: [(0, 2100)] for day in _WEEKDAY_BITS}
        )
    assert not provider.has_verified_schedule
    assert events[-1] is False

    await entity.async_set_weekly_schedule(schedule)
    await entity.async_clear_weekly_schedule()
    assert not provider.has_verified_schedule
    assert events[-1] is False


async def test_weekly_schedule_clear_snapshots_and_verifies(
    weekly_schedule_device,
) -> None:
    """Clear once after a fresh snapshot and verify each heat day is empty."""
    entity, _device, cluster, stored = weekly_schedule_device
    for bit in stored:
        stored[bit] = [0, 1950, 480, 2100]

    result = await entity.async_clear_weekly_schedule()

    assert result["complete"]
    assert all(day["transitions"] == [] for day in result["days"].values())
    assert result["pre_write_snapshot"]["complete"]
    assert result["pre_write_snapshot"]["days"]["monday"]["transitions"] == [
        {"time": "00:00", "temperature": 19.5},
        {"time": "08:00", "temperature": 21.0},
    ]
    assert all(values == [] for values in stored.values())
    commands = cluster.command.await_args_list
    assert [item.args[0] for item in commands] == [2] * 7 + [3] + [2] * 7
    assert commands[7].kwargs == {"retries": 0}
    cluster.write_attributes.assert_not_awaited()
    assert await entity.async_get_weekly_schedule(refresh=False) == result


async def test_weekly_schedule_clear_requires_complete_preflight(
    weekly_schedule_device,
) -> None:
    """A failed fresh snapshot prevents the clear command from being sent."""
    entity, _device, cluster, stored = weekly_schedule_device
    for bit in stored:
        stored[bit] = [0, 2000]
    command = cluster.command.side_effect

    async def fail_wednesday(command_id, **kwargs):
        if command_id == 2 and kwargs["days_to_return"] == 8:
            raise TimeoutError("no response")
        return await command(command_id, **kwargs)

    cluster.command.side_effect = fail_wednesday
    with pytest.raises(ZHAException, match="Unable to read the wednesday schedule"):
        await entity.async_clear_weekly_schedule()
    assert not any(item.args[0] == 3 for item in cluster.command.await_args_list)
    assert all(values == [0, 2000] for values in stored.values())
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["pre_write_snapshot"] is None
    assert cached["days"]["wednesday"]["transitions"] is None


async def test_weekly_schedule_clear_requires_device_command(
    weekly_schedule_device,
) -> None:
    """A missing clear command is reported before reading or writing."""
    entity, _device, cluster, _stored = weekly_schedule_device
    commands = {
        key: value for key, value in cluster.server_commands.items() if key != 3
    }
    with (
        patch.object(cluster, "server_commands", commands),
        pytest.raises(ZHAException, match="does not support schedule clearing"),
    ):
        await entity.async_clear_weekly_schedule()
    cluster.command.assert_not_awaited()


async def test_weekly_schedule_clear_cancellation_invalidates_cache(
    weekly_schedule_device,
) -> None:
    """Cancellation during clear leaves the schedule unknown and snapshot available."""
    entity, _device, cluster, stored = weekly_schedule_device
    for bit in stored:
        stored[bit] = [0, 2000]
    command = cluster.command.side_effect
    started = asyncio.Event()

    async def pause_clear(command_id, **kwargs):
        if command_id == 3:
            started.set()
            await asyncio.Event().wait()
        return await command(command_id, **kwargs)

    cluster.command.side_effect = pause_clear
    clear = asyncio.create_task(entity.async_clear_weekly_schedule())
    waiting_for_clear = asyncio.create_task(started.wait())
    done, _ = await asyncio.wait(
        (clear, waiting_for_clear), return_when=asyncio.FIRST_COMPLETED
    )
    if clear in done:
        waiting_for_clear.cancel()
        await clear
    assert waiting_for_clear in done
    clear.cancel()
    with pytest.raises(asyncio.CancelledError):
        await clear
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["pre_write_snapshot"]["complete"]
    assert all(day["transitions"] is None for day in cached["days"].values())


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("timeout", "Unable to confirm schedule clearing"),
        ("response_error", "Unable to confirm schedule clearing"),
        ("rejected", "Schedule clear returned status"),
        ("unexpected_ack", "Unexpected schedule clear acknowledgement"),
        ("readback", "heat schedule read-back failed"),
        ("nonempty", "did not remove heat transitions on"),
    ],
)
async def test_weekly_schedule_clear_surfaces_failure(
    weekly_schedule_device, failure: str, message: str
) -> None:
    """A failed or unverified clear is reported without retry or rollback."""
    entity, _device, cluster, stored = weekly_schedule_device
    for bit in stored:
        stored[bit] = [0, 2000]
    command = cluster.command.side_effect
    clear_attempted = False

    async def fail_clear(command_id, **kwargs):
        nonlocal clear_attempted
        if command_id == 3:
            clear_attempted = True
            if failure == "rejected":
                return zcl_f.DefaultResponse(
                    command_id=3, status=zcl_f.Status.UNSUP_CLUSTER_COMMAND
                )
            if failure == "response_error":
                return ValueError("device command failed")
            response = await command(command_id, **kwargs)
            if failure == "timeout":
                raise TimeoutError("acknowledgement lost")
            if failure == "unexpected_ack":
                return zcl_f.DefaultResponse(command_id=1, status=zcl_f.Status.SUCCESS)
            if failure == "nonempty":
                stored[4] = [0, 1900]
            return response
        if (
            clear_attempted
            and failure == "readback"
            and command_id == 2
            and kwargs["days_to_return"] == 4
        ):
            raise TimeoutError("read-back lost")
        return await command(command_id, **kwargs)

    cluster.command.side_effect = fail_clear
    with pytest.raises(ZHAException, match=message) as err:
        await entity.async_clear_weekly_schedule()
    assert "No rollback was attempted" in str(err.value)
    assert sum(item.args[0] == 3 for item in cluster.command.await_args_list) == 1
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["pre_write_snapshot"]["complete"]
    assert cached["pre_write_snapshot"]["days"]["monday"]["transitions"] == [
        {"time": "00:00", "temperature": 20.0}
    ]
    if failure in ("timeout", "response_error", "rejected", "unexpected_ack"):
        assert all(day["transitions"] is None for day in cached["days"].values())
    elif failure == "readback":
        assert cached["days"]["monday"]["transitions"] == []
        assert cached["days"]["tuesday"]["transitions"] is None
    else:
        assert cached["days"]["tuesday"]["transitions"] == [
            {"time": "00:00", "temperature": 19.0}
        ]


@pytest.mark.parametrize(
    "problem",
    [
        "missing_day",
        "empty_day",
        "malformed_transition",
        "duplicate_time",
        "invalid_temperature",
        "missing_midnight",
        "too_many",
        "out_of_limits",
        "limits_unavailable",
        "heat_limits_transport_failure",
        "invalid_heat_limits",
    ],
)
async def test_weekly_schedule_validation_precedes_writes(
    weekly_schedule_device, problem: str
) -> None:
    """Invalid complete-week uploads never write any day."""
    entity, _device, cluster, _stored = weekly_schedule_device
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    if problem == "missing_day":
        del schedule["sunday"]
    elif problem == "empty_day":
        schedule["sunday"] = []
    elif problem == "malformed_transition":
        schedule["sunday"] = [(0, 2000, 1)]
    elif problem == "duplicate_time":
        schedule["sunday"] = [(0, 2000), (0, 2100)]
    elif problem == "invalid_temperature":
        schedule["sunday"] = [(0, True)]
    elif problem == "missing_midnight":
        schedule["sunday"] = [(60, 2000)]
    elif problem == "too_many":
        schedule["sunday"] = [(minute, 2000) for minute in range(256)]
    elif problem == "out_of_limits":
        schedule["sunday"] = [(0, 5000)]
    elif problem == "limits_unavailable":
        cluster.PLUGGED_ATTR_READS["min_heat_setpoint_limit"] = None
    elif problem == "heat_limits_transport_failure":
        cluster.read_attributes.side_effect = TimeoutError("radio unavailable")
    elif problem == "invalid_heat_limits":
        cluster.read_attributes.return_value = (
            {"min_heat_setpoint_limit": 3000, "max_heat_setpoint_limit": 1600},
            {},
        )

    with pytest.raises(ZHAException):
        await entity.async_set_weekly_schedule(schedule)
    cluster.command.assert_not_awaited()


@pytest.mark.parametrize(
    ("temperature", "direction"),
    [(5000, "too high"), (600, "too low")],
)
async def test_weekly_schedule_heat_limit_error_identifies_temperature(
    weekly_schedule_device, temperature: int, direction: str
) -> None:
    """Out-of-range temperatures identify the value, day, time, and limits."""
    entity, _device, cluster, _stored = weekly_schedule_device
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    schedule["sunday"] = [(0, 2000), (390, temperature)]

    with pytest.raises(ZHAException) as err:
        await entity.async_set_weekly_schedule(schedule)
    assert str(err.value) == (
        f"The temperature {temperature / 100:g} °C on Sunday at 06:30 is "
        f"{direction}. Choose a temperature within the thermostat's "
        "allowed range of 7 to 29 °C."
    )
    cluster.command.assert_not_awaited()


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (ValueError("command failed"), "Unable to read the monday schedule"),
        (
            zcl_f.DefaultResponse(command_id=2, status=zcl_f.Status.FAILURE),
            "device returned",
        ),
        ("unexpected response", "Unexpected schedule response"),
    ],
)
async def test_weekly_schedule_rejects_non_schedule_responses(
    weekly_schedule_device, response, message: str
) -> None:
    """Command errors, default responses and non-struct replies are rejected."""
    entity, _device, cluster, _stored = weekly_schedule_device
    cluster.command.return_value = response
    cluster.command.side_effect = None
    with pytest.raises(ZHAException, match=message):
        await entity.async_get_weekly_schedule()


async def test_weekly_schedule_does_not_enforce_unverified_device_limit(
    weekly_schedule_device,
) -> None:
    """A mocked twelve-transition payload is not rejected by a guessed limit."""
    entity, _device, cluster, stored = weekly_schedule_device
    transitions = [(minute, 2000) for minute in range(12)]
    result = await entity.async_set_weekly_schedule(
        {day: list(transitions) for day in _WEEKDAY_BITS}
    )
    assert result["complete"]
    assert len(stored[2]) == 24
    assert sum(item.args[0] == 1 for item in cluster.command.await_args_list) == 7


async def test_weekly_schedule_incomplete_preflight(
    weekly_schedule_device,
) -> None:
    """A failed fresh pre-read aborts before writes and leaves unknown days marked."""
    entity, _device, cluster, _stored = weekly_schedule_device
    command = cluster.command.side_effect

    async def fail_wednesday(command_id, **kwargs):
        if command_id == 2 and kwargs["days_to_return"] == 8:
            raise TimeoutError("no response")
        return await command(command_id, **kwargs)

    cluster.command.side_effect = fail_wednesday
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    with pytest.raises(ZHAException, match="Unable to read the wednesday schedule"):
        await entity.async_set_weekly_schedule(schedule)
    assert not any(item.args[0] == 1 for item in cluster.command.await_args_list)
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["days"]["monday"]["transitions"] == []
    assert cached["days"]["wednesday"]["transitions"] is None
    assert cached["pre_write_snapshot"] is None


async def test_weekly_schedule_missing_thermostat_cluster_clears_cache(
    weekly_schedule_device,
) -> None:
    """A missing endpoint cluster fails explicitly and clears stale cache."""
    entity, device, _cluster, _stored = weekly_schedule_device
    await entity.async_get_weekly_schedule()
    with (
        patch.object(device, "async_get_cluster", side_effect=KeyError("missing")),
        pytest.raises(
            ZHAException, match="The thermostat cluster is no longer available"
        ),
    ):
        await entity.async_get_weekly_schedule(refresh=False)
    cached = entity.weekly_schedule._snapshot()
    assert not cached["complete"]
    assert entity.weekly_schedule._pre_write_snapshot is None


async def test_weekly_schedule_missing_write_command(weekly_schedule_device) -> None:
    """A missing set command is rejected before snapshot reads or writes."""
    entity, _device, cluster, _stored = weekly_schedule_device
    commands = {
        key: value for key, value in cluster.server_commands.items() if key != 1
    }
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    with (
        patch.object(cluster, "server_commands", commands),
        pytest.raises(ZHAException, match="does not support schedule writes"),
    ):
        await entity.async_set_weekly_schedule(schedule)
    cluster.command.assert_not_awaited()


async def test_weekly_schedule_rejects_unencodable_payload(
    weekly_schedule_device,
) -> None:
    """Payload serialization errors are reported before any device command."""
    entity, _device, cluster, _stored = weekly_schedule_device
    commands = dict(cluster.server_commands)

    class InvalidSchema:
        def __init__(self, **_kwargs) -> None:
            raise ValueError("payload too large")

    commands[1] = SimpleNamespace(schema=InvalidSchema)
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    with (
        patch.object(cluster, "server_commands", commands),
        pytest.raises(ZHAException, match="monday schedule cannot be encoded"),
    ):
        await entity.async_set_weekly_schedule(schedule)
    cluster.command.assert_not_awaited()


async def test_weekly_schedule_cluster_replacement_aborts_before_first_write(
    weekly_schedule_device,
) -> None:
    """A replaced cluster during preflight aborts before changing a day."""
    entity, device, cluster, _stored = weekly_schedule_device
    manager = entity.weekly_schedule
    endpoint = device.device.endpoints[1]
    original_command = cluster.command.side_effect

    async def replace_after_sunday(command_id, **kwargs):
        response = await original_command(command_id, **kwargs)
        if command_id == 2 and int(kwargs["days_to_return"]) == 1:
            endpoint.in_clusters[Thermostat.cluster_id] = Thermostat(endpoint)
        return response

    cluster.command.side_effect = replace_after_sunday
    with pytest.raises(ZHAException, match="thermostat cluster changed"):
        await entity.async_set_weekly_schedule(
            {day: [(0, 2000)] for day in _WEEKDAY_BITS}
        )
    assert not any(item.args[0] == 1 for item in cluster.command.await_args_list)
    cached = manager._snapshot()
    assert not cached["complete"]
    assert manager._pre_write_snapshot is None


async def test_weekly_schedule_cluster_change_after_snapshot_is_reported(
    weekly_schedule_device,
) -> None:
    """A cluster change just before writing is reported with the saved snapshot."""
    entity, _device, cluster, _stored = weekly_schedule_device
    manager = entity.weekly_schedule
    original = manager._ensure_same_cluster
    checks = 0

    def replace_before_write(current_cluster) -> None:
        nonlocal checks
        checks += 1
        if checks == 9:
            raise ZHAException("The thermostat cluster changed during the operation")
        original(current_cluster)

    with (
        patch.object(manager, "_ensure_same_cluster", side_effect=replace_before_write),
        pytest.raises(
            ZHAException,
            match=r"Observed changed days: \[\]; unknown attempted days: \[\]",
        ),
    ):
        await entity.async_set_weekly_schedule(
            {day: [(0, 2000)] for day in _WEEKDAY_BITS}
        )
    assert checks == 9
    assert not any(item.args[0] == 1 for item in cluster.command.await_args_list)
    assert manager._pre_write_snapshot["complete"]


@pytest.mark.parametrize(
    ("count", "days", "mode", "values"),
    [
        (2, 2, 1, [0, 2000]),
        (1, 4, 1, [0, 2000]),
        (1, 2, 2, [0, 2000]),
        (2, 2, 1, [60, 2000, 60, 2100]),
    ],
)
async def test_weekly_schedule_rejects_malformed_read_back(
    weekly_schedule_device, count: int, days: int, mode: int, values: list[int]
) -> None:
    """A mismatched or invalid response is never cached as a known day."""
    entity, _device, cluster, _stored = weekly_schedule_device
    cluster.command.return_value = (
        Thermostat.ClientCommandDefs.get_weekly_schedule_response.schema(
            num_transitions_for_sequence=count,
            day_of_week_for_sequence=days,
            mode_for_sequence=mode,
            values=values,
        )
    )
    cluster.command.side_effect = None
    with pytest.raises(ZHAException, match="schedule (response|transition)"):
        await entity.async_get_weekly_schedule()
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["days"]["monday"]["transitions"] is None


async def test_weekly_schedule_partial_failure_preserves_snapshot(
    weekly_schedule_device,
) -> None:
    """A lost acknowledgement and failed read-back leave the attempted day unknown."""
    entity, _device, cluster, _stored = weekly_schedule_device
    command = cluster.command.side_effect
    attempted_tuesday = False

    async def fail_tuesday(command_id, **kwargs):
        nonlocal attempted_tuesday
        if command_id == 1 and kwargs["day_of_week_for_sequence"] == 4:
            attempted_tuesday = True
            raise TimeoutError("acknowledgement lost")
        if command_id == 2 and kwargs["days_to_return"] == 4 and attempted_tuesday:
            raise TimeoutError("read-back lost")
        return await command(command_id, **kwargs)

    cluster.command.side_effect = fail_tuesday
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    with pytest.raises(
        ZHAException,
        match=r"Observed changed days: \['monday'\]; unknown attempted days: \['tuesday'\]",
    ):
        await entity.async_set_weekly_schedule(schedule)
    writes = [item for item in cluster.command.await_args_list if item.args[0] == 1]
    assert len(writes) == 2
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["days"]["monday"]["transitions"] == [
        {"time": "00:00", "temperature": 20.0}
    ]
    assert cached["days"]["tuesday"]["transitions"] is None
    assert cached["pre_write_snapshot"]["complete"]
    assert cached["pre_write_snapshot"]["days"]["monday"]["transitions"] == []


async def test_weekly_schedule_lost_acknowledgement_with_matching_readback(
    weekly_schedule_device,
) -> None:
    """An exact read-back establishes the stored value without retrying the write."""
    entity, _device, cluster, _stored = weekly_schedule_device
    command = cluster.command.side_effect

    async def lose_first_ack(command_id, **kwargs):
        response = await command(command_id, **kwargs)
        if command_id == 1 and kwargs["day_of_week_for_sequence"] == 2:
            raise TimeoutError("acknowledgement lost")
        return response

    cluster.command.side_effect = lose_first_ack
    result = await entity.async_set_weekly_schedule(
        {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    )
    assert result["complete"]
    writes = [item for item in cluster.command.await_args_list if item.args[0] == 1]
    assert len(writes) == 7


@pytest.mark.parametrize("reply", ["exception", "unexpected_ack"])
async def test_weekly_schedule_matching_readback_recovers_invalid_reply(
    weekly_schedule_device, reply: str
) -> None:
    """Exact read-back confirms a write despite an exception or unknown reply."""
    entity, _device, cluster, _stored = weekly_schedule_device
    command = cluster.command.side_effect

    async def invalid_reply(command_id, **kwargs):
        response = await command(command_id, **kwargs)
        if command_id == 1 and kwargs["day_of_week_for_sequence"] == 2:
            if reply == "exception":
                return ValueError("response decoding failed")
            return zcl_f.DefaultResponse(command_id=3, status=zcl_f.Status.SUCCESS)
        return response

    cluster.command.side_effect = invalid_reply
    result = await entity.async_set_weekly_schedule(
        {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    )
    assert result["complete"]
    assert (
        len([item for item in cluster.command.await_args_list if item.args[0] == 1])
        == 7
    )


@pytest.mark.parametrize("failure", ["rejected", "mismatched_readback", "transport"])
async def test_weekly_schedule_stops_after_device_failure(
    weekly_schedule_device, failure: str
) -> None:
    """A rejection or differing read-back stops subsequent days without rollback."""
    entity, _device, cluster, stored = weekly_schedule_device
    command = cluster.command.side_effect

    async def fail_tuesday(command_id, **kwargs):
        if command_id == 1 and kwargs["day_of_week_for_sequence"] == 4:
            if failure == "rejected":
                return zcl_f.DefaultResponse(
                    command_id=1, status=zcl_f.Status.UNSUP_CLUSTER_COMMAND
                )
            if failure == "transport":
                raise ValueError("Radio rejected the schedule payload")
            stored[4] = [0, 1900]
            return zcl_f.DefaultResponse(command_id=1, status=zcl_f.Status.SUCCESS)
        return await command(command_id, **kwargs)

    cluster.command.side_effect = fail_tuesday
    with pytest.raises(ZHAException) as err:
        await entity.async_set_weekly_schedule(
            {day: [(0, 2000)] for day in _WEEKDAY_BITS}
        )
    assert "Schedule upload stopped on tuesday" in str(err.value)
    assert "unknown attempted days: []" in str(err.value)
    if failure in ("rejected", "transport"):
        expected = (
            "UNSUP_CLUSTER_COMMAND"
            if failure == "rejected"
            else "Radio rejected the schedule payload"
        )
        assert expected in str(err.value)
        assert "Observed changed days: ['monday']" in str(err.value)
    else:
        assert "read-back does not match" in str(err.value)
        assert "Observed changed days: ['monday', 'tuesday']" in str(err.value)
    writes = [item for item in cluster.command.await_args_list if item.args[0] == 1]
    assert len(writes) == 2
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert cached["pre_write_snapshot"]["complete"]


@pytest.mark.parametrize("clear_type", ["raw", "managed"])
async def test_weekly_schedule_serializes_clear(
    weekly_schedule_device, clear_type: str
) -> None:
    """Clear waits for an in-progress upload on the same endpoint."""
    entity, device, cluster, stored = weekly_schedule_device
    command = cluster.command.side_effect
    started = asyncio.Event()
    resume = asyncio.Event()

    async def pause_first_write(command_id, **kwargs):
        if command_id == 1 and kwargs["day_of_week_for_sequence"] == 2:
            started.set()
            await resume.wait()
        return await command(command_id, **kwargs)

    cluster.command.side_effect = pause_first_write
    upload = asyncio.create_task(
        entity.async_set_weekly_schedule({day: [(0, 2000)] for day in _WEEKDAY_BITS})
    )
    waiting_for_write = asyncio.create_task(started.wait())
    done, _ = await asyncio.wait(
        (upload, waiting_for_write), return_when=asyncio.FIRST_COMPLETED
    )
    if upload in done:
        await upload
    assert waiting_for_write in done
    clear = asyncio.create_task(
        entity.async_clear_weekly_schedule()
        if clear_type == "managed"
        else device.issue_cluster_command(
            1, Thermostat.cluster_id, 3, "server", None, {}
        )
    )
    await asyncio.sleep(0)
    assert not clear.done()
    assert not any(item.args[0] == 3 for item in cluster.command.await_args_list)
    resume.set()
    await upload
    await clear
    assert all(values == [] for values in stored.values())
    cached = await entity.async_get_weekly_schedule(refresh=False)
    if clear_type == "raw":
        assert all(day["transitions"] is None for day in cached["days"].values())
    else:
        assert all(day["transitions"] == [] for day in cached["days"].values())
        assert cached["pre_write_snapshot"]["days"]["monday"]["transitions"] == [
            {"time": "00:00", "temperature": 20.0}
        ]


async def test_weekly_schedule_invalidates_on_cluster_replacement(
    weekly_schedule_device,
) -> None:
    """A replacement cluster cannot reuse the previous device's cached schedule."""
    entity, device, _cluster, _stored = weekly_schedule_device
    assert (await entity.async_get_weekly_schedule())["complete"]
    endpoint = device.device.endpoints[1]
    endpoint.in_clusters[Thermostat.cluster_id] = Thermostat(endpoint)
    cached = await entity.async_get_weekly_schedule(refresh=False)
    assert not cached["complete"]
    assert all(day["transitions"] is None for day in cached["days"].values())


@pytest.mark.parametrize(
    ("value", "raw_value"),
    [(0.3, 3), (-0.3, -3), (0.7, 7), (-1.9, -19), (2.4, 24)],
)
async def test_thermostat_local_temperature_calibration_write(
    zha_gateway: Gateway, value: float, raw_value: int
) -> None:
    """Test that a scaled number writes the nearest raw value, not a truncated one."""

    zha_device = await device_climate_mock(zha_gateway, CLIMATE)
    thrm_cluster = zha_device.device.endpoints[1].thermostat
    entity = get_entity(
        zha_device, platform=Platform.NUMBER, qualifier="local_temperature_calibration"
    )

    await entity.async_set_native_value(value)

    assert thrm_cluster.write_attributes.mock_calls == [
        call({"local_temperature_calibration": raw_value}, manufacturer=UNDEFINED)
    ]


async def test_thermostat_quirkv2_local_temperature_calibration_config_overwrite(
    zha_gateway: Gateway,
) -> None:
    """Test that a quirk v2 local temperature calibration config overwrites the default one."""

    registry = DeviceRegistry()
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        CLIMATE,
        manufacturer="unk_manufacturer",
        model="FakeModel",
        registry=registry,
    )
    zigpy_device.node_desc.mac_capability_flags |= 0b_0000_0100
    zigpy_device.endpoints[1].thermostat.PLUGGED_ATTR_READS = ZCL_ATTR_PLUG

    @registry.register_device
    class FakeThermostatQuirk(Device):
        _device_match = DeviceMatch(
            applies_to=(ModelInfo("unk_manufacturer", "FakeModel"),)
        )

        def discover_entities(self) -> Iterator[PlatformEntity]:
            yield from super().discover_entities()

            endpoint = self.endpoints[1]
            cluster = endpoint.zigpy_endpoint.in_clusters[Thermostat.cluster_id]
            calibration = Thermostat.AttributeDefs.local_temperature_calibration.name

            yield NumberConfigurationEntity(
                endpoint=endpoint,
                device=self,
                cluster=cluster,
                unique_id=f"{self.ieee}-{endpoint.id}",
                attribute_name=calibration,
                unique_id_suffix=calibration,
                min_value=-5,
                max_value=5,
                step=0.1,
                multiplier=0.1,
                translation_key="local_temperature_calibration",
                fallback_name="Local temperature offset",
            )

    zigpy_device = registry.resolve(zigpy_device)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    assert zha_device.model == "FakeModel"
    assert zha_device.manufacturer == "unk_manufacturer"

    local_temperature_calibration_entity = zha_device.platform_entities[
        (Platform.NUMBER, "00:0d:6f:00:0a:90:69:e7-1-local_temperature_calibration")
    ]
    assert local_temperature_calibration_entity
    assert isinstance(local_temperature_calibration_entity, NumberConfigurationEntity)
    assert local_temperature_calibration_entity.state.native_min_value == -5.0
    assert local_temperature_calibration_entity.state.native_max_value == 5.0
    assert local_temperature_calibration_entity.state.native_step == 0.1
    assert local_temperature_calibration_entity._multiplier == 0.1


async def test_weekly_schedule_requires_exposed_feature(zha_gateway: Gateway) -> None:
    """Thermostats without an exposed schedule feature have no provider."""
    device = await device_climate_mock(zha_gateway, CLIMATE, plug={})
    entity: ThermostatEntity = get_entity(
        device, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    assert entity.weekly_schedule is None
    with pytest.raises(ZHAException, match="does not support weekly schedules"):
        await entity.async_get_weekly_schedule()


async def test_bosch_trv1_weekly_schedule_from_diagnostics(
    zha_gateway: Gateway,
) -> None:
    """The real TRV1 signature discovers the standard schedule provider."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/bosch-rbsh-trv1-zb-eu-0x11087140.json",
    )
    device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity: ThermostatEntity = get_entity(
        device, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )

    assert THERMOSTAT_WEEKLY_SCHEDULE in device.exposes_features
    assert isinstance(entity.weekly_schedule, ZclWeeklySchedule)
    assert HVACMode.AUTO in entity.hvac_modes


async def test_weekly_schedule_only_changed_days(weekly_schedule_device) -> None:
    """Change detection skips days whose fresh read already matches."""
    entity, _device, cluster, stored = weekly_schedule_device
    stored.update({bit: [0, 2000] for bit in _WEEKDAY_BITS.values()})
    schedule = {day: [(0, 2000)] for day in _WEEKDAY_BITS}
    schedule["wednesday"] = [(0, 1700), (420, 2100)]

    result = await entity.async_set_weekly_schedule(schedule, only_changed=True)

    writes = [
        item.kwargs["day_of_week_for_sequence"]
        for item in cluster.command.await_args_list
        if item.args[0] == Thermostat.ServerCommandDefs.set_weekly_schedule.id
    ]
    assert writes == [_WEEKDAY_BITS["wednesday"]]
    assert result["written_days"] == ["wednesday"]
    assert stored[_WEEKDAY_BITS["wednesday"]] == [0, 1700, 420, 2100]

    cluster.command.reset_mock()
    result = await entity.async_set_weekly_schedule(schedule, only_changed=True)
    assert result["written_days"] == []
    assert all(item.args[0] == 0x02 for item in cluster.command.await_args_list)


async def test_weekly_schedule_custom_provider(zha_gateway: Gateway) -> None:
    """Other thermostat families plug in by registering a feature provider."""

    class MemoryProvider(WeeklyScheduleProvider):
        capabilities = WeeklyScheduleCapabilities(
            max_transitions_per_day=2, temperature_step=50, supports_clear=False
        )

        def __init__(self, device, endpoint_id) -> None:
            super().__init__(device, endpoint_id)
            self.days: dict[str, tuple[Transition, ...]] = dict.fromkeys(
                _WEEKDAY_BITS, ()
            )

        async def _async_read_day(self, day):
            return self.days[day]

        async def _async_heat_limits(self):
            return 500, 3000

        def _check_write_support(self) -> None:
            pass

        async def _async_write_day(self, day, transitions):
            self.days[day] = transitions
            return WriteAcknowledgement()

    device = await device_climate_mock(zha_gateway, CLIMATE, plug={})
    device.exposes_features.add("test_memory_schedule")
    entity: ThermostatEntity = get_entity(
        device, platform=Platform.CLIMATE, entity_type=ThermostatEntity
    )
    with patch.dict(
        "zha.zigbee.weekly_schedule.WEEKLY_SCHEDULE_PROVIDERS",
        {"test_memory_schedule": MemoryProvider},
    ):
        provider = entity.weekly_schedule
    assert isinstance(provider, MemoryProvider)

    with pytest.raises(ZHAException, match="between 1 and 2 transitions"):
        await entity.async_set_weekly_schedule(
            {day: [(0, 2000), (60, 2100), (120, 2200)] for day in _WEEKDAY_BITS}
        )
    with pytest.raises(ZHAException, match=r"multiples of 0\.5"):
        await entity.async_set_weekly_schedule(
            {day: [(0, 2010)] for day in _WEEKDAY_BITS}
        )
    with pytest.raises(ZHAException, match="does not support schedule clearing"):
        await entity.async_clear_weekly_schedule()

    result = await entity.async_set_weekly_schedule(
        {day: [(0, 1750), (360, 2100)] for day in _WEEKDAY_BITS}
    )
    assert result["complete"]
    assert result["days"]["sunday"]["transitions"] == [
        {"time": "00:00", "temperature": 17.5},
        {"time": "06:00", "temperature": 21.0},
    ]
    assert provider.days["sunday"] == (Transition(0, 1750), Transition(360, 2100))
