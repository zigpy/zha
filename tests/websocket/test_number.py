"""Test zha analog output."""

from typing import Optional
from unittest.mock import call

from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl.clusters import general

from zha.application.discovery import Platform
from zha.application.gateway import WebSocketClientGateway, WebSocketServerGateway
from zha.application.platforms.model import BasePlatformEntity, NumberEntity
from zha.zigbee.device import WebSocketClientDevice

from ..common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)


def find_entity(
    device_proxy: WebSocketClientDevice, platform: Platform
) -> Optional[BasePlatformEntity]:
    """Find an entity for the specified platform on the given device."""
    for entity in device_proxy.platform_entities.values():
        if entity.platform == platform:
            return entity
    return None


async def test_number(
    connected_client_and_server: tuple[WebSocketClientGateway, WebSocketServerGateway],
) -> None:
    """Test zha number platform."""
    controller, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROL_SWITCH,
                SIG_EP_INPUT: [
                    general.AnalogOutput.cluster_id,
                    general.Basic.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )
    cluster: general.AnalogOutput = zigpy_device.endpoints.get(1).analog_output
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

    zha_device = await join_zigpy_device(server, zigpy_device)
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

    client_device: Optional[WebSocketClientDevice] = controller.devices.get(
        zha_device.ieee
    )
    assert client_device is not None
    entity: NumberEntity = find_entity(client_device, Platform.NUMBER)  # type: ignore
    assert entity is not None
    assert isinstance(entity, NumberEntity)

    assert cluster.read_attributes.call_count == 3

    # test that the state is 15.0
    assert entity.state.state == 15.0

    # test attributes
    assert entity.min_value == 1.0
    assert entity.max_value == 100.0
    assert entity.step == 1.1

    # change value from device
    assert cluster.read_attributes.call_count == 3
    await send_attributes_report(server, cluster, {0x0055: 15})
    await server.async_block_till_done()
    assert entity.state.state == 15.0

    # update value from device
    await send_attributes_report(server, cluster, {0x0055: 20})
    await server.async_block_till_done()
    assert entity.state.state == 20.0

    # change value from client
    await controller.numbers.set_value(entity, 30.0)
    await server.async_block_till_done()

    assert len(cluster.write_attributes.mock_calls) == 1
    assert cluster.write_attributes.call_args == call(
        {"present_value": 30.0}, manufacturer=None
    )
    assert entity.state.state == 30.0
