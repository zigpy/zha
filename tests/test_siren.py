"""Test zha siren."""

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest
from zigpy.const import SIG_EP_PROFILE
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f

from tests.common import get_entity, mock_coro
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms.siren import SirenEntityFeature
from zha.zigbee.device import Device


@pytest.fixture
async def siren(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> tuple[Device, security.IasWd]:
    """Siren fixture."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zha_device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].ias_wd


async def test_siren(
    siren: tuple[Device, security.IasWd],  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
) -> None:
    """Test zha siren platform."""

    zha_device, cluster = siren
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.TONES
        | SirenEntityFeature.VOLUME_SET
        | SirenEntityFeature.DURATION
    )

    assert entity.state["state"] is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True

    # turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 2  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to off
    assert entity.state["state"] is False

    # turn on from client with options
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on(duration=100, volume_level=3, tone=3)
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 51  # bitmask for specified args
        assert cluster.request.call_args[0][4] == 100  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True


@pytest.mark.looptime
async def test_siren_timed_off(
    siren: tuple[Device, security.IasWd],  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
) -> None:
    """Test zha siren platform."""
    zha_device, cluster = siren
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)

    assert entity.state["state"] is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state["state"] is True

    await asyncio.sleep(6)

    # test that the state has changed to off from the timer
    assert entity.state["state"] is False
