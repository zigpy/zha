"""Test ZHA device switch."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from unittest import mock
from unittest.mock import patch

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
import zigpy.types
from zigpy.zcl.clusters import general
import zigpy.zdo.types as zdo_t

from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE
from zha.application.gateway import Gateway
from zha.zigbee.device import Device


@pytest.fixture
def zigpy_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Callable[..., ZigpyDevice]:
    """Device tracker zigpy device."""

    def _dev(with_basic_cluster_handler: bool = True, **kwargs):
        in_clusters = [general.OnOff.cluster_id]
        if with_basic_cluster_handler:
            in_clusters.append(general.Basic.cluster_id)

        endpoints = {
            3: {
                SIG_EP_INPUT: in_clusters,
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
            }
        }
        return zigpy_device_mock(endpoints, **kwargs)

    return _dev


@pytest.fixture
def zigpy_device_mains(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Callable[..., ZigpyDevice]:
    """Device tracker zigpy device."""

    def _dev(with_basic_cluster_handler: bool = True):
        in_clusters = [general.OnOff.cluster_id]
        if with_basic_cluster_handler:
            in_clusters.append(general.Basic.cluster_id)

        endpoints = {
            3: {
                SIG_EP_INPUT: in_clusters,
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
            }
        }
        return zigpy_device_mock(
            endpoints, node_descriptor=b"\x02@\x84_\x11\x7fd\x00\x00,d\x00\x00"
        )

    return _dev


@pytest.fixture
def device_with_basic_cluster_handler(
    zigpy_device_mains: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> ZigpyDevice:
    """Return a ZHA device with a basic cluster handler present."""
    return zigpy_device_mains(with_basic_cluster_handler=True)


@pytest.fixture
def device_without_basic_cluster_handler(
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> ZigpyDevice:
    """Return a ZHA device without a basic cluster handler present."""
    return zigpy_device(with_basic_cluster_handler=False)


@pytest.fixture
async def ota_zha_device(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Device:
    """ZHA device with OTA cluster fixture."""
    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [general.Ota.cluster_id],
                SIG_EP_TYPE: 0x1234,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    zha_device = await device_joined(zigpy_dev)
    return zha_device


async def _send_time_changed(zha_gateway: Gateway, seconds: int):
    """Send a time changed event."""
    await asyncio.sleep(seconds)
    await zha_gateway.async_block_till_done()


@patch(
    "zha.zigbee.cluster_handlers.general.BasicClusterHandler.async_initialize",
    new=mock.AsyncMock(),
)
@pytest.mark.looptime
async def test_check_available_success(
    zha_gateway: Gateway,
    device_with_basic_cluster_handler: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> None:
    """Check device availability success on 1st try."""
    zha_device = await device_joined(device_with_basic_cluster_handler)
    basic_ch = device_with_basic_cluster_handler.endpoints[3].basic

    basic_ch.read_attributes.reset_mock()
    device_with_basic_cluster_handler.last_seen = None
    assert zha_device.available is True
    await _send_time_changed(zha_gateway, zha_device.consider_unavailable_time + 2)
    assert zha_device.available is False
    assert basic_ch.read_attributes.await_count == 0  # type: ignore[unreachable]

    device_with_basic_cluster_handler.last_seen = (
        time.time() - zha_device.consider_unavailable_time - 100
    )
    _seens = [time.time(), device_with_basic_cluster_handler.last_seen]

    def _update_last_seen(*args, **kwargs):  # pylint: disable=unused-argument
        new_last_seen = _seens.pop()
        device_with_basic_cluster_handler.last_seen = new_last_seen

    basic_ch.read_attributes.side_effect = _update_last_seen

    # successfully ping zigpy device, but zha_device is not yet available
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)
    assert basic_ch.read_attributes.await_count == 1
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is False

    # There was traffic from the device: pings, but not yet available
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)
    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is False

    # There was traffic from the device: don't try to ping, marked as available
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)
    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is True


@patch(
    "zha.zigbee.cluster_handlers.general.BasicClusterHandler.async_initialize",
    new=mock.AsyncMock(),
)
@pytest.mark.looptime
async def test_check_available_unsuccessful(
    zha_gateway: Gateway,
    device_with_basic_cluster_handler: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> None:
    """Check device availability all tries fail."""

    zha_device = await device_joined(device_with_basic_cluster_handler)
    basic_ch = device_with_basic_cluster_handler.endpoints[3].basic

    assert zha_device.available is True
    assert basic_ch.read_attributes.await_count == 0

    device_with_basic_cluster_handler.last_seen = (
        time.time() - zha_device.consider_unavailable_time - 2
    )

    # unsuccessfully ping zigpy device, but zha_device is still available
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)

    assert basic_ch.read_attributes.await_count == 1
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is True

    # still no traffic, but zha_device is still available
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)

    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is True

    # not even trying to update, device is unavailable
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)

    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is False


@patch(
    "zha.zigbee.cluster_handlers.general.BasicClusterHandler.async_initialize",
    new=mock.AsyncMock(),
)
@pytest.mark.looptime
async def test_check_available_no_basic_cluster_handler(
    zha_gateway: Gateway,
    device_without_basic_cluster_handler: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check device availability for a device without basic cluster."""
    caplog.set_level(logging.DEBUG, logger="homeassistant.components.zha")

    zha_device = await device_joined(device_without_basic_cluster_handler)

    assert zha_device.available is True

    device_without_basic_cluster_handler.last_seen = (
        time.time() - zha_device.consider_unavailable_time - 2
    )

    assert "does not have a mandatory basic cluster" not in caplog.text
    await _send_time_changed(zha_gateway, zha_device.__polling_interval + 1)

    assert zha_device.available is False
    assert "does not have a mandatory basic cluster" in caplog.text  # type: ignore[unreachable]


async def test_device_is_active_coordinator(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test that the current coordinator is uniquely detected."""

    current_coord_dev = zigpy_device(ieee="aa:bb:cc:dd:ee:ff:00:11", nwk=0x0000)
    current_coord_dev.node_desc = current_coord_dev.node_desc.replace(
        logical_type=zdo_t.LogicalType.Coordinator
    )

    old_coord_dev = zigpy_device(ieee="aa:bb:cc:dd:ee:ff:00:12", nwk=0x0000)
    old_coord_dev.node_desc = old_coord_dev.node_desc.replace(
        logical_type=zdo_t.LogicalType.Coordinator
    )

    # The two coordinators have different IEEE addresses
    assert current_coord_dev.ieee != old_coord_dev.ieee

    current_coordinator = await device_joined(current_coord_dev)
    stale_coordinator = await device_joined(old_coord_dev)

    # Ensure the current ApplicationController's IEEE matches our coordinator's
    current_coordinator.gateway.application_controller.state.node_info.ieee = (
        current_coord_dev.ieee
    )

    assert current_coordinator.is_active_coordinator
    assert not stale_coordinator.is_active_coordinator
