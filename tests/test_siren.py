"""Test zha siren."""

import asyncio
from unittest.mock import patch

import pytest
from zigpy.const import SIG_EP_PROFILE
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    mock_coro,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms.siren import SirenEntityFeature
from zha.quirks import SIREN_BASIC
from zha.zigbee.device import Device


async def siren_mock(
    zha_gateway: Gateway,
    basic: bool = False,
) -> tuple[Device, security.IasWd]:
    """Siren fixture."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    if basic:
        zigpy_device.quirk_id = {SIREN_BASIC}

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device, zigpy_device.endpoints[1].ias_wd


async def test_siren(zha_gateway: Gateway) -> None:
    """Test zha siren platform."""

    zha_device, cluster = await siren_mock(zha_gateway)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.TONES
        | SirenEntityFeature.VOLUME_SET
        | SirenEntityFeature.DURATION
    )

    assert entity.state.is_on is False

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 50  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.is_on is True

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 2  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to off
    assert entity.state.is_on is False

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 51  # bitmask for specified args
        assert kw["warning_duration"] == 100  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.is_on is True


async def test_basic_siren(zha_gateway: Gateway) -> None:
    """Test zha basic siren."""

    zha_device, cluster = await siren_mock(zha_gateway, basic=True)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)
    assert entity.supported_features == (
        SirenEntityFeature.TURN_ON
        | SirenEntityFeature.TURN_OFF
        | SirenEntityFeature.DURATION
    )

    assert entity.state.is_on is False

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 18  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.is_on is True

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 2  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to off
    assert entity.state.is_on is False

    # turn on from client with duration option
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on(duration=100)
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 18  # bitmask for specified args
        assert kw["warning_duration"] == 100  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.is_on is True


async def test_siren_timed_off(zha_gateway: Gateway) -> None:
    """Test zha siren platform."""
    zha_device, cluster = await siren_mock(zha_gateway)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)

    assert entity.state.is_on is False

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
        kw = cluster.request.call_args.kwargs
        assert kw["warning"] == 50  # bitmask for default args
        assert kw["warning_duration"] == 5  # duration in seconds
        assert kw["strobe_duty_cycle"] == 0
        assert kw["strobe_level"] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.is_on is True

    await asyncio.sleep(6)

    # test that the state has changed to off from the timer
    assert entity.state.is_on is False


async def test_siren_squawk(zha_gateway: Gateway) -> None:
    """Test zha siren squawk."""
    zha_device, cluster = await siren_mock(zha_gateway)
    assert cluster is not None

    entity = get_entity(zha_device, platform=Platform.SIREN)

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x01, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_squawk(mode=1, strobe=1, squawk_level=3)
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert (
            cluster.request.call_args[0][1]
            == security.IasWd.ServerCommandDefs.squawk.id
        )
        assert cluster.request.call_args.kwargs["squawk"] == security.Squawk(
            mode=security.SquawkMode.Disarmed,
            strobe=security.SquawkStrobe.Strobe,
            level=security.SquawkLevel.Very_high_level_sound,
        )


@pytest.mark.parametrize("basic", [False, True])
async def test_siren_failed_turn_on_keeps_off_timer(
    zha_gateway: Gateway, basic: bool
) -> None:
    """Test a failed turn on doesn't leave the siren on forever."""
    zha_device, _ = await siren_mock(zha_gateway, basic=basic)
    entity = get_entity(zha_device, platform=Platform.SIREN)

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_turn_on(duration=60)
    assert entity.state.is_on is True

    # a second turn on that fails must not drop the first one's off timer
    with (
        patch("zigpy.zcl.Cluster.request", side_effect=asyncio.TimeoutError),
        pytest.raises(asyncio.TimeoutError),
    ):
        await entity.async_turn_on(duration=60)
    assert entity.state.is_on is True

    await asyncio.sleep(61)
    assert entity.state.is_on is False


@pytest.mark.parametrize("basic", [False, True])
async def test_siren_overlapping_turn_on(zha_gateway: Gateway, basic: bool) -> None:
    """Test overlapping turn on calls keep the last call's off timer."""
    zha_device, _ = await siren_mock(zha_gateway, basic=basic)
    entity = get_entity(zha_device, platform=Platform.SIREN)

    async def slow_request(*args, **kwargs):
        await asyncio.sleep(0.1)
        return [0x00, zcl_f.Status.SUCCESS]

    with patch("zigpy.zcl.Cluster.request", side_effect=slow_request):
        await asyncio.gather(
            entity.async_turn_on(duration=5),
            entity.async_turn_on(duration=60),
        )
    assert entity.state.is_on is True

    # the device was last told to sound for 60 seconds
    await asyncio.sleep(10)
    assert entity.state.is_on is True

    await asyncio.sleep(51)
    assert entity.state.is_on is False
