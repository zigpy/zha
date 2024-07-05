"""Test zha number platform."""

from collections.abc import Awaitable, Callable
from unittest.mock import call

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl.clusters import general, lighting

from tests.common import get_entity, send_attributes_report, update_attribute_cache
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.platforms.number.const import NumberMode
from zha.exceptions import ZHAException
from zha.zigbee.device import Device


@pytest.fixture
def zigpy_analog_output_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy analog_output device."""

    endpoints = {
        1: {
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROL_SWITCH,
            SIG_EP_INPUT: [general.AnalogOutput.cluster_id, general.Basic.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return zigpy_device_mock(endpoints)


@pytest.fixture
async def light(zigpy_device_mock: Callable[..., ZigpyDevice]) -> ZigpyDevice:
    """Siren fixture."""

    zigpy_device = zigpy_device_mock(
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
        node_descriptor=b"\x02@\x84_\x11\x7fd\x00\x00,d\x00\x00",
    )

    return zigpy_device


async def test_number(
    zigpy_analog_output_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zha_gateway: Gateway,
) -> None:
    """Test zha number platform."""
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
    update_attribute_cache(cluster)
    cluster.PLUGGED_ATTR_READS["present_value"] = 15.0

    zha_device = await device_joined(zigpy_analog_output_device)
    # one for present_value and one for the rest configuration attributes
    assert cluster.read_attributes.call_count == 3
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

    assert cluster.read_attributes.call_count == 3

    assert entity.name == "PWM1"

    # test that the state is 15.0
    assert entity.state["state"] == 15.0

    # test attributes
    assert entity.info_object.min_value == 1.0
    assert entity.info_object.max_value == 100.0
    assert entity.info_object.step == 1.1

    assert entity.icon == "mdi:percent"
    assert entity.native_unit_of_measurement == "%"
    assert entity.mode == NumberMode.AUTO
    assert entity.native_min_value == 1.0
    assert entity.native_max_value == 100.0
    assert entity.native_step == 1.1

    # change value from device
    assert cluster.read_attributes.call_count == 3
    await send_attributes_report(zha_gateway, cluster, {0x0055: 15})
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == 15.0

    # update value from device
    await send_attributes_report(zha_gateway, cluster, {0x0055: 20})
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == 20.0

    # change value from client
    await entity.async_set_value(30.0)
    await zha_gateway.async_block_till_done()

    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"present_value": 30.0}, manufacturer=None
    )
    assert entity.state["state"] == 30.0

    # test updating entity state from client
    cluster.read_attributes.reset_mock()
    assert entity.state["state"] == 30.0
    cluster.PLUGGED_ATTR_READS = {"present_value": 20}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["present_value"], allow_cache=False, only_cache=False, manufacturer=None
    )
    assert entity.state["state"] == 20.0

    await entity.async_set_native_value(30)
    await zha_gateway.async_block_till_done()
    assert len(cluster.write_attributes.mock_calls) == 2
    assert cluster.write_attributes.call_args == call(
        {"present_value": 30}, manufacturer=None
    )
    assert entity.state["state"] == 30.0


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
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    light: Device,  # pylint: disable=redefined-outer-name
    device_joined,
    attr: str,
    initial_value: int,
    new_value: int,
    max_value: int,
) -> None:
    """Test ZHA level control number entities - new join."""

    level_control_cluster = light.endpoints[1].level
    level_control_cluster.PLUGGED_ATTR_READS = {
        attr: initial_value,
    }
    zha_device = await device_joined(light)

    entity = get_entity(zha_device, platform=Platform.NUMBER, qualifier=attr)

    assert level_control_cluster.read_attributes.mock_calls == [
        call(
            [
                "on_off_transition_time",
                "on_level",
                "on_transition_time",
                "off_transition_time",
                "default_move_rate",
            ],
            allow_cache=True,
            only_cache=False,
            manufacturer=None,
        ),
        call(
            ["start_up_current_level"],
            allow_cache=True,
            only_cache=False,
            manufacturer=None,
        ),
        call(
            [
                "current_level",
            ],
            allow_cache=False,
            only_cache=False,
            manufacturer=None,
        ),
    ]

    assert entity.state["state"] == initial_value
    assert entity._attr_entity_category == EntityCategory.CONFIG

    assert entity.icon is None
    assert entity.native_unit_of_measurement is None
    assert entity.mode == NumberMode.AUTO
    assert entity.native_min_value == 0
    assert entity.native_max_value == max_value
    assert entity.native_step == 1.0

    await entity.async_set_native_value(new_value)
    assert level_control_cluster.write_attributes.mock_calls == [
        call({attr: new_value}, manufacturer=None)
    ]

    assert entity.state["state"] == new_value

    level_control_cluster.read_attributes.reset_mock()
    await entity.async_update()
    # the mocking doesn't update the attr cache so this flips back to initial value
    assert entity.state["state"] == initial_value
    assert level_control_cluster.read_attributes.mock_calls == [
        call(
            [attr],
            allow_cache=False,
            only_cache=False,
            manufacturer=None,
        )
    ]

    level_control_cluster.write_attributes.reset_mock()
    level_control_cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZHAException):
        await entity.async_set_native_value(new_value)

    assert level_control_cluster.write_attributes.mock_calls == [
        call({attr: new_value}, manufacturer=None),
        call({attr: new_value}, manufacturer=None),
        call({attr: new_value}, manufacturer=None),
    ]
    assert entity.state["state"] == initial_value

    # test updating entity state from client
    level_control_cluster.read_attributes.reset_mock()
    assert entity.state["state"] == initial_value
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
            manufacturer=None,
        ),
    ]
    assert entity.state["state"] == new_value

    # update value from device
    await send_attributes_report(
        zha_gateway,
        level_control_cluster,
        {level_control_cluster.attributes_by_name[attr].id: initial_value},
    )
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == initial_value


@pytest.mark.parametrize(
    ("attr", "initial_value", "new_value"),
    (("start_up_color_temperature", 500, 350),),
)
async def test_color_number(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
    light: Device,  # pylint: disable=redefined-outer-name
    device_joined,
    attr: str,
    initial_value: int,
    new_value: int,
) -> None:
    """Test ZHA color number entities - new join."""

    color_cluster = light.endpoints[1].light_color
    color_cluster.PLUGGED_ATTR_READS = {
        attr: initial_value,
    }
    zha_device = await device_joined(light)

    entity = get_entity(zha_device, platform=Platform.NUMBER, qualifier=attr)

    assert color_cluster.read_attributes.call_count == 3
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
            manufacturer=None,
        )
        in color_cluster.read_attributes.call_args_list
    )

    assert entity.state["state"] == initial_value
    assert entity._attr_entity_category == EntityCategory.CONFIG

    await entity.async_set_native_value(new_value)
    assert color_cluster.write_attributes.call_count == 1
    assert color_cluster.write_attributes.call_args[0][0] == {
        attr: new_value,
    }

    assert entity.state["state"] == new_value

    color_cluster.read_attributes.reset_mock()
    await entity.async_update()
    # the mocking doesn't update the attr cache so this flips back to initial value
    assert entity.state["state"] == initial_value
    assert color_cluster.read_attributes.call_count == 1
    assert (
        call(
            [attr],
            allow_cache=False,
            only_cache=False,
            manufacturer=None,
        )
        in color_cluster.read_attributes.call_args_list
    )

    color_cluster.write_attributes.reset_mock()
    color_cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZHAException):
        await entity.async_set_native_value(new_value)

    assert color_cluster.write_attributes.mock_calls == [
        call({attr: new_value}, manufacturer=None),
        call({attr: new_value}, manufacturer=None),
        call({attr: new_value}, manufacturer=None),
    ]
    assert entity.state["state"] == initial_value

    # test updating entity state from client
    color_cluster.read_attributes.reset_mock()
    assert entity.state["state"] == initial_value
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
            manufacturer=None,
        ),
    ]
    assert entity.state["state"] == new_value

    # update value from device
    await send_attributes_report(
        zha_gateway,
        color_cluster,
        {color_cluster.attributes_by_name[attr].id: initial_value},
    )
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == initial_value
