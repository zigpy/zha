"""Test zha siren."""

import asyncio
from typing import Optional
from unittest.mock import patch

import pytest
from zigpy.const import SIG_EP_PROFILE
from zigpy.profiles import zha
from zigpy.zcl.clusters import general, security
import zigpy.zcl.foundation as zcl_f

from zha.application.discovery import Platform
from zha.application.platforms.model import BasePlatformEntity
from zha.websocket.client.controller import Controller
from zha.websocket.client.proxy import DeviceProxy
from zha.websocket.server.gateway import WebSocketGateway as Server
from zha.zigbee.device import Device

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


@pytest.fixture
async def siren(
    connected_client_and_server: tuple[Controller, Server],
) -> tuple[Device, security.IasWd]:
    """Siren fixture."""

    _, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zha_device = await join_zigpy_device(server, zigpy_device)
    return zha_device, zigpy_device.endpoints[1].ias_wd


async def test_siren(
    siren: tuple[Device, security.IasWd],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha siren platform."""

    zha_device, cluster = siren
    assert cluster is not None
    controller, server = connected_client_and_server

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = find_entity(client_device, Platform.SIREN)
    assert entity is not None

    assert entity.state.state is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await controller.sirens.turn_on(entity)
        await server.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.state is True

    # turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await controller.sirens.turn_off(entity)
        await server.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 2  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to off
    assert entity.state.state is False

    # turn on from client with options
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await controller.sirens.turn_on(entity, duration=100, volume_level=3, tone=3)
        await server.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        # assert (cluster.request.call_args[0][3] == 51)  # bitmask for specified args TODO fix kwargs on siren methods so args are processed correctly
        assert cluster.request.call_args[0][4] == 100  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.state is True


@pytest.mark.looptime
async def test_siren_timed_off(
    siren: tuple[Device, security.IasWd],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha siren platform."""
    zha_device, cluster = siren
    assert cluster is not None
    controller, server = connected_client_and_server

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = find_entity(client_device, Platform.SIREN)
    assert entity is not None

    assert entity.state.state is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await controller.sirens.turn_on(entity)
        await server.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 50  # bitmask for default args
        assert cluster.request.call_args[0][4] == 5  # duration in seconds
        assert cluster.request.call_args[0][5] == 0
        assert cluster.request.call_args[0][6] == 2
        cluster.request.reset_mock()

    # test that the state has changed to on
    assert entity.state.state is True

    await asyncio.sleep(6)

    # test that the state has changed to off from the timer
    assert entity.state.state is False
