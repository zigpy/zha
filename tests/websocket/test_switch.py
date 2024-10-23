"""Test zha switch."""

import asyncio
import logging
from typing import Optional
from unittest.mock import call, patch

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
import zigpy.profiles.zha
from zigpy.zcl.clusters import general
import zigpy.zcl.foundation as zcl_f

from tests.common import mock_coro
from zha.application.discovery import Platform
from zha.application.platforms.model import (
    BasePlatformEntity,
    SwitchEntity,
    SwitchGroupEntity,
)
from zha.websocket.client.controller import Controller
from zha.websocket.client.proxy import DeviceProxy, GroupProxy
from zha.websocket.server.gateway import WebSocketGateway as Server
from zha.zigbee.device import Device
from zha.zigbee.group import Group, GroupMemberReference

from ..common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    async_find_group_entity_id,
    create_mock_zigpy_device,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)

ON = 1
OFF = 0
IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"
_LOGGER = logging.getLogger(__name__)


def find_entity(
    device_proxy: DeviceProxy, platform: Platform
) -> Optional[BasePlatformEntity]:
    """Find an entity for the specified platform on the given device."""
    for entity in device_proxy.device_model.entities.values():
        if entity.platform == platform:
            return entity
    return None


def get_group_entity(
    group_proxy: GroupProxy, entity_id: str
) -> Optional[SwitchGroupEntity]:
    """Get entity."""

    return group_proxy.group_model.entities.get(entity_id)


@pytest.fixture
def zigpy_device(connected_client_and_server: tuple[Controller, Server]) -> ZigpyDevice:
    """Device tracker zigpy device."""
    controller, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
    )
    return zigpy_device


@pytest.fixture
async def device_switch_1(
    connected_client_and_server: tuple[Controller, Server],
) -> Device:
    """Test zha switch platform."""

    _, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE,
    )
    zha_device = await join_zigpy_device(server, zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_switch_2(
    connected_client_and_server: tuple[Controller, Server],
) -> Device:
    """Test zha switch platform."""

    _, server = connected_client_and_server
    zigpy_device = create_mock_zigpy_device(
        server,
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
    )
    zha_device = await join_zigpy_device(server, zigpy_device)
    zha_device.available = True
    return zha_device


async def test_switch(
    zigpy_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha switch platform."""
    controller, server = connected_client_and_server
    zha_device = await join_zigpy_device(server, zigpy_device)
    cluster = zigpy_device.endpoints.get(1).on_off

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity: SwitchEntity = find_entity(client_device, Platform.SWITCH)
    assert entity is not None

    assert isinstance(entity, SwitchEntity)

    assert entity.state.state is False

    # turn on at switch
    await send_attributes_report(server, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.state.state is True

    # turn off at switch
    await send_attributes_report(server, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.state.state is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await controller.switches.turn_on(entity)
        await server.async_block_till_done()
        assert entity.state.state is True
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            ON,
            cluster.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # Fail turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x01, zcl_f.Status.FAILURE]),
    ):
        await controller.switches.turn_off(entity)
        await server.async_block_till_done()
        assert entity.state.state is True
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            OFF,
            cluster.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await controller.switches.turn_off(entity)
        await server.async_block_till_done()
        assert entity.state.state is False
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            OFF,
            cluster.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # Fail turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x01, zcl_f.Status.FAILURE],
    ):
        await controller.switches.turn_on(entity)
        await server.async_block_till_done()
        assert entity.state.state is False
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            ON,
            cluster.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # test updating entity state from client
    assert entity.state.state is False
    cluster.PLUGGED_ATTR_READS = {"on_off": True}
    update_attribute_cache(cluster)
    await controller.entities.refresh_state(entity)
    await server.async_block_till_done()
    assert entity.state.state is True


@pytest.mark.looptime
async def test_zha_group_switch_entity(
    device_switch_1: Device,
    device_switch_2: Device,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test the switch entity for a ZHA group."""
    controller, server = connected_client_and_server
    member_ieee_addresses = [device_switch_1.ieee, device_switch_2.ieee]
    members = [
        GroupMemberReference(ieee=device_switch_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_switch_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await server.async_create_zigpy_group("Test Group", members)
    await server.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.SWITCH, zha_group)
    assert entity_id is not None

    group_proxy: Optional[GroupProxy] = controller.groups.get(2)
    assert group_proxy is not None

    entity: SwitchGroupEntity = get_group_entity(group_proxy, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, SwitchGroupEntity)

    group_cluster_on_off = zha_group.zigpy_group.endpoint[general.OnOff.cluster_id]
    dev1_cluster_on_off = device_switch_1.device.endpoints[1].on_off
    dev2_cluster_on_off = device_switch_2.device.endpoints[1].on_off

    # test that the lights were created and are off
    assert entity.state.state is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        # turn on via UI
        await controller.switches.turn_on(entity)
        await server.async_block_till_done()
        assert len(group_cluster_on_off.request.mock_calls) == 1
        assert group_cluster_on_off.request.call_args == call(
            False,
            ON,
            group_cluster_on_off.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
    assert entity.state.state is True

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        # turn off via UI
        await controller.switches.turn_off(entity)
        await server.async_block_till_done()
        assert len(group_cluster_on_off.request.mock_calls) == 1
        assert group_cluster_on_off.request.call_args == call(
            False,
            OFF,
            group_cluster_on_off.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
    assert entity.state.state is False

    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(server, dev1_cluster_on_off, {0: 1})
    await send_attributes_report(server, dev2_cluster_on_off, {0: 1})
    await server.async_block_till_done()

    # group member updates are debounced
    assert entity.state.state is False
    await asyncio.sleep(1)
    await server.async_block_till_done()

    # test that group light is on
    assert entity.state.state is True

    await send_attributes_report(server, dev1_cluster_on_off, {0: 0})
    await server.async_block_till_done()

    # test that group light is still on
    assert entity.state.state is True

    await send_attributes_report(server, dev2_cluster_on_off, {0: 0})
    await server.async_block_till_done()

    # group member updates are debounced
    assert entity.state.state is True
    await asyncio.sleep(1)
    await server.async_block_till_done()

    # test that group light is now off
    assert entity.state.state is False

    await send_attributes_report(server, dev1_cluster_on_off, {0: 1})
    await server.async_block_till_done()

    # group member updates are debounced
    assert entity.state.state is False
    await asyncio.sleep(1)
    await server.async_block_till_done()

    # test that group light is now back on
    assert entity.state.state is True

    # test value error calling client api with wrong entity type
    with pytest.raises(ValueError):
        await controller.sirens.turn_on(entity)
        await server.async_block_till_done()
