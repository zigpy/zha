"""Locks on Zigbee Home Automation networks."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Literal

from zigpy.zcl.clusters.closures import DoorLock as DoorLockCluster
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.lock.const import (
    STATE_LOCKED,
    STATE_UNLOCKED,
    VALUE_TO_STATE,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_DOORLOCK,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.LOCK)


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_DOORLOCK)
class DoorLock(PlatformEntity):
    """Representation of a ZHA lock."""

    PLATFORM = Platform.LOCK
    _attr_translation_key: str = "door_lock"

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the lock."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._doorlock_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_DOORLOCK
        )
        self._state: str | None = VALUE_TO_STATE.get(
            self._doorlock_cluster_handler.cluster.get("lock_state"), None
        )
        self._doorlock_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the lock."""
        response = super().state
        response["is_locked"] = self.is_locked
        return response

    @property
    def is_locked(self) -> bool:
        """Return true if entity is locked."""
        if self._state is None:
            return False
        return self._state == STATE_LOCKED

    async def async_lock(self) -> None:
        """Lock the lock."""
        result = await self._doorlock_cluster_handler.lock_door()
        if result[0] is not Status.SUCCESS:
            self.error("Error with lock_door: %s", result)
            return

        self._state = STATE_LOCKED
        self.maybe_emit_state_changed_event()

    async def async_unlock(self) -> None:
        """Unlock the lock."""
        result = await self._doorlock_cluster_handler.unlock_door()
        if result[0] is not Status.SUCCESS:
            self.error("Error with unlock_door: %s", result)
            return

        self._state = STATE_UNLOCKED
        self.maybe_emit_state_changed_event()

    async def async_set_lock_user_code(self, code_slot: int, user_code: str) -> None:
        """Set the user_code to index X on the lock."""
        if self._doorlock_cluster_handler:
            await self._doorlock_cluster_handler.async_set_user_code(
                code_slot, user_code
            )
            self.debug("User code at slot %s set", code_slot)

    async def async_enable_lock_user_code(self, code_slot: int) -> None:
        """Enable user_code at index X on the lock."""
        if self._doorlock_cluster_handler:
            await self._doorlock_cluster_handler.async_enable_user_code(code_slot)
            self.debug("User code at slot %s enabled", code_slot)

    async def async_disable_lock_user_code(self, code_slot: int) -> None:
        """Disable user_code at index X on the lock."""
        if self._doorlock_cluster_handler:
            await self._doorlock_cluster_handler.async_disable_user_code(code_slot)
            self.debug("User code at slot %s disabled", code_slot)

    async def async_clear_lock_user_code(self, code_slot: int) -> None:
        """Clear the user_code at index X on the lock."""
        if self._doorlock_cluster_handler:
            await self._doorlock_cluster_handler.async_clear_user_code(code_slot)
            self.debug("User code at slot %s cleared", code_slot)

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle state update from cluster handler."""
        if event.attribute_id != DoorLockCluster.AttributeDefs.lock_state.id:
            return
        self._state = VALUE_TO_STATE.get(event.attribute_value, self._state)
        self.maybe_emit_state_changed_event()

    def restore_external_state_attributes(
        self,
        *,
        state: Literal["locked", "unlocked"] | None,
    ) -> None:
        """Restore extra state attributes that are stored outside of the ZCL cache."""
        self._state = state
