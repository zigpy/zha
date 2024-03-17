"""Test ZHA button."""
from typing import Awaitable, Callable, Optional
from unittest.mock import patch

import pytest
from zigpy.const import SIG_EP_PROFILE
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha as zha
import zigpy.zcl.clusters.general as general
import zigpy.zcl.clusters.security as security
import zigpy.zcl.foundation as zcl_f

from zhaws.client.controller import Controller
from zhaws.client.model.types import ButtonEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device

from .common import find_entity, mock_coro
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE


@pytest.fixture
async def contact_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> tuple[Device, general.Identify]:
    """Contact sensor fixture."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    general.Identify.cluster_id,
                    security.IasZone.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_ZONE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zhaws_device: Device = await device_joined(zigpy_device)
    return zhaws_device, zigpy_device.endpoints[1].identify


async def test_button(
    contact_sensor: tuple[Device, general.Identify],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha button platform."""

    zhaws_device, cluster = contact_sensor
    controller, server = connected_client_and_server
    assert cluster is not None
    client_device: Optional[DeviceProxy] = controller.devices.get(zhaws_device.ieee)
    assert client_device is not None
    entity: ButtonEntity = find_entity(client_device, Platform.BUTTON)  # type: ignore
    assert entity is not None
    assert isinstance(entity, ButtonEntity)

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await controller.buttons.press(entity)
        await server.block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 5  # duration in seconds
