"""Test zha lock."""

from collections.abc import Awaitable, Callable
from unittest.mock import patch

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
from zigpy.zcl.clusters import closures, general
import zigpy.zcl.foundation as zcl_f

from tests.common import get_entity, send_attributes_report, update_attribute_cache
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.lock.const import STATE_LOCKED, STATE_UNLOCKED
from zha.zigbee.device import Device

LOCK_DOOR = 0
UNLOCK_DOOR = 1
SET_PIN_CODE = 5
CLEAR_PIN_CODE = 7
SET_USER_STATUS = 9


@pytest.fixture
async def lock(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> tuple[Device, closures.DoorLock]:
    """Lock cluster fixture."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [closures.DoorLock.cluster_id, general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.DOOR_LOCK,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
    )

    zha_device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].door_lock


async def test_lock(
    lock: tuple[Device, closures.DoorLock],  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
) -> None:
    """Test zha lock platform."""

    zha_device, cluster = lock
    entity = get_entity(zha_device, platform=Platform.LOCK)

    assert entity.state["is_locked"] is False

    # set state to locked
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.state["is_locked"] is True

    # set state to unlocked
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 2, 2: 3})
    assert entity.state["is_locked"] is False

    # lock from HA
    await async_lock(zha_gateway, cluster, entity)

    # unlock from HA
    await async_unlock(zha_gateway, cluster, entity)

    # set user code
    await async_set_user_code(zha_gateway, cluster, entity)

    # clear user code
    await async_clear_user_code(zha_gateway, cluster, entity)

    # enable user code
    await async_enable_user_code(zha_gateway, cluster, entity)

    # disable user code
    await async_disable_user_code(zha_gateway, cluster, entity)

    # test updating entity state from client
    cluster.read_attributes.reset_mock()
    assert entity.state["is_locked"] is False
    cluster.PLUGGED_ATTR_READS = {"lock_state": 1}
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.call_count == 1
    assert entity.state["is_locked"] is True


async def async_lock(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test lock functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_lock()
        await zha_gateway.async_block_till_done()
        assert entity.state["is_locked"] is True
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == LOCK_DOOR
        cluster.request.reset_mock()

    # test unlock failure
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.FAILURE]):
        await entity.async_unlock()
        await zha_gateway.async_block_till_done()
        assert entity.state["is_locked"] is True
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == UNLOCK_DOOR
        cluster.request.reset_mock()


async def async_unlock(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test lock functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_unlock()
        await zha_gateway.async_block_till_done()
        assert entity.state["is_locked"] is False
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == UNLOCK_DOOR
        cluster.request.reset_mock()

    # test lock failure
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.FAILURE]):
        await entity.async_lock()
        await zha_gateway.async_block_till_done()
        assert entity.state["is_locked"] is False
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == LOCK_DOOR
        cluster.request.reset_mock()


async def async_set_user_code(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test set lock code functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_set_lock_user_code(3, "13246579")
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == SET_PIN_CODE
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2
        assert cluster.request.call_args[0][4] == closures.DoorLock.UserStatus.Enabled
        assert (
            cluster.request.call_args[0][5] == closures.DoorLock.UserType.Unrestricted
        )
        assert cluster.request.call_args[0][6] == "13246579"


async def async_clear_user_code(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test clear lock code functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_clear_lock_user_code(3)
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == CLEAR_PIN_CODE
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2


async def async_enable_user_code(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test enable lock code functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_enable_lock_user_code(3)
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == SET_USER_STATUS
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2
        assert cluster.request.call_args[0][4] == closures.DoorLock.UserStatus.Enabled


async def async_disable_user_code(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test disable lock code functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_disable_lock_user_code(3)
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == SET_USER_STATUS
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2
        assert cluster.request.call_args[0][4] == closures.DoorLock.UserStatus.Disabled


async def test_lock_state_restoration(
    lock: tuple[Device, closures.DoorLock],  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
) -> None:
    """Test the lock state restoration."""
    zha_device, _ = lock
    entity = get_entity(zha_device, platform=Platform.LOCK)

    assert entity.state["is_locked"] is False

    entity.restore_external_state_attributes(state=STATE_LOCKED)
    assert entity.state["is_locked"] is True

    entity.restore_external_state_attributes(state=STATE_UNLOCKED)
    assert entity.state["is_locked"] is False
