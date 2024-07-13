"""Test zha application helpers."""

from collections.abc import Awaitable, Callable
import logging

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters.general import Basic, OnOff

from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application.gateway import Gateway
from zha.application.helpers import async_is_bindable_target, get_matched_clusters
from zha.zigbee.device import Device

ON = 1
OFF = 0
IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"
_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def zigpy_device(zigpy_device_mock: Callable[..., ZigpyDevice]) -> ZigpyDevice:
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [Basic.cluster_id, OnOff.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    zigpy_dev: ZigpyDevice = zigpy_device_mock(endpoints)
    # this one is mains powered
    zigpy_dev.node_desc.mac_capability_flags |= 0b_0000_0100
    return zigpy_dev


@pytest.fixture
def remote_zigpy_device(zigpy_device_mock: Callable[..., ZigpyDevice]) -> ZigpyDevice:
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [Basic.cluster_id],
            SIG_EP_OUTPUT: [OnOff.cluster_id],
            SIG_EP_TYPE: zha.DeviceType.REMOTE_CONTROL,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    remote_zigpy_dev: ZigpyDevice = zigpy_device_mock(
        endpoints, ieee=IEEE_GROUPABLE_DEVICE, nwk=0x1234
    )
    return remote_zigpy_dev


async def test_async_is_bindable_target(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    remote_zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test zha if a device is a binding target for another device."""
    zha_device = await device_joined(zigpy_device)
    remote_zha_device = await device_joined(remote_zigpy_device)

    assert async_is_bindable_target(remote_zha_device, zha_device)


async def test_get_matched_clusters(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    remote_zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test getting matched clusters for 2 zha devices."""
    zha_device = await device_joined(zigpy_device)
    remote_zha_device = await device_joined(remote_zigpy_device)

    matches = await get_matched_clusters(remote_zha_device, zha_device)
    assert len(matches) == 1
    assert (
        matches[0].source_cluster
        == remote_zha_device.device.endpoints[1].out_clusters[OnOff.cluster_id]
    )
    assert matches[0].target_ieee == zha_device.ieee
    assert matches[0].target_ep_id == 1
