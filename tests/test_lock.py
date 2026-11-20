"""Test zha lock."""

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
import zigpy.exceptions
import zigpy.profiles.zha
from zigpy.zcl import AttributeReportedEvent, AttributeWrittenEvent, ClusterType
from zigpy.zcl.clusters import closures, general
from zigpy.zcl.clusters.closures import DoorLock, LockState
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    rejoin_zha_device,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import ASSUMED_STATE_SAVE_DELAY, PlatformEntity
from zha.application.platforms.lock.const import STATE_LOCKED, STATE_UNLOCKED
from zha.zigbee.device import Device
from zha.zigbee.store import (
    ENTITY_ASSUMED_STATE_NAMESPACE,
    ENTITY_STATE_NAMESPACE,
    entity_state_key,
)

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
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.state.is_locked is True

    # set state to unlocked
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 2, 2: 3})
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


def _assumed_record(zha_device: Device, entity: PlatformEntity) -> Any:
    """Return the assumed state record of a lock, or `None`."""
    namespace = zha_device.device.store.namespace(ENTITY_ASSUMED_STATE_NAMESPACE)
    return namespace.get(entity_state_key(Platform.LOCK, entity.unique_id))


async def _wait_for_save(zha_gateway: Gateway) -> None:
    """Wait until delayed saves of assumed values have run."""
    await asyncio.sleep(ASSUMED_STATE_SAVE_DELAY + 1)
    await zha_gateway.async_block_till_done()


async def _join_lock(zha_gateway: Gateway) -> tuple[Device, DoorLock, PlatformEntity]:
    """Join a lock that reported itself unlocked."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_LOCK)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints[1].door_lock
    await send_attributes_report(zha_gateway, cluster, {0: LockState.Unlocked})

    return zha_device, cluster, get_entity(zha_device, platform=Platform.LOCK)


async def _lock(entity: PlatformEntity) -> None:
    """Lock successfully."""
    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.SUCCESS]):
        await entity.async_lock()


async def test_lock_assumed_state_survives_restart(zha_gateway: Gateway) -> None:
    """A commanded lock state is kept until the lock reports it."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    assert entity.state.is_locked is False

    await _lock(entity)

    # Saving waits, in case the lock reports right away
    assert _assumed_record(zha_device, entity) is None
    await _wait_for_save(zha_gateway)

    record = _assumed_record(zha_device, entity)
    assert record["state"]["value"] == STATE_LOCKED
    assert datetime.fromisoformat(record["state"]["since"]) > (
        cluster._attr_cache.get_last_updated(DoorLock.AttributeDefs.lock_state)
    )

    # The cache still says unlocked, the assumed state is newer
    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)
    assert entity.state.is_locked is True

    # Home Assistant's copy is a fallback only
    entity.restore_external_state_attributes(state=STATE_UNLOCKED)
    assert entity.state.is_locked is True
    assert _assumed_record(zha_device, entity)["state"]["value"] == STATE_LOCKED


async def test_lock_assumed_state_saved_when_device_is_rebuilt(
    zha_gateway: Gateway,
) -> None:
    """Removing the entity saves an assumed state still waiting to be saved."""
    zha_device, _, entity = await _join_lock(zha_gateway)
    await _lock(entity)
    assert _assumed_record(zha_device, entity) is None

    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)
    assert entity.state.is_locked is True
    assert _assumed_record(zha_device, entity)["state"]["value"] == STATE_LOCKED


async def test_lock_confirmed_command_writes_nothing(zha_gateway: Gateway) -> None:
    """A command the lock confirms before the save delay leaves no store write."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    store = zha_device.device.store

    with patch.object(store, "_emit", wraps=store._emit) as emit:
        await _lock(entity)
        await send_attributes_report(zha_gateway, cluster, {0: LockState.Locked})
        await _wait_for_save(zha_gateway)

    assert entity.state.is_locked is True
    assert emit.call_count == 0


@pytest.mark.parametrize(
    ("reported", "is_locked"),
    [(LockState.Locked, True), (LockState.Unlocked, False)],
)
async def test_lock_assumed_state_dropped_on_report(
    zha_gateway: Gateway, reported: LockState, is_locked: bool
) -> None:
    """A report confirming or contradicting the assumed state replaces it."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    await _lock(entity)
    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is not None

    await send_attributes_report(zha_gateway, cluster, {0: reported})
    assert entity.state.is_locked is is_locked
    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is None

    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)
    assert entity.state.is_locked is is_locked

    # Without an assumed state, Home Assistant's restored state is used as before
    entity.restore_external_state_attributes(state=STATE_LOCKED)
    assert entity.state.is_locked is True


async def test_lock_restored_state_older_than_report_since_load(
    zha_gateway: Gateway,
) -> None:
    """A report after loading is newer than Home Assistant's restored state."""
    zha_device, cluster, _ = await _join_lock(zha_gateway)
    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)

    await send_attributes_report(zha_gateway, cluster, {0: LockState.Locked})
    entity.restore_external_state_attributes(state=STATE_UNLOCKED)
    assert entity.state.is_locked is True


async def test_lock_assumed_state_dropped_on_read(zha_gateway: Gateway) -> None:
    """Polling the lock state replaces the assumed state."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    await _lock(entity)
    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is not None

    cluster.PLUGGED_ATTR_READS = {"lock_state": LockState.Unlocked}
    update_attribute_cache(cluster)
    await entity.async_update()
    await _wait_for_save(zha_gateway)

    assert entity.state.is_locked is False
    assert _assumed_record(zha_device, entity) is None


async def test_lock_assumed_state_kept_on_failed_poll(zha_gateway: Gateway) -> None:
    """A failed poll leaves the assumed state shown and stored."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    await _lock(entity)

    with patch.object(
        cluster, "read_attributes", side_effect=zigpy.exceptions.DeliveryError("")
    ):
        await entity.async_update()

    await _wait_for_save(zha_gateway)
    assert entity.state.is_locked is True
    assert _assumed_record(zha_device, entity)["state"]["value"] == STATE_LOCKED


@pytest.mark.parametrize(
    ("status", "dropped"),
    [(zcl_f.Status.SUCCESS, True), (zcl_f.Status.READ_ONLY, False)],
)
async def test_lock_assumed_state_dropped_on_successful_write_only(
    zha_gateway: Gateway, status: zcl_f.Status, dropped: bool
) -> None:
    """A rejected write of the attribute does not replace the assumed state."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    await _lock(entity)

    cluster.emit(
        AttributeWrittenEvent.event_type,
        AttributeWrittenEvent(
            device_ieee=str(zha_device.ieee),
            endpoint_id=1,
            cluster_type=ClusterType.Server,
            cluster_id=cluster.cluster_id,
            attribute_name=DoorLock.AttributeDefs.lock_state.name,
            attribute_id=DoorLock.AttributeDefs.lock_state.id,
            manufacturer_code=None,
            value=LockState.Unlocked,
            status=status,
        ),
    )
    await _wait_for_save(zha_gateway)

    assert (_assumed_record(zha_device, entity) is None) is dropped


async def test_lock_assumed_state_ignores_manufacturer_attribute(
    zha_gateway: Gateway,
) -> None:
    """A manufacturer-specific attribute with the same ID does not drop the entry."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    await _lock(entity)

    cluster.emit(
        AttributeReportedEvent.event_type,
        AttributeReportedEvent(
            device_ieee=str(zha_device.ieee),
            endpoint_id=1,
            cluster_type=ClusterType.Server,
            cluster_id=cluster.cluster_id,
            attribute_name=None,
            attribute_id=DoorLock.AttributeDefs.lock_state.id,
            manufacturer_code=0x1234,
            raw_value=2,
            value=2,
        ),
    )
    await _wait_for_save(zha_gateway)

    assert _assumed_record(zha_device, entity)["state"]["value"] == STATE_LOCKED


async def test_lock_assumed_state_yields_to_newer_cache(zha_gateway: Gateway) -> None:
    """At load, an attribute cache value newer than the assumed state wins."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    zigpy_device = zha_device.device
    await _lock(entity)

    # The lock reports while no entity listens, e.g. while the device is rebuilt
    await zha_device.on_remove()
    assert _assumed_record(zha_device, entity) is not None
    cluster._attr_cache.set_value(DoorLock.AttributeDefs.lock_state, LockState.Unlocked)
    del zha_gateway._devices[zigpy_device.ieee]
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)

    assert entity.state.is_locked is False

    # The stale entry is removed by the save scheduled at load
    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is None


async def test_lock_stale_assumed_state_removed_after_slow_initialization(
    zha_gateway: Gateway,
) -> None:
    """The cleanup save is not lost when the device adds the entity after its delay."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    zigpy_device = zha_device.device
    await _lock(entity)

    await zha_device.on_remove()
    assert _assumed_record(zha_device, entity) is not None
    cluster._attr_cache.set_value(DoorLock.AttributeDefs.lock_state, LockState.Unlocked)
    del zha_gateway._devices[zigpy_device.ieee]

    # Initialization reads take longer than the save delay, so the save scheduled at
    # load runs before the device has added the entity
    add_pending_entities = Device._add_pending_entities

    async def slow_add_pending_entities(self: Device, **kwargs: Any) -> None:
        await asyncio.sleep(0.1)
        await add_pending_entities(self, **kwargs)

    with (
        patch("zha.application.platforms.ASSUMED_STATE_SAVE_DELAY", 0.01),
        patch.object(Device, "_add_pending_entities", slow_add_pending_entities),
    ):
        zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(zha_device, platform=Platform.LOCK)
    assert entity.state.is_locked is False

    await zha_gateway.async_block_till_done()
    assert _assumed_record(zha_device, entity) is None


async def test_lock_poll_uses_the_cached_value(zha_gateway: Gateway) -> None:
    """Polling shows the value as cached, after a quirk transformed it."""
    _, cluster, entity = await _join_lock(zha_gateway)
    update_attribute = cluster._update_attribute

    # A quirk that inverts the lock state the lock sends
    def invert(attrid: Any, value: Any) -> None:
        if attrid == DoorLock.AttributeDefs.lock_state.id:
            value = (
                LockState.Locked if value == LockState.Unlocked else LockState.Unlocked
            )

        update_attribute(attrid, value)

    cluster.PLUGGED_ATTR_READS = {"lock_state": LockState.Unlocked}

    with patch.object(cluster, "_update_attribute", new=invert):
        await entity.async_update()

    assert cluster.get(DoorLock.AttributeDefs.lock_state.name) == LockState.Locked
    assert entity.state.is_locked is True


async def test_lock_assumed_state_not_kept_after_report_during_command(
    zha_gateway: Gateway,
) -> None:
    """A report that arrives while the command is in flight is newer than the command."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)

    async def lock_and_report(*args: Any, **kwargs: Any) -> list[zcl_f.Status]:
        cluster.update_attribute(DoorLock.AttributeDefs.lock_state.id, LockState.Locked)
        return [zcl_f.Status.SUCCESS]

    with patch("zigpy.zcl.Cluster.request", side_effect=lock_and_report):
        await entity.async_lock()

    await _wait_for_save(zha_gateway)
    assert entity.state.is_locked is True
    assert _assumed_record(zha_device, entity) is None


async def test_lock_assumed_state_not_kept_on_failure(zha_gateway: Gateway) -> None:
    """A failed command leaves nothing behind."""
    zha_device, _, entity = await _join_lock(zha_gateway)

    with patch("zigpy.zcl.Cluster.request", return_value=[zcl_f.Status.FAILURE]):
        await entity.async_lock()

    await _wait_for_save(zha_gateway)
    assert len(zha_device.device.store.namespace(ENTITY_ASSUMED_STATE_NAMESPACE)) == 0
    assert len(zha_device.device.store.namespace(ENTITY_STATE_NAMESPACE)) == 0


async def test_lock_assumed_state_only_saved_by_added_entity(
    zha_gateway: Gateway,
) -> None:
    """Entities the device has not added, or has removed, never write the record."""
    zha_device, _, old_entity = await _join_lock(zha_gateway)
    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)

    # The removed entity finishes a command after the device was rebuilt
    await _lock(old_entity)
    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is None

    # A copy created by discovery, as when the device is initialized again
    copy = type(entity)(
        endpoint=entity.endpoint, device=zha_device, cluster=entity.cluster
    )
    copy.on_add()
    await _lock(copy)
    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is None
    await copy.on_remove()
    assert _assumed_record(zha_device, entity) is None


async def test_lock_assumed_state_follows_unique_id_migration(
    zha_gateway: Gateway,
) -> None:
    """An assumed state stored under a previous unique ID moves to the current one."""
    zha_device, _, entity = await _join_lock(zha_gateway)
    namespace = zha_device.device.store.namespace(ENTITY_ASSUMED_STATE_NAMESPACE)
    old_key = entity_state_key(Platform.LOCK, "old-unique-id")
    namespace[old_key] = {
        "state": {"value": STATE_LOCKED, "since": "2100-01-01T00:00:00+00:00"}
    }

    with patch.object(
        type(entity),
        "migrate_unique_ids",
        new_callable=PropertyMock,
        return_value=frozenset({"old-unique-id"}),
    ):
        zha_device = await rejoin_zha_device(zha_gateway, zha_device)

    entity = get_entity(zha_device, platform=Platform.LOCK)
    assert entity.state.is_locked is True
    assert old_key not in namespace
    assert _assumed_record(zha_device, entity)["state"]["value"] == STATE_LOCKED


@pytest.mark.parametrize(
    "record",
    [
        "not a record",
        {"state": "locked"},
        {"state": {"value": "jammed", "since": "2100-01-01T00:00:00+00:00"}},
        {"state": {"value": "locked", "since": "2100-01-01T00:00:00"}},
        {"state": {"value": "locked", "since": "yesterday"}},
        {"state": {"since": "2100-01-01T00:00:00+00:00"}},
    ],
)
async def test_lock_invalid_assumed_state_ignored(
    zha_gateway: Gateway, record: Any
) -> None:
    """An invalid assumed state is not restored, is removed, and HA's is used."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_LOCK)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)
    namespace = zha_device.device.store.namespace(ENTITY_ASSUMED_STATE_NAMESPACE)
    namespace[entity_state_key(Platform.LOCK, entity.unique_id)] = record

    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)
    assert entity.state.is_locked is False

    entity.restore_external_state_attributes(state=STATE_LOCKED)
    assert entity.state.is_locked is True

    await _wait_for_save(zha_gateway)
    assert _assumed_record(zha_device, entity) is None


async def test_lock_assumed_state_keeps_unknown_fields(zha_gateway: Gateway) -> None:
    """Fields of the record this version does not know survive a save."""
    zha_device, cluster, entity = await _join_lock(zha_gateway)
    namespace = zha_device.device.store.namespace(ENTITY_ASSUMED_STATE_NAMESPACE)
    key = entity_state_key(Platform.LOCK, entity.unique_id)
    future = {"future": {"value": 1, "since": "2100-01-01T00:00:00+00:00"}}
    namespace[key] = future

    zha_device = await rejoin_zha_device(zha_gateway, zha_device)
    entity = get_entity(zha_device, platform=Platform.LOCK)

    await _lock(entity)
    await _wait_for_save(zha_gateway)
    assert set(namespace[key]) == {"future", "state"}

    await send_attributes_report(zha_gateway, cluster, {0: LockState.Locked})
    await _wait_for_save(zha_gateway)
    assert namespace[key] == future
