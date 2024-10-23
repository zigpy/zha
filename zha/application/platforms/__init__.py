"""Platform module for Zigbee Home Automation."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
from contextlib import suppress
from functools import cached_property
import logging
from typing import TYPE_CHECKING, Any, final

from zigpy.quirks.v2 import EntityMetadata, EntityType

from zha.application import Platform
from zha.application.platforms.model import (
    BaseEntityInfo,
    BaseIdentifiers,
    EntityCategory,
    EntityStateChangedEvent,
    GroupEntityIdentifiers,
    PlatformEntityIdentifiers,
)
from zha.const import STATE_CHANGED
from zha.debounce import Debouncer
from zha.event import EventBase
from zha.mixins import LogMixin

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY: float = 0.5


class BaseEntity(LogMixin, EventBase):
    """Base class for entities."""

    PLATFORM: Platform = Platform.UNKNOWN

    _attr_fallback_name: str | None
    _attr_translation_key: str | None
    _attr_entity_category: EntityCategory | None
    _attr_entity_registry_enabled_default: bool = True
    _attr_device_class: str | None
    _attr_state_class: str | None
    _attr_enabled: bool = True

    def __init__(self, unique_id: str) -> None:
        """Initialize the platform entity."""
        super().__init__()

        self._unique_id: str = unique_id

        self.__previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []
        self._tracked_handles: list[asyncio.Handle] = []

    @property
    def enabled(self) -> bool:
        """Return the entity enabled state."""
        return self._attr_enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set the entity enabled state."""
        self._attr_enabled = value

    @property
    def fallback_name(self) -> str | None:
        """Return the entity fallback name for when a translation key is unavailable."""
        if hasattr(self, "_attr_fallback_name"):
            return self._attr_fallback_name
        return None

    @property
    def icon(self) -> str | None:
        """Return the entity icon."""
        return None

    @property
    def translation_key(self) -> str | None:
        """Return the translation key."""
        if hasattr(self, "_attr_translation_key"):
            return self._attr_translation_key
        return None

    @property
    def entity_category(self) -> EntityCategory | None:
        """Return the entity category."""
        if hasattr(self, "_attr_entity_category"):
            return self._attr_entity_category
        return None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return the entity category."""
        return self._attr_entity_registry_enabled_default

    @property
    def device_class(self) -> str | None:
        """Return the device class."""
        if hasattr(self, "_attr_device_class"):
            return self._attr_device_class
        return None

    @property
    def state_class(self) -> str | None:
        """Return the state class."""
        if hasattr(self, "_attr_state_class"):
            return self._attr_state_class
        return None

    @final
    @property
    def unique_id(self) -> str:
        """Return the unique id."""
        return self._unique_id

    @cached_property
    def identifiers(self) -> BaseIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return BaseIdentifiers(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
        )

    @cached_property
    def info_object(self) -> BaseEntityInfo:
        """Return a representation of the platform entity."""

        return BaseEntityInfo(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
            class_name=self.__class__.__name__,
            fallback_name=self.fallback_name,
            translation_key=self.translation_key,
            device_class=self.device_class,
            state_class=self.state_class,
            entity_category=self.entity_category,
            entity_registry_enabled_default=self.entity_registry_enabled_default,
            enabled=self.enabled,
            # Set by platform entities
            cluster_handlers=[],
            device_ieee=None,
            endpoint_id=None,
            available=None,
            # Set by group entities
            group_id=None,
            state=self.state,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Return the arguments to use in the command."""
        return {
            "class_name": self.__class__.__name__,
        }

    @cached_property
    def extra_state_attribute_names(self) -> set[str] | None:
        """Return entity specific state attribute names.

        Implemented by platform classes. Convention for attribute names
        is lowercase snake_case.
        """
        if hasattr(self, "_attr_extra_state_attribute_names"):
            return self._attr_extra_state_attribute_names
        return None

    def enable(self) -> None:
        """Enable the entity."""
        self.enabled = True

    def disable(self) -> None:
        """Disable the entity."""
        self.enabled = False

    async def on_remove(self) -> None:
        """Cancel tasks and timers this entity owns."""
        for handle in self._tracked_handles:
            self.debug("Cancelling handle: %s", handle)
            handle.cancel()

        tasks = [t for t in self._tracked_tasks if not (t.done() or t.cancelled())]
        for task in tasks:
            self.debug("Cancelling task: %s", task)
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    def maybe_emit_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        state = self.state
        if self.__previous_state != state:
            self.emit(
                STATE_CHANGED,
                EntityStateChangedEvent(state=self.state, **self.identifiers.__dict__),
            )
            self.__previous_state = state

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a message."""
        msg = f"%s: {msg}"
        args = (self._unique_id,) + args
        _LOGGER.log(level, msg, *args, **kwargs)


class PlatformEntity(BaseEntity):
    """Class that represents an entity for a device platform."""

    # suffix to add to the unique_id of the entity. Used for multi
    # entities using the same cluster handler/cluster id for the entity.
    _unique_id_suffix: str | None = None

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        entity_metadata: EntityMetadata | None = None,
        **kwargs: Any,
    ):
        """Initialize the platform entity."""
        if entity_metadata is not None:
            self._init_from_quirks_metadata(entity_metadata)

        if self._unique_id_suffix:
            unique_id += f"-{self._unique_id_suffix}"

        # XXX: The ordering here matters: `_init_from_quirks_metadata` affects how
        # the `unique_id` is computed!
        super().__init__(unique_id=unique_id, **kwargs)

        self._cluster_handlers: list[ClusterHandler] = cluster_handlers
        self.cluster_handlers: dict[str, ClusterHandler] = {}
        for cluster_handler in cluster_handlers:
            self.cluster_handlers[cluster_handler.name] = cluster_handler
        self._device: Device = device
        self._endpoint = endpoint
        # we double create these in discovery tests because we reissue the create calls to count and prove them out
        if (self.PLATFORM, self.unique_id) not in self._device.platform_entities:
            self._device.platform_entities[(self.PLATFORM, self.unique_id)] = self
        else:
            _LOGGER.debug(
                "Not registering entity %r, unique id %r already exists: %r",
                self,
                (self.PLATFORM, self.unique_id),
                self._device.platform_entities[(self.PLATFORM, self.unique_id)],
            )

    @classmethod
    def create_platform_entity(
        cls: type[PlatformEntity],
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> PlatformEntity | None:
        """Entity Factory.

        Return a platform entity if it is a supported configuration, otherwise return None
        """
        return cls(unique_id, cluster_handlers, endpoint, device, **kwargs)

    def _init_from_quirks_metadata(self, entity_metadata: EntityMetadata) -> None:
        """Init this entity from the quirks metadata."""
        if entity_metadata.initially_disabled:
            self._attr_entity_registry_enabled_default = False

        has_attribute_name = hasattr(entity_metadata, "attribute_name")
        has_command_name = hasattr(entity_metadata, "command_name")
        has_fallback_name = hasattr(entity_metadata, "fallback_name")

        if has_fallback_name:
            self._attr_fallback_name = entity_metadata.fallback_name

        if entity_metadata.translation_key:
            self._attr_translation_key = entity_metadata.translation_key
        elif has_attribute_name:
            self._attr_translation_key = entity_metadata.attribute_name
        elif has_command_name:
            self._attr_translation_key = entity_metadata.command_name

        if has_attribute_name:
            self._unique_id_suffix = entity_metadata.attribute_name
        elif has_command_name:
            self._unique_id_suffix = entity_metadata.command_name

        if entity_metadata.entity_type is EntityType.CONFIG:
            self._attr_entity_category = EntityCategory.CONFIG
        elif entity_metadata.entity_type is EntityType.DIAGNOSTIC:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        else:
            self._attr_entity_category = None

    @cached_property
    def identifiers(self) -> PlatformEntityIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return PlatformEntityIdentifiers(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
            device_ieee=self.device.ieee,
            endpoint_id=self.endpoint.id,
        )

    @cached_property
    def info_object(self) -> BaseEntityInfo:
        """Return a representation of the platform entity."""
        return super().info_object.model_copy(
            update={
                "cluster_handlers": [ch.info_object for ch in self._cluster_handlers],
                "device_ieee": self._device.ieee,
                "endpoint_id": self._endpoint.id,
                "available": self.available,
            }
        )

    @property
    def device(self) -> Device:
        """Return the device."""
        return self._device

    @property
    def endpoint(self) -> Endpoint:
        """Return the endpoint."""
        return self._endpoint

    @property
    def should_poll(self) -> bool:
        """Return True if we need to poll for state changes."""
        return False

    @property
    def available(self) -> bool:
        """Return true if the device this entity belongs to is available."""
        return self.device.available

    @property
    def state(self) -> dict[str, Any]:
        """Return the arguments to use in the command."""
        state = super().state
        state["available"] = self.available
        return state

    def maybe_emit_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        from zha.application.gateway import WebSocketGateway

        super().maybe_emit_state_changed_event()
        if isinstance(self.device.gateway, WebSocketGateway):
            self.device.gateway.emit(
                STATE_CHANGED,
                EntityStateChangedEvent(state=self.state, **self.identifiers.__dict__),
            )

    async def async_update(self) -> None:
        """Retrieve latest state."""
        self.debug("polling current state")
        tasks = [
            cluster_handler.async_update()
            for cluster_handler in self.cluster_handlers.values()
            if hasattr(cluster_handler, "async_update")
        ]
        if tasks:
            await asyncio.gather(*tasks)
            self.maybe_emit_state_changed_event()


class GroupEntity(BaseEntity):
    """A base class for group entities."""

    def __init__(
        self,
        group: Group,
        update_group_from_member_delay: float = DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY,
    ) -> None:
        """Initialize a group."""
        super().__init__(unique_id=f"{self.PLATFORM}_zha_group_0x{group.group_id:04x}")
        self._attr_fallback_name: str = group.name
        self._group: Group = group
        self._change_listener_debouncer = Debouncer(
            group.gateway,
            _LOGGER,
            cooldown=update_group_from_member_delay,
            immediate=False,
            function=self.update,
        )
        self._group.register_group_entity(self)

    @cached_property
    def identifiers(self) -> GroupEntityIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return GroupEntityIdentifiers(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
            group_id=self.group_id,
        )

    @cached_property
    def info_object(self) -> BaseEntityInfo:
        """Return a representation of the group."""
        return super().info_object.model_copy(update={"group_id": self.group_id})

    @property
    def state(self) -> dict[str, Any]:
        """Return the arguments to use in the command."""
        state = super().state
        state["available"] = self.available
        return state

    @property
    def available(self) -> bool:
        """Return true if all member entities are available."""
        return any(
            platform_entity.available
            for platform_entity in self._group.get_platform_entities(self.PLATFORM)
        )

    @property
    def group_id(self) -> int:
        """Return the group id."""
        return self._group.group_id

    @property
    def group(self) -> Group:
        """Return the group."""
        return self._group

    def maybe_emit_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        from zha.application.gateway import WebSocketGateway

        super().maybe_emit_state_changed_event()
        if isinstance(self.group.gateway, WebSocketGateway):
            self.group.gateway.emit(
                STATE_CHANGED,
                EntityStateChangedEvent(state=self.state, **self.identifiers.__dict__),
            )

    def debounced_update(self, _: Any | None = None) -> None:
        """Debounce updating group entity from member entity updates."""
        # Delay to ensure that we get updates from all members before updating the group entity
        assert self._change_listener_debouncer
        self.group.gateway.create_task(self._change_listener_debouncer.async_call())

    async def on_remove(self) -> None:
        """Cancel tasks this entity owns."""
        await super().on_remove()
        if self._change_listener_debouncer:
            self._change_listener_debouncer.async_cancel()

    @abstractmethod
    def update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""

    async def async_update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""
        self.update()
