"""Test ZHA button."""

from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest
from zigpy.const import SIG_EP_PROFILE
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.button import ZHAButton
from zha.zigbee.device import ZHADevice

from .common import find_entity, mock_coro
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE


@pytest.fixture
async def contact_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> tuple[ZHADevice, general.Identify]:
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

    zha_device: ZHADevice = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].identify


async def test_button(
    contact_sensor: tuple[ZHADevice, general.Identify],
    zha_gateway,
) -> None:
    """Test zha button platform."""

    zha_device, cluster = contact_sensor
    gateway = await zha_gateway()
    assert cluster is not None
    entity: PlatformEntity = find_entity(zha_device, Platform.BUTTON)  # type: ignore
    assert entity is not None
    assert isinstance(entity, ZHAButton)
    assert entity.PLATFORM == Platform.BUTTON

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_press()
        await gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 5  # duration in seconds
