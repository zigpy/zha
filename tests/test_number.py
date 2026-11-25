"""Test zha number platform."""

import logging
from unittest.mock import call

import pytest
from zigpy.device import ZigbeeDevice
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
import zigpy.types
from zigpy.typing import UNDEFINED
from zigpy.zcl.clusters import general, hvac, lighting
import zigpy.zdo.types as zdo_t

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.platforms.number.const import NumberMode

ZIGPY_ANALOG_OUTPUT_DEVICE = {
    1: {
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROL_SWITCH,
        SIG_EP_INPUT: [general.AnalogOutput.cluster_id, general.Basic.cluster_id],
        SIG_EP_OUTPUT: [],
        SIG_EP_PROFILE: zha.PROFILE_ID,
    }
}


async def light_mock(zha_gateway: Gateway) -> ZigbeeDevice:
    """Siren fixture."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_PROFILE: zha.PROFILE_ID,
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    general.Identify.cluster_id,
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                    lighting.Color.cluster_id,
                ],
                SIG_EP_OUTPUT: [general.Ota.cluster_id],
            }
        },
        node_descriptor=zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.EndDevice,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
            ),
            manufacturer_code=4447,
            maximum_buffer_size=127,
            maximum_incoming_transfer_size=100,
            server_mask=11264,
            maximum_outgoing_transfer_size=100,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        ),
    )

    return zigpy_device


@pytest.mark.parametrize("cached", [True, False])
async def test_number(
    zha_gateway: Gateway,
    cached: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test zha number platform.

    Without a cached value, everything has to be read from the device, as on the
    (re-)interview of a device.
    """
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "max_present_value": 100.0,
        "min_present_value": 1.0,
        "relinquish_default": 50.0,
        "resolution": 1.1,
        "description": "PWM1",
        "engineering_units": 98,
        "application_type": 4 * 0x10000,
    }
    if cached:
        update_attribute_cache(cluster)
    cluster.PLUGGED_ATTR_READS["present_value"] = 15.0

    caplog.set_level(logging.DEBUG, logger="zha.zigbee.cluster_config")
    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    assert "Failed to read attributes" not in caplog.text
    # one for present_value and one for the rest configuration attributes
    assert cluster.read_attributes.call_count == 2
    attr_reads = set()
    for call_args in cluster.read_attributes.call_args_list:
        attr_reads |= set(call_args[0][0])
    assert "max_present_value" in attr_reads
    assert "min_present_value" in attr_reads
    assert "relinquish_default" in attr_reads
    assert "resolution" in attr_reads
    assert "description" in attr_reads
    assert "engineering_units" in attr_reads
    assert "application_type" in attr_reads

    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)
    assert isinstance(entity, PlatformEntity)

    assert cluster.read_attributes.call_count == 2

    assert entity.fallback_name == "PWM1"

    # test that the state is 15.0
    assert entity.state.native_value == 15.0

    # test attributes
    assert entity.state.native_min_value == 1.0
    assert entity.state.native_max_value == 100.0
    assert entity.state.native_step == 1.1
    assert entity.state.mode == NumberMode.AUTO

    assert entity.icon == "mdi:percent"
    assert entity.native_unit_of_measurement == "%"
    assert entity.native_min_value == 1.0
    assert entity.native_max_value == 100.0
    assert entity.native_step == 1.1

    # change value from device
    assert cluster.read_attributes.call_count == 2
    await send_attributes_report(zha_gateway, cluster, {0x0055: 15})
    await zha_gateway.async_block_till_done()
    assert entity.state.native_value == 15.0

    # update value from device
    await send_attributes_report(zha_gateway, cluster, {0x0055: 20})
    await zha_gateway.async_block_till_done()
    assert entity.state.native_value == 20.0

    # change value from client
    await entity.async_set_native_value(30.0)
    await zha_gateway.async_block_till_done()

    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"present_value": 30.0}, manufacturer=UNDEFINED
    )
    assert entity.state.native_value == 30.0

    # test updating entity state from client
    cluster.read_attributes.reset_mock()
    assert entity.state.native_value == 30.0
    cluster.PLUGGED_ATTR_READS = {"present_value": 20}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["present_value"], allow_cache=False, only_cache=False, manufacturer=UNDEFINED
    )
    assert entity.state.native_value == 20.0

    await entity.async_set_native_value(30)
    await zha_gateway.async_block_till_done()
    assert len(cluster.write_attributes.mock_calls) == 2
    assert cluster.write_attributes.call_args == call(
        {"present_value": 30}, manufacturer=UNDEFINED
    )
    assert entity.state.native_value == 30.0


async def test_number_capabilities_updated(
    zha_gateway: Gateway,
) -> None:
    """Test the range, step and unit follow the device after the entity was added.

    A device paired with an incomplete cache only gets the missing values later, e.g.
    from the startup poll or a report.
    """
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {"min_present_value": 5.0, "present_value": 50.0}
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_min_value == 5.0
    assert entity.state.native_max_value == 1023
    assert entity.state.native_step is None
    assert entity.state.native_unit_of_measurement is None
    assert entity.fallback_name is None

    await send_attributes_report(
        zha_gateway,
        cluster,
        {
            "max_present_value": 100.0,
            "resolution": 10.0,
            "engineering_units": 98,
            "description": "Power Limit",
        },
    )
    await zha_gateway.async_block_till_done()

    assert entity.state.native_min_value == 5.0
    assert entity.state.native_max_value == 100.0
    assert entity.state.native_step == 10.0
    assert entity.state.native_unit_of_measurement == "%"
    assert entity.fallback_name == "Power Limit"


async def test_number_zero_max_value(
    zha_gateway: Gateway,
) -> None:
    """Test a maximum of 0 is not replaced by the default."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "min_present_value": -100.0,
        "max_present_value": 0.0,
        "present_value": -50.0,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_min_value == -100.0
    assert entity.state.native_max_value == 0.0


@pytest.mark.parametrize("resolution", [0.0, float("inf"), float("nan")])
async def test_number_invalid_resolution(
    zha_gateway: Gateway,
    resolution: float,
) -> None:
    """Test an invalid resolution is not used as step."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "min_present_value": 0.0,
        "max_present_value": 1.0,
        "resolution": resolution,
        "present_value": 0.5,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_step is None


@pytest.mark.parametrize("bound", [float("nan"), float("inf"), float("-inf")])
async def test_number_non_finite_range(
    zha_gateway: Gateway,
    bound: float,
) -> None:
    """Test a NaN or infinite minimum and maximum fall back to the defaults."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "min_present_value": bound,
        "max_present_value": bound,
        "present_value": 5.0,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_min_value == 0
    assert entity.state.native_max_value == 1023


async def test_number_non_finite_max_reported(
    zha_gateway: Gateway,
) -> None:
    """Test a NaN maximum reported after joining falls back to the default."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "min_present_value": 5.0,
        "max_present_value": 100.0,
        "present_value": 50.0,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_min_value == 5.0
    assert entity.state.native_max_value == 100.0

    await send_attributes_report(
        zha_gateway, cluster, {"max_present_value": float("nan")}
    )

    assert entity.state.native_min_value == 5.0
    assert entity.state.native_max_value == 1023


async def test_number_nan_present_value(
    zha_gateway: Gateway,
) -> None:
    """Test a NaN present value is reported as unknown."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "min_present_value": 0.0,
        "max_present_value": 100.0,
        "present_value": float("nan"),
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_value is None

    await send_attributes_report(zha_gateway, cluster, {"present_value": 42.0})
    assert entity.state.native_value == 42.0


async def test_number_missing_description_attr(
    zha_gateway: Gateway,
) -> None:
    """Test zha number platform - missing description attribute."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "max_present_value": 100.0,
        "min_present_value": 1.0,
        "relinquish_default": 50.0,
        "resolution": 1.1,
        "engineering_units": 98,
        "application_type": 4 * 0x10000,
    }
    update_attribute_cache(cluster)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)

    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)
    assert isinstance(entity, PlatformEntity)

    assert entity.fallback_name is None
    assert entity.translation_key is None


@pytest.mark.parametrize(
    ("application_type", "icon"),
    [
        (0x00040000, "mdi:percent"),
        (0x01040000, "mdi:percent"),
        (0x0106FFFF, "mdi:fan"),
        (0x01FF0000, None),
    ],
)
async def test_number_icon(
    zha_gateway: Gateway,
    application_type: int,
    icon: str | None,
) -> None:
    """Test the icon is taken from the type of the application type.

    The group in bits 24 to 31 is ignored, it is `0x01` for analog outputs.
    """
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "max_present_value": 100.0,
        "min_present_value": 0.0,
        "application_type": application_type,
        "present_value": 50.0,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.icon == icon


@pytest.mark.parametrize(
    ("attr", "initial_value", "new_value", "max_value"),
    (
        ("on_off_transition_time", 20, 5, 65535),
        ("on_level", 255, 50, 255),
        ("on_transition_time", 5, 1, 65534),
        ("off_transition_time", 5, 1, 65534),
        ("default_move_rate", 1, 5, 254),
        ("start_up_current_level", 254, 125, 255),
    ),
)
async def test_level_control_number(
    zha_gateway: Gateway,
    attr: str,
    initial_value: int,
    new_value: int,
    max_value: int,
) -> None:
    """Test ZHA level control number entities - new join."""

    light = await light_mock(zha_gateway)
    level_control_cluster = light.endpoints[1].level
    level_control_cluster.PLUGGED_ATTR_READS = {
        attr: initial_value,
    }
    zha_device = await join_zigpy_device(zha_gateway, light)

    entity = get_entity(zha_device, platform=Platform.NUMBER, qualifier=attr)

    assert level_control_cluster.read_attributes.mock_calls == [
        call(
            [
                "on_off_transition_time",
                "on_level",
                "on_transition_time",
                "off_transition_time",
                "default_move_rate",
                "start_up_current_level",
            ],
            allow_cache=True,
            only_cache=False,
        ),
        call(
            [
                "current_level",
            ],
            allow_cache=False,
            only_cache=False,
        ),
    ]

    assert entity.state.native_value == initial_value
    assert entity._attr_entity_category == EntityCategory.CONFIG

    assert entity.icon is None
    assert entity.fallback_name is None
    assert entity.native_unit_of_measurement is None
    assert entity.mode == NumberMode.AUTO
    assert entity.native_min_value == 0
    assert entity.native_max_value == max_value
    assert entity.native_step == 1.0

    await entity.async_set_native_value(new_value)
    assert level_control_cluster.write_attributes.mock_calls == [
        call({attr: new_value}, manufacturer=UNDEFINED)
    ]

    assert entity.state.native_value == new_value

    level_control_cluster.read_attributes.reset_mock()
    await entity.async_update()
    # the mocking doesn't update the attr cache so this flips back to initial value
    assert entity.state.native_value == initial_value
    assert level_control_cluster.read_attributes.mock_calls == [
        call(
            [attr],
            allow_cache=False,
            only_cache=False,
            manufacturer=UNDEFINED,
        )
    ]

    level_control_cluster.write_attributes.reset_mock()
    level_control_cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZigbeeException):
        await entity.async_set_native_value(new_value)

    assert level_control_cluster.write_attributes.mock_calls == [
        call({attr: new_value}, manufacturer=UNDEFINED),
    ]
    assert entity.state.native_value == initial_value

    # test updating entity state from client
    level_control_cluster.read_attributes.reset_mock()
    assert entity.state.native_value == initial_value
    level_control_cluster.PLUGGED_ATTR_READS = {attr: new_value}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert level_control_cluster.read_attributes.await_count == 1
    assert level_control_cluster.read_attributes.mock_calls == [
        call(
            [
                attr,
            ],
            allow_cache=False,
            only_cache=False,
            manufacturer=UNDEFINED,
        ),
    ]
    assert entity.state.native_value == new_value

    # update value from device
    await send_attributes_report(
        zha_gateway,
        level_control_cluster,
        {level_control_cluster.attributes_by_name[attr].id: initial_value},
    )
    await zha_gateway.async_block_till_done()
    assert entity.state.native_value == initial_value


@pytest.mark.parametrize(
    ("attr", "initial_value", "new_value"),
    (("start_up_color_temperature", 500, 350),),
)
async def test_color_number(
    zha_gateway: Gateway,
    attr: str,
    initial_value: int,
    new_value: int,
) -> None:
    """Test ZHA color number entities - new join."""

    light = await light_mock(zha_gateway)
    color_cluster = light.endpoints[1].light_color
    color_cluster.PLUGGED_ATTR_READS = {
        attr: initial_value,
    }
    zha_device = await join_zigpy_device(zha_gateway, light)

    entity = get_entity(zha_device, platform=Platform.NUMBER, qualifier=attr)

    assert color_cluster.read_attributes.call_count == 2
    assert (
        call(
            [
                "color_temp_physical_min",
                "color_temp_physical_max",
                "color_capabilities",
                "start_up_color_temperature",
                "options",
            ],
            allow_cache=True,
            only_cache=False,
        )
        in color_cluster.read_attributes.call_args_list
    )

    assert entity.state.native_value == initial_value
    assert entity._attr_entity_category == EntityCategory.CONFIG

    await entity.async_set_native_value(new_value)
    assert color_cluster.write_attributes.call_count == 1
    assert color_cluster.write_attributes.call_args[0][0] == {
        attr: new_value,
    }

    assert entity.state.native_value == new_value

    color_cluster.read_attributes.reset_mock()
    await entity.async_update()
    # the mocking doesn't update the attr cache so this flips back to initial value
    assert entity.state.native_value == initial_value
    assert color_cluster.read_attributes.call_count == 1
    assert (
        call(
            [attr],
            allow_cache=False,
            only_cache=False,
            manufacturer=UNDEFINED,
        )
        in color_cluster.read_attributes.call_args_list
    )

    color_cluster.write_attributes.reset_mock()
    color_cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZigbeeException):
        await entity.async_set_native_value(new_value)

    assert color_cluster.write_attributes.mock_calls == [
        call({attr: new_value}, manufacturer=UNDEFINED),
    ]
    assert entity.state.native_value == initial_value

    # test updating entity state from client
    color_cluster.read_attributes.reset_mock()
    assert entity.state.native_value == initial_value
    color_cluster.PLUGGED_ATTR_READS = {attr: new_value}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert color_cluster.read_attributes.await_count == 1
    assert color_cluster.read_attributes.mock_calls == [
        call(
            [
                attr,
            ],
            allow_cache=False,
            only_cache=False,
            manufacturer=UNDEFINED,
        ),
    ]
    assert entity.state.native_value == new_value

    # update value from device
    await send_attributes_report(
        zha_gateway,
        color_cluster,
        {color_cluster.attributes_by_name[attr].id: initial_value},
    )
    await zha_gateway.async_block_till_done()
    assert entity.state.native_value == initial_value


async def test_heat_setpoint_limit_ranges_follow_each_other(
    zha_gateway: Gateway,
) -> None:
    """Test the min/max heat setpoint limit ranges follow the other limit."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_PROFILE: zha.PROFILE_ID,
                SIG_EP_TYPE: zha.DeviceType.THERMOSTAT,
                SIG_EP_INPUT: [general.Basic.cluster_id, hvac.Thermostat.cluster_id],
                SIG_EP_OUTPUT: [],
            }
        },
    )
    thermostat = zigpy_device.endpoints[1].thermostat
    thermostat.PLUGGED_ATTR_READS = {
        "abs_min_heat_setpoint_limit": 500,
        "abs_max_heat_setpoint_limit": 3500,
        "min_heat_setpoint_limit": 700,
        "max_heat_setpoint_limit": 3000,
    }
    update_attribute_cache(thermostat)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    min_limit = get_entity(
        zha_device, platform=Platform.NUMBER, qualifier="min_heat_setpoint_limit"
    )
    max_limit = get_entity(
        zha_device, platform=Platform.NUMBER, qualifier="max_heat_setpoint_limit"
    )
    assert min_limit.state.native_min_value == 5.0
    assert min_limit.state.native_max_value == 30.0
    assert max_limit.state.native_min_value == 7.0
    assert max_limit.state.native_max_value == 35.0

    # Writing one limit moves the bound of the other one
    await min_limit.async_set_native_value(16.0)
    await zha_gateway.async_block_till_done()
    assert min_limit.state.native_value == 16.0
    assert max_limit.state.native_min_value == 16.0

    # So does a value reported by the device
    await send_attributes_report(
        zha_gateway,
        thermostat,
        {hvac.Thermostat.AttributeDefs.max_heat_setpoint_limit.id: 2200},
    )
    await zha_gateway.async_block_till_done()
    assert max_limit.state.native_value == 22.0
    assert min_limit.state.native_max_value == 22.0


async def test_parkside_valve_timer_duration_not_duplicated(
    zha_gateway: Gateway,
) -> None:
    """Test the Parkside valve's timer duration number is exposed once, by its quirk."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    general.Identify.cluster_id,
                    general.Groups.cluster_id,
                    general.Scenes.cluster_id,
                    general.OnOff.cluster_id,
                    0xEF00,  # Tuya manufacturer cluster
                ],
                SIG_EP_OUTPUT: [general.Time.cluster_id, general.Ota.cluster_id],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="_TZE200_htnnfasr",
        model="TS0601",
        attributes={1: {"tuya_manufacturer": {"timer_duration": 10}}},
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    numbers = [
        entity
        for entity in zha_device.platform_entities.values()
        if entity.PLATFORM == Platform.NUMBER
        and getattr(entity, "_attribute_name", None) == "timer_duration"
    ]
    assert len(numbers) == 1
    assert numbers[0].state.native_value == 10


@pytest.mark.parametrize(
    ("engineering_units", "unit"),
    [
        (20, "BTU"),  # BTUs
        (41, "ton"),  # tons
        (90, "°"),  # degrees-angular
        (117, "BTU/lb"),  # BTUs-per-pound
        (136, "L/h"),  # liters-per-hour
        (137, "kWh/m²"),  # kilowatt-hours-per-square-meter
        (138, "kWh/ft²"),  # kilowatt-hours-per-square-foot
        (161, "mm/s"),  # millimeters-per-second
        (200, "dBmV"),  # decibels-millivolt
        (201, "dBV"),  # decibels-volt
        (246, "A²·h"),  # ampere-square-hours
    ],
)
async def test_number_engineering_units(
    zha_gateway: Gateway,
    engineering_units: int,
    unit: str,
) -> None:
    """Test the BACnet engineering units are shown as the unit they name."""
    zigpy_analog_output_device = create_mock_zigpy_device(
        zha_gateway, ZIGPY_ANALOG_OUTPUT_DEVICE
    )
    cluster: general.AnalogOutput = zigpy_analog_output_device.endpoints.get(
        1
    ).analog_output
    cluster.PLUGGED_ATTR_READS = {
        "max_present_value": 100.0,
        "min_present_value": 0.0,
        "engineering_units": engineering_units,
        "present_value": 50.0,
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_analog_output_device)
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.NUMBER)

    assert entity.state.native_unit_of_measurement == unit
