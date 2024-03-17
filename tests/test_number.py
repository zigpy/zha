"""Test zha analog output."""
from typing import Awaitable, Callable, Optional
from unittest.mock import call

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha as zha
import zigpy.types
import zigpy.zcl.clusters.general as general

from zhaws.client.controller import Controller
from zhaws.client.model.types import NumberEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device

from .common import find_entity, send_attributes_report, update_attribute_cache
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE


@pytest.fixture
def zigpy_analog_output_device(
    zigpy_device_mock: Callable[..., ZigpyDevice]
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


async def test_number(
    zigpy_analog_output_device: ZigpyDevice,
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha number platform."""
    controller, server = connected_client_and_server
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

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity: NumberEntity = find_entity(client_device, Platform.NUMBER)  # type: ignore
    assert entity is not None
    assert isinstance(entity, NumberEntity)

    assert cluster.read_attributes.call_count == 3

    # test that the state is 15.0
    assert entity.state.state == "15.0"

    # test attributes
    assert entity.min_value == 1.0
    assert entity.max_value == 100.0
    assert entity.step == 1.1

    # change value from device
    assert cluster.read_attributes.call_count == 3
    await send_attributes_report(server, cluster, {0x0055: 15})
    await server.block_till_done()
    assert entity.state.state == "15.0"

    # update value from device
    await send_attributes_report(server, cluster, {0x0055: 20})
    await server.block_till_done()
    assert entity.state.state == "20.0"

    # change value from client
    await controller.numbers.set_value(entity, 30.0)
    await server.block_till_done()

    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call({"present_value": 30.0})
    assert entity.state.state == "30.0"
