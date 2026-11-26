"""Test zha lock."""

from unittest.mock import patch

import pytest
import zigpy.profiles.zha
from zigpy.zcl.clusters import closures, general
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.lock.const import STATE_LOCKED, STATE_UNLOCKED
from zha.exceptions import ZHAException

LOCK_DOOR = 0
UNLOCK_DOOR = 1
SET_PIN_CODE = 5
CLEAR_PIN_CODE = 7
SET_USER_STATUS = 9


ZIGPY_LOCK = {
    1: {
        SIG_EP_INPUT: [closures.DoorLock.cluster_id, general.Basic.cluster_id],
        SIG_EP_OUTPUT: [],
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.DOOR_LOCK,
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
    }
}


async def test_lock(zha_gateway: Gateway) -> None:
    """Test zha lock platform."""

    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_LOCK)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints[1].door_lock
    entity = get_entity(zha_device, platform=Platform.LOCK)

    assert entity.state.is_locked is False

    # set state to locked
    await send_attributes_report(
        zha_gateway, cluster, {closures.DoorLock.AttributeDefs.lock_state: 1}
    )
    assert entity.state.is_locked is True

    # reports of other door lock attributes leave the state alone
    await send_attributes_report(
        zha_gateway, cluster, {closures.DoorLock.AttributeDefs.lock_type: 2}
    )
    assert entity.state.is_locked is True

    # set state to unlocked
    await send_attributes_report(
        zha_gateway, cluster, {closures.DoorLock.AttributeDefs.lock_state: 2}
    )
    assert entity.state.is_locked is False

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
    assert entity.state.is_locked is False
    cluster.PLUGGED_ATTR_READS = {"lock_state": 1}
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.call_count == 1
    assert entity.state.is_locked is True


async def async_lock(
    zha_gateway: Gateway,
    cluster: closures.DoorLock,
    entity: PlatformEntity,
) -> None:
    """Test lock functionality from client."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_lock()
        await zha_gateway.async_block_till_done()
        assert entity.state.is_locked is True
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == LOCK_DOOR
        cluster.request.reset_mock()

    # test unlock failure
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.FAILURE]):
        with pytest.raises(ZHAException):
            await entity.async_unlock()
        await zha_gateway.async_block_till_done()
        assert entity.state.is_locked is True
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
        assert entity.state.is_locked is False
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == UNLOCK_DOOR
        cluster.request.reset_mock()

    # test lock failure
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.FAILURE]):
        with pytest.raises(ZHAException):
            await entity.async_lock()
        await zha_gateway.async_block_till_done()
        assert entity.state.is_locked is False
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


async def test_lock_state_restoration(zha_gateway: Gateway) -> None:
    """Test the lock state restoration."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_LOCK)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(zha_device, platform=Platform.LOCK)

    assert entity.state.is_locked is False

    entity.restore_external_state_attributes(state=STATE_LOCKED)
    assert entity.state.is_locked is True

    entity.restore_external_state_attributes(state=STATE_UNLOCKED)
    assert entity.state.is_locked is False


_LOCK_RESPONSES = closures.DoorLock.ClientCommandDefs


@pytest.mark.parametrize(
    ("method", "args", "response"),
    [
        ("async_lock", (), _LOCK_RESPONSES.lock_door_response),
        ("async_unlock", (), _LOCK_RESPONSES.unlock_door_response),
        (
            "async_set_lock_user_code",
            (3, "13246579"),
            _LOCK_RESPONSES.set_pin_code_response,
        ),
        ("async_clear_lock_user_code", (3,), _LOCK_RESPONSES.clear_pin_code_response),
        (
            "async_enable_lock_user_code",
            (3,),
            _LOCK_RESPONSES.set_user_status_response,
        ),
        (
            "async_disable_lock_user_code",
            (3,),
            _LOCK_RESPONSES.set_user_status_response,
        ),
    ],
)
async def test_lock_command_failure_raises(
    zha_gateway: Gateway,
    method: str,
    args: tuple,
    response: zcl_f.ZCLCommandDef,
) -> None:
    """A command the lock rejects raises instead of passing as a success."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_LOCK)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)

    # Start from the state a lock or unlock would change
    start = STATE_UNLOCKED if method == "async_lock" else STATE_LOCKED
    entity.restore_external_state_attributes(state=start)
    was_locked = entity.state.is_locked

    # The lock's own response with a failure status
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=response.schema(status=zcl_f.Status.FAILURE),
        ),
        pytest.raises(ZHAException),
    ):
        await getattr(entity, method)(*args)

    # A Default Response with an error status, e.g. when a PIN is required
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=zcl_f.DefaultResponse(
                command_id=response.id, status=zcl_f.Status.NOT_AUTHORIZED
            ),
        ),
        pytest.raises(ZHAException),
    ):
        await getattr(entity, method)(*args)

    # A rejected command leaves the state alone
    assert entity.state.is_locked is was_locked

    # Both forms of success pass
    for success in (
        response.schema(status=zcl_f.Status.SUCCESS),
        zcl_f.DefaultResponse(command_id=response.id, status=zcl_f.Status.SUCCESS),
    ):
        entity.restore_external_state_attributes(state=start)
        with patch("zigpy.zcl.Cluster.request", return_value=success):
            await getattr(entity, method)(*args)
        if method == "async_lock":
            assert entity.state.is_locked is True
        elif method == "async_unlock":
            assert entity.state.is_locked is False
        else:
            assert entity.state.is_locked is was_locked


async def test_set_user_code_failure_reason(zha_gateway: Gateway) -> None:
    """The lock's set PIN code status values are named in the error."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_LOCK)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)

    # The set PIN code response status is a DoorLock value, not a ZCL status
    schema = _LOCK_RESPONSES.set_pin_code_response.schema
    for frame, reason in (
        (b"\x02", "memory full"),
        (b"\x03", "duplicate code"),
        (b"\x7f", "status 0x7F"),
    ):
        response, _ = schema.deserialize(frame)
        with (
            patch("zigpy.zcl.Cluster.request", return_value=response),
            pytest.raises(ZHAException, match=f"slot 3: {reason}$"),
        ):
            await entity.async_set_lock_user_code(3, "13246579")
