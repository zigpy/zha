"""Entity for Zigbee Home Automation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import functools
import logging
from typing import TYPE_CHECKING, Any, Self

from homeassistant.const import ATTR_NAME, EntityCategory
from homeassistant.core import CALLBACK_TYPE, Event, callback
from homeassistant.helpers import entity
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import CONNECTION_ZIGBEE, DeviceInfo
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity
from zigpy.quirks.v2 import EntityMetadata, EntityType

from .core.const import (
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    DOMAIN,
    SIGNAL_GROUP_ENTITY_REMOVED,
    SIGNAL_GROUP_MEMBERSHIP_CHANGE,
    SIGNAL_REMOVE,
)
from .core.helpers import LogMixin, get_zha_gateway

if TYPE_CHECKING:
    from .core.cluster_handlers import ClusterHandler
    from .core.device import ZHADevice

_LOGGER = logging.getLogger(__name__)

ENTITY_SUFFIX = "entity_suffix"
DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY = 0.5


class BaseZhaEntity(LogMixin, entity.Entity):
    """A base class for ZHA entities."""

    _unique_id_suffix: str | None = None
    """suffix to add to the unique_id of the entity. Used for multi
       entities using the same cluster handler/cluster id for the entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, unique_id: str, zha_device: ZHADevice, **kwargs: Any) -> None:
        """Init ZHA entity."""
        self._unique_id: str = unique_id
        if self._unique_id_suffix:
            self._unique_id += f"-{self._unique_id_suffix}"
        self._state: Any = None
        self._extra_state_attributes: dict[str, Any] = {}
        self._zha_device = zha_device
        self._unsubs: list[Callable[[], None]] = []

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def zha_device(self) -> ZHADevice:
        """Return the ZHA device this entity is attached to."""
        return self._zha_device

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific state attributes."""
        return self._extra_state_attributes

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        zha_device_info = self._zha_device.device_info
        ieee = zha_device_info["ieee"]

        zha_gateway = get_zha_gateway(self.hass)

        return DeviceInfo(
            connections={(CONNECTION_ZIGBEE, ieee)},
            identifiers={(DOMAIN, ieee)},
            manufacturer=zha_device_info[ATTR_MANUFACTURER],
            model=zha_device_info[ATTR_MODEL],
            name=zha_device_info[ATTR_NAME],
            via_device=(DOMAIN, zha_gateway.state.node_info.ieee),
        )

    @callback
    def async_state_changed(self) -> None:
        """Entity state changed."""
        self.async_write_ha_state()

    @callback
    def async_update_state_attribute(self, key: str, value: Any) -> None:
        """Update a single device state attribute."""
        self._extra_state_attributes.update({key: value})
        self.async_write_ha_state()

    @callback
    def async_set_state(self, attr_id: int, attr_name: str, value: Any) -> None:
        """Set the entity state."""

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect entity object when removed."""
        for unsub in self._unsubs[:]:
            unsub()
            self._unsubs.remove(unsub)

    @callback
    def async_accept_signal(
        self,
        cluster_handler: ClusterHandler | None,
        signal: str,
        func: Callable[..., Any],
        signal_override=False,
    ):
        """Accept a signal from a cluster handler."""
        unsub = None
        if signal_override:
            unsub = async_dispatcher_connect(self.hass, signal, func)
        else:
            assert cluster_handler
            unsub = async_dispatcher_connect(
                self.hass, f"{cluster_handler.unique_id}_{signal}", func
            )
        self._unsubs.append(unsub)

    def log(self, level: int, msg: str, *args, **kwargs):
        """Log a message."""
        msg = f"%s: {msg}"
        args = (self.entity_id,) + args
        _LOGGER.log(level, msg, *args, **kwargs)


class ZhaEntity(BaseZhaEntity, RestoreEntity):
    """A base class for non group ZHA entities."""

    remove_future: asyncio.Future[Any]

    def __init__(
        self,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> None:
        """Init ZHA entity."""
        super().__init__(unique_id, zha_device, **kwargs)

        self.cluster_handlers: dict[str, ClusterHandler] = {}
        for cluster_handler in cluster_handlers:
            self.cluster_handlers[cluster_handler.name] = cluster_handler

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """
        return cls(unique_id, zha_device, cluster_handlers, **kwargs)

    def _init_from_quirks_metadata(self, entity_metadata: EntityMetadata) -> None:
        """Init this entity from the quirks metadata."""
        if entity_metadata.initially_disabled:
            self._attr_entity_registry_enabled_default = False

        if entity_metadata.translation_key:
            self._attr_translation_key = entity_metadata.translation_key

        if hasattr(entity_metadata.entity_metadata, "attribute_name"):
            if not entity_metadata.translation_key:
                self._attr_translation_key = (
                    entity_metadata.entity_metadata.attribute_name
                )
            self._unique_id_suffix = entity_metadata.entity_metadata.attribute_name
        elif hasattr(entity_metadata.entity_metadata, "command_name"):
            if not entity_metadata.translation_key:
                self._attr_translation_key = (
                    entity_metadata.entity_metadata.command_name
                )
            self._unique_id_suffix = entity_metadata.entity_metadata.command_name
        if entity_metadata.entity_type is EntityType.CONFIG:
            self._attr_entity_category = EntityCategory.CONFIG
        elif entity_metadata.entity_type is EntityType.DIAGNOSTIC:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self._zha_device.available

    async def async_added_to_hass(self) -> None:
        """Run when about to be added to hass."""
        self.remove_future = self.hass.loop.create_future()
        self.async_accept_signal(
            None,
            f"{SIGNAL_REMOVE}_{self.zha_device.ieee}",
            functools.partial(self.async_remove, force_remove=True),
            signal_override=True,
        )

        if last_state := await self.async_get_last_state():
            self.async_restore_last_state(last_state)

        self.async_accept_signal(
            None,
            f"{self.zha_device.available_signal}_entity",
            self.async_state_changed,
            signal_override=True,
        )
        self._zha_device.gateway.register_entity_reference(
            self._zha_device.ieee,
            self.entity_id,
            self._zha_device,
            self.cluster_handlers,
            self.device_info,
            self.remove_future,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect entity object when removed."""
        await super().async_will_remove_from_hass()
        self.zha_device.gateway.remove_entity_reference(self)
        self.remove_future.set_result(True)

    @callback
    def async_restore_last_state(self, last_state) -> None:
        """Restore previous state."""

    async def async_update(self) -> None:
        """Retrieve latest state."""
        tasks = [
            cluster_handler.async_update()
            for cluster_handler in self.cluster_handlers.values()
            if hasattr(cluster_handler, "async_update")
        ]
        if tasks:
            await asyncio.gather(*tasks)


class ZhaGroupEntity(BaseZhaEntity):
    """A base class for ZHA group entities."""

    # The group name is set in the initializer
    _attr_name: str

    def __init__(
        self,
        entity_ids: list[str],
        unique_id: str,
        group_id: int,
        zha_device: ZHADevice,
        **kwargs: Any,
    ) -> None:
        """Initialize a ZHA group."""
        super().__init__(unique_id, zha_device, **kwargs)
        self._available = False
        self._group = zha_device.gateway.groups.get(group_id)
        self._group_id: int = group_id
        self._entity_ids: list[str] = entity_ids
        self._async_unsub_state_changed: CALLBACK_TYPE | None = None
        self._handled_group_membership = False
        self._change_listener_debouncer: Debouncer | None = None
        self._update_group_from_child_delay = DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY

        self._attr_name = self._group.name

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self._available

    @classmethod
    def create_entity(
        cls,
        entity_ids: list[str],
        unique_id: str,
        group_id: int,
        zha_device: ZHADevice,
        **kwargs: Any,
    ) -> Self | None:
        """Group Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """
        return cls(entity_ids, unique_id, group_id, zha_device, **kwargs)

    async def _handle_group_membership_changed(self):
        """Handle group membership changed."""
        # Make sure we don't call remove twice as members are removed
        if self._handled_group_membership:
            return

        self._handled_group_membership = True
        await self.async_remove(force_remove=True)

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        await self.async_update()

        self.async_accept_signal(
            None,
            f"{SIGNAL_GROUP_MEMBERSHIP_CHANGE}_0x{self._group_id:04x}",
            self._handle_group_membership_changed,
            signal_override=True,
        )

        if self._change_listener_debouncer is None:
            self._change_listener_debouncer = Debouncer(
                self.hass,
                _LOGGER,
                cooldown=self._update_group_from_child_delay,
                immediate=False,
                function=functools.partial(self.async_update_ha_state, True),
            )
            self.async_on_remove(self._change_listener_debouncer.async_cancel)
        self._async_unsub_state_changed = async_track_state_change_event(
            self.hass, self._entity_ids, self.async_state_changed_listener
        )

        def send_removed_signal():
            async_dispatcher_send(
                self.hass, SIGNAL_GROUP_ENTITY_REMOVED, self._group_id
            )

        self.async_on_remove(send_removed_signal)

    @callback
    def async_state_changed_listener(self, event: Event[EventStateChangedData]) -> None:
        """Handle child updates."""
        # Delay to ensure that we get updates from all members before updating the group
        assert self._change_listener_debouncer
        self._change_listener_debouncer.async_schedule_call()

    async def async_will_remove_from_hass(self) -> None:
        """Handle removal from Home Assistant."""
        await super().async_will_remove_from_hass()
        if self._async_unsub_state_changed is not None:
            self._async_unsub_state_changed()
            self._async_unsub_state_changed = None

    async def async_update(self) -> None:
        """Update the state of the group entity."""
