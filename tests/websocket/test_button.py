"""Test ZHA button."""

from typing import Optional
from unittest.mock import patch

from zigpy.const import SIG_EP_PROFILE
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f

from zha.application.discovery import Platform
from zha.application.platforms.model import BasePlatformEntity, ButtonEntity
from zha.websocket.client.controller import Controller
from zha.websocket.client.proxy import DeviceProxy
from zha.websocket.server.gateway import WebSocketGateway as Server

from ..common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    mock_coro,
)


def find_entity(
    device_proxy: DeviceProxy, platform: Platform
) -> Optional[BasePlatformEntity]:
    """Find an entity for the specified platform on the given device."""
    for entity in device_proxy.device_model.entities.values():
        if entity.platform == platform:
            return entity
    return None


async def test_button(
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha button platform."""
    controller, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
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
    zhaws_device = await join_zigpy_device(server, zigpy_device)
    cluster = zigpy_device.endpoints[1].identify

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
        await server.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 5  # duration in seconds
