"""Locks on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
import dataclasses
from typing import TYPE_CHECKING, Any, Literal, cast

from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.closures import (
    DoorLock as DoorLockCluster,
    LockState as ZclLockState,
)
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.helpers import safe_read
from zha.application.platforms import (
    AttrConfig,
    BaseEntityState,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    register_entity,
)
from zha.application.platforms.lock.const import (
    STATE_LOCKED,
    STATE_UNLOCKED,
    VALUE_TO_STATE,
)

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


@dataclasses.dataclass(frozen=True, kw_only=True)
class LockState(BaseEntityState):
    """State for lock entities."""

    is_locked: bool


class BaseLock(PlatformEntity, ABC):
    """Abstract base class for ZHA lock entities."""

    PLATFORM = Platform.LOCK

    @property
    def state(self) -> LockState:
        """Get the state of the lock."""
        return LockState(
            **super().state.__dict__,
            is_locked=self.is_locked,
        )

    @property
    @abstractmethod
    def is_locked(self) -> bool:
        """Return true if entity is locked."""

    @abstractmethod
    async def async_lock(self) -> None:
        """Lock the lock."""

    @abstractmethod
    async def async_unlock(self) -> None:
        """Unlock the lock."""


@register_entity(DoorLockCluster.cluster_id)
class DoorLock(BaseLock):
    """Representation of a ZHA lock."""

    _attr_translation_key: str = "door_lock"
    _attr_primary_weight = 5

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({DoorLockCluster.cluster_id}),
    )

    _server_cluster_config = {
        DoorLockCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                DoorLockCluster.AttributeDefs.lock_state: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the lock."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._state: str | None = VALUE_TO_STATE.get(
            self._cluster.get(DoorLockCluster.AttributeDefs.lock_state.name), None
        )

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type, self.handle_attribute_updated
                )
            )

    @property
    def is_locked(self) -> bool:
        """Return true if entity is locked."""
        if self._state is None:
            return False
        return self._state == STATE_LOCKED

    async def async_lock(self) -> None:
        """Lock the lock."""
        result = await self._cluster.lock_door()
        if result[0] is not Status.SUCCESS:
            self.error("Error with lock_door: %s", result)
            return

        self._state = STATE_LOCKED
        self.maybe_emit_state_changed_event()

    async def async_unlock(self) -> None:
        """Unlock the lock."""
        result = await self._cluster.unlock_door()
        if result[0] is not Status.SUCCESS:
            self.error("Error with unlock_door: %s", result)
            return

        self._state = STATE_UNLOCKED
        self.maybe_emit_state_changed_event()

    async def async_set_lock_user_code(self, code_slot: int, user_code: str) -> None:
        """Set the user_code to index X on the lock."""
        await self._cluster.set_pin_code(
            code_slot - 1,  # start code slots at 1, Zigbee internals use 0
            DoorLockCluster.UserStatus.Enabled,
            DoorLockCluster.UserType.Unrestricted,
            user_code,
        )
        self.debug("User code at slot %s set", code_slot)

    async def async_enable_lock_user_code(self, code_slot: int) -> None:
        """Enable user_code at index X on the lock."""
        await self._cluster.set_user_status(
            code_slot - 1, DoorLockCluster.UserStatus.Enabled
        )
        self.debug("User code at slot %s enabled", code_slot)

    async def async_disable_lock_user_code(self, code_slot: int) -> None:
        """Disable user_code at index X on the lock."""
        await self._cluster.set_user_status(
            code_slot - 1, DoorLockCluster.UserStatus.Disabled
        )
        self.debug("User code at slot %s disabled", code_slot)

    async def async_clear_lock_user_code(self, code_slot: int) -> None:
        """Clear the user_code at index X on the lock."""
        await self._cluster.clear_pin_code(code_slot - 1)
        self.debug("User code at slot %s cleared", code_slot)

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle state update from the door-lock cluster."""
        if event.attribute_id != DoorLockCluster.AttributeDefs.lock_state.id:
            return

        value = cast(ZclLockState, event.value)
        self._state = VALUE_TO_STATE.get(value, self._state)
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Poll lock_state from the cluster."""
        await safe_read(
            self._cluster,
            [DoorLockCluster.AttributeDefs.lock_state.name],
            allow_cache=False,
            only_cache=False,
        )
        value = self._cluster.get(DoorLockCluster.AttributeDefs.lock_state.name)
        if value is not None:
            self._state = VALUE_TO_STATE.get(value, self._state)
            self.maybe_emit_state_changed_event()

    def restore_external_state_attributes(
        self,
        *,
        state: Literal["locked", "unlocked"] | None,
    ) -> None:
        """Restore extra state attributes that are stored outside of the ZCL cache."""
        self._state = state
