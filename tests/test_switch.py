"""Test zha switch."""

from collections.abc import Awaitable, Callable
import logging
from typing import Optional
from unittest.mock import call, patch

import pytest
from slugify import slugify
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import general
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.gateway import ZHAGateway
from zha.application.platforms import GroupEntity, PlatformEntity
from zha.exceptions import ZHAException
from zha.zigbee.device import ZHADevice
from zha.zigbee.group import Group, GroupMemberReference

from .common import (
    async_find_group_entity_id,
    find_entity_id,
    send_attributes_report,
    update_attribute_cache,
)
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

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
            SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return zigpy_device_mock(endpoints)


@pytest.fixture
async def device_switch_1(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha switch platform."""

    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE,
    )
    zha_device = await device_joined(zigpy_dev)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_switch_2(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
) -> ZHADevice:
    """Test zha switch platform."""

    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
    )
    zha_device = await device_joined(zigpy_dev)
    zha_device.available = True
    return zha_device


async def test_switch(
    device_joined: Callable[[ZigpyDevice], Awaitable[ZHADevice]],
    zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_gateway: ZHAGateway,
) -> None:
    """Test zha switch platform."""
    zha_device = await device_joined(zigpy_device)
    cluster = zigpy_device.endpoints.get(1).on_off
    entity_id = find_entity_id(Platform.SWITCH, zha_device)
    assert entity_id is not None

    entity: PlatformEntity = get_entity(zha_device, entity_id)  # type: ignore
    assert entity is not None

    assert bool(bool(entity.get_state()["state"])) is False

    # turn on at switch
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert bool(entity.get_state()["state"]) is True

    # turn off at switch
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert bool(entity.get_state()["state"]) is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert bool(entity.get_state()["state"]) is True
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
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x01, zcl_f.Status.FAILURE],
        ),
        pytest.raises(ZHAException, match="Failed to turn off"),
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert bool(entity.get_state()["state"]) is True
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
        return_value=[0x01, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert bool(entity.get_state()["state"]) is False
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
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x01, zcl_f.Status.FAILURE],
        ),
        pytest.raises(ZHAException, match="Failed to turn on"),
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert bool(entity.get_state()["state"]) is False
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
    assert bool(entity.get_state()["state"]) is False
    cluster.PLUGGED_ATTR_READS = {"on_off": True}
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert bool(entity.get_state()["state"]) is True


async def test_zha_group_switch_entity(
    device_switch_1: ZHADevice,  # pylint: disable=redefined-outer-name
    device_switch_2: ZHADevice,  # pylint: disable=redefined-outer-name
    zha_gateway: ZHAGateway,
) -> None:
    """Test the switch entity for a ZHA group."""
    member_ieee_addresses = [device_switch_1.ieee, device_switch_2.ieee]
    members = [
        GroupMemberReference(ieee=device_switch_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_switch_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await zha_gateway.async_create_zigpy_group("Test Group", members)
    await zha_gateway.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity_id = async_find_group_entity_id(Platform.SWITCH, zha_group)
    assert entity_id is not None

    entity: GroupEntity = get_group_entity(zha_group, entity_id)  # type: ignore
    assert entity is not None

    assert isinstance(entity, GroupEntity)

    group_cluster_on_off = zha_group.zigpy_group.endpoint[general.OnOff.cluster_id]
    dev1_cluster_on_off = device_switch_1.device.endpoints[1].on_off
    dev2_cluster_on_off = device_switch_2.device.endpoints[1].on_off

    # test that the lights were created and are off
    assert bool(entity.get_state()["state"]) is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        # turn on via UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(group_cluster_on_off.request.mock_calls) == 1
        assert group_cluster_on_off.request.call_args == call(
            False,
            ON,
            group_cluster_on_off.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
    assert bool(entity.get_state()["state"]) is True

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x01, zcl_f.Status.SUCCESS],
    ):
        # turn off via UI
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert len(group_cluster_on_off.request.mock_calls) == 1
        assert group_cluster_on_off.request.call_args == call(
            False,
            OFF,
            group_cluster_on_off.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
    assert bool(entity.get_state()["state"]) is False

    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # test that group light is on
    assert bool(entity.get_state()["state"]) is True

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is still on
    assert bool(entity.get_state()["state"]) is True

    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is now off
    assert bool(entity.get_state()["state"]) is False

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # test that group light is now back on
    assert bool(entity.get_state()["state"]) is True


def get_entity(zha_dev: ZHADevice, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]


def get_group_entity(group: Group, entity_id: str) -> Optional[GroupEntity]:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in group.group_entities.values()
    }

    return entities.get(entity_id)
