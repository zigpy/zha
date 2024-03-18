"""Test zha lock."""
from collections.abc import Awaitable, Callable
from typing import Optional
from unittest.mock import patch

import pytest
from slugify import slugify
from zhaws.client.controller import Controller
from zhaws.client.model.types import LockEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.platforms.registries import Platform
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
from zigpy.zcl.clusters import closures, general
import zigpy.zcl.foundation as zcl_f

from tests.common import mock_coro

from .common import find_entity_id, send_attributes_report, update_attribute_cache
from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

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


def get_entity(zha_dev: DeviceProxy, entity_id: str) -> LockEntity:
    """Get entity."""
    entities = {
        entity.platform + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.device_model.entities.values()
    }
    return entities[entity_id]  # type: ignore


async def test_lock(
    lock: tuple[Device, closures.DoorLock],
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zha lock platform."""

    zha_device, cluster = lock
    controller, server = connected_client_and_server
    entity_id = find_entity_id(Platform.LOCK, zha_device)
    assert entity_id is not None

    client_device: Optional[DeviceProxy] = controller.devices.get(zha_device.ieee)
    assert client_device is not None
    entity = get_entity(client_device, entity_id)
    assert entity is not None

    assert entity.state.is_locked is False

    # set state to locked
    await send_attributes_report(server, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.state.is_locked is True

    # set state to unlocked
    await send_attributes_report(server, cluster, {1: 0, 0: 2, 2: 3})
    assert entity.state.is_locked is False

    # lock from HA
    await async_lock(server, cluster, entity, controller)

    # unlock from HA
    await async_unlock(server, cluster, entity, controller)

    # set user code
    await async_set_user_code(server, cluster, entity, controller)

    # clear user code
    await async_clear_user_code(server, cluster, entity, controller)

    # enable user code
    await async_enable_user_code(server, cluster, entity, controller)

    # disable user code
    await async_disable_user_code(server, cluster, entity, controller)

    # test updating entity state from client
    assert entity.state.is_locked is False
    cluster.PLUGGED_ATTR_READS = {"lock_state": 1}
    update_attribute_cache(cluster)
    await controller.entities.refresh_state(entity)
    await server.block_till_done()
    assert entity.state.is_locked is True


async def async_lock(
    server: Server,
    cluster: closures.DoorLock,
    entity: LockEntity,
    controller: Controller,
) -> None:
    """Test lock functionality from client."""
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.SUCCESS])
    ):
        await controller.locks.lock(entity)
        await server.block_till_done()
        assert entity.state.is_locked is True
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == LOCK_DOOR
        cluster.request.reset_mock()

    # test unlock failure
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.FAILURE])
    ):
        await controller.locks.unlock(entity)
        await server.block_till_done()
        assert entity.state.is_locked is True
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == UNLOCK_DOOR
        cluster.request.reset_mock()


async def async_unlock(
    server: Server,
    cluster: closures.DoorLock,
    entity: LockEntity,
    controller: Controller,
) -> None:
    """Test lock functionality from client."""
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.SUCCESS])
    ):
        await controller.locks.unlock(entity)
        await server.block_till_done()
        assert entity.state.is_locked is False
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == UNLOCK_DOOR
        cluster.request.reset_mock()

    # test lock failure
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.FAILURE])
    ):
        await controller.locks.lock(entity)
        await server.block_till_done()
        assert entity.state.is_locked is False
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == LOCK_DOOR
        cluster.request.reset_mock()


async def async_set_user_code(
    server: Server,
    cluster: closures.DoorLock,
    entity: LockEntity,
    controller: Controller,
) -> None:
    """Test set lock code functionality from client."""
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.SUCCESS])
    ):
        await controller.locks.set_user_lock_code(entity, 3, "13246579")
        await server.block_till_done()
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
    server: Server,
    cluster: closures.DoorLock,
    entity: LockEntity,
    controller: Controller,
) -> None:
    """Test clear lock code functionality from client."""
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.SUCCESS])
    ):
        await controller.locks.clear_user_lock_code(entity, 3)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == CLEAR_PIN_CODE
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2


async def async_enable_user_code(
    server: Server,
    cluster: closures.DoorLock,
    entity: LockEntity,
    controller: Controller,
) -> None:
    """Test enable lock code functionality from client."""
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.SUCCESS])
    ):
        await controller.locks.enable_user_lock_code(entity, 3)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == SET_USER_STATUS
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2
        assert cluster.request.call_args[0][4] == closures.DoorLock.UserStatus.Enabled


async def async_disable_user_code(
    server: Server,
    cluster: closures.DoorLock,
    entity: LockEntity,
    controller: Controller,
) -> None:
    """Test disable lock code functionality from client."""
    with patch(
        "zigpy.zcl.Cluster.request", return_value=mock_coro([zcl_f.Status.SUCCESS])
    ):
        await controller.locks.disable_user_lock_code(entity, 3)
        await server.block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == SET_USER_STATUS
        assert cluster.request.call_args[0][3] == 2  # user slot 3 => internal slot 2
        assert cluster.request.call_args[0][4] == closures.DoorLock.UserStatus.Disabled
