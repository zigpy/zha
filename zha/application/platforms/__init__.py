"""Platform module for Zigbee Home Automation."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
from collections.abc import Callable
from contextlib import suppress
import dataclasses
from enum import StrEnum
from functools import cached_property
import logging
from typing import TYPE_CHECKING, Any, Final, Optional, final

from zigpy.quirks.v2 import EntityMetadata, EntityType
from zigpy.types.named import EUI64

from zha.application import Platform
from zha.application.const import UniqueIdMigration
from zha.const import STATE_CHANGED
from zha.debounce import Debouncer
from zha.event import EventBase
from zha.mixins import LogMixin
from zha.zigbee.cluster_handlers import ClusterHandlerInfo

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY: float = 0.5


class EntityCategory(StrEnum):
    """Category of an entity."""

    # Config: An entity which allows changing the configuration of a device.
    CONFIG = "config"

    # Diagnostic: An entity exposing some configuration parameter,
    # or diagnostics of a device.
    DIAGNOSTIC = "diagnostic"


@dataclasses.dataclass(frozen=True, kw_only=True)
class BaseEntityInfo:
    """Information about a base entity."""

    fallback_name: str
    unique_id: str
    migrate_unique_ids: frozenset[str]
    platform: str
    class_name: str
    translation_key: str | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    entity_registry_enabled_default: bool
    enabled: bool = True
    primary: bool

    # For platform entities
    cluster_handlers: list[ClusterHandlerInfo]
    device_ieee: EUI64 | None
    endpoint_id: int | None
    available: bool | None

    # For group entities
    group_id: int | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class BaseIdentifiers:
    """Identifiers for the base entity."""

    unique_id: str
    platform: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlatformEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the platform entity."""

    device_ieee: EUI64
    endpoint_id: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class GroupEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the group entity."""

    group_id: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class EntityStateChangedEvent:
    """Event for when an entity state changes."""

    event_type: Final[str] = "entity"
    event: Final[str] = STATE_CHANGED
    platform: str
    unique_id: str
    device_ieee: Optional[EUI64] = None
    endpoint_id: Optional[int] = None
    group_id: Optional[int] = None


class BaseEntity(LogMixin, EventBase):
    """Base class for entities."""

    PLATFORM: Platform = Platform.UNKNOWN

    _attr_fallback_name: str | None = None
    _attr_icon: str | None = None
    _attr_translation_key: str | None = None
    _attr_entity_category: EntityCategory | None = None
    _attr_entity_registry_enabled_default: bool = True
    _attr_device_class: str | None = None
    _attr_state_class: str | None = None
    _attr_enabled: bool = True
    _attr_always_supported: bool = False
    _attr_primary: bool = False

    # When two entities both want to be primary, the one with the higher weight will be
    # chosen. If there is a tie, both lose.
    _attr_primary_weight: int = 0

    def __init__(self, unique_id: str) -> None:
        """Initialize the platform entity."""
        super().__init__()

        self._unique_id: str = unique_id
        self._migrate_unique_ids: list[str] = []

        self.__previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []
        self._tracked_handles: list[asyncio.Handle] = []
        self._on_remove_callbacks: list[Callable[[], None]] = []

    def is_supported(self) -> bool:
        """Return if the entity is supported for the device."""
        if self._attr_always_supported:
            return True

        return self._is_supported()

    def _is_supported(self) -> bool:
        """Return if the entity is supported for the device, internal."""
        return True

    def is_supported_in_list(self, entities: list[BaseEntity]) -> bool:
        """Return if the entity is supported given all other entities."""
        return True

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags."""
        pass

    @property
    def enabled(self) -> bool:
        """Return the entity enabled state."""
        return self._attr_enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set the entity enabled state."""
        self._attr_enabled = value

    @property
    def primary(self) -> bool:
        """Return if the entity is the primary device control."""
        return self._attr_primary

    @primary.setter
    def primary(self, value: bool) -> None:
        """Set the entity as the primary device control."""
        self._attr_primary = value

    @property
    def primary_weight(self) -> int:
        """Return the primary weight of the entity."""
        return self._attr_primary_weight

    @property
    def fallback_name(self) -> str | None:
        """Return the entity fallback name for when a translation key is unavailable."""
        return self._attr_fallback_name

    @property
    def icon(self) -> str | None:
        """Return the entity icon."""
        return self._attr_icon

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
        return self._attr_device_class

    @property
    def state_class(self) -> str | None:
        """Return the state class."""
        return self._attr_state_class

    @final
    @property
    def unique_id(self) -> str:
        """Return the unique id."""
        return self._unique_id

    @final
    @property
    def migrate_unique_ids(self) -> frozenset[str]:
        """Return the previous unique ids to migrate from, if any."""
        return frozenset(self._migrate_unique_ids)

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
            migrate_unique_ids=self.migrate_unique_ids,
            platform=self.PLATFORM,
            class_name=self.__class__.__name__,
            fallback_name=self.fallback_name,
            translation_key=self.translation_key,
            device_class=self.device_class,
            state_class=self.state_class,
            entity_category=self.entity_category,
            entity_registry_enabled_default=self.entity_registry_enabled_default,
            enabled=self.enabled,
            primary=self.primary,
            # Set by platform entities
            cluster_handlers=[],
            device_ieee=None,
            endpoint_id=None,
            available=None,
            # Set by group entities
            group_id=None,
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

    def on_add(self) -> None:
        """Run when entity is added."""
        pass

    async def on_remove(self) -> None:
        """Cancel tasks and timers this entity owns."""
        while self._on_remove_callbacks:
            callback = self._on_remove_callbacks.pop()
            self.debug("Running remove callback: %s", callback)
            callback()

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
                STATE_CHANGED, EntityStateChangedEvent(**self.identifiers.__dict__)
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

    _migrate_platform_unique_ids: tuple[tuple[UniqueIdMigration, str]] | None = None

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        entity_metadata: EntityMetadata | None = None,
        legacy_discovery_unique_id: str | None = None,
        **kwargs: Any,
    ):
        """Initialize the platform entity."""
        if entity_metadata is not None:
            self._init_from_quirks_metadata(entity_metadata)

        if self._unique_id_suffix is not None:
            unique_id = f"{legacy_discovery_unique_id}-{self._unique_id_suffix}"
        else:
            unique_id = legacy_discovery_unique_id

        super().__init__(unique_id=unique_id, **kwargs)

        self._cluster_handlers: list[ClusterHandler] = cluster_handlers
        self.cluster_handlers: dict[str, ClusterHandler] = {}

        for cluster_handler in cluster_handlers:
            self.cluster_handlers[cluster_handler.name] = cluster_handler

        self._device: Device = device
        self._endpoint = endpoint

    def _init_from_quirks_metadata(self, entity_metadata: EntityMetadata) -> None:
        """Init this entity from the quirks metadata."""
        if entity_metadata.initially_disabled:
            self._attr_entity_registry_enabled_default = False

        # v2 quirks entities are assumed to always be supported
        self._attr_always_supported = True

        has_attribute_name = hasattr(entity_metadata, "attribute_name")
        has_command_name = hasattr(entity_metadata, "command_name")
        has_fallback_name = hasattr(entity_metadata, "fallback_name")

        if has_fallback_name:
            self._attr_fallback_name = entity_metadata.fallback_name

        if entity_metadata.translation_key:
            self._attr_translation_key = entity_metadata.translation_key

        if unique_id_suffix := entity_metadata.unique_id_suffix:
            self._unique_id_suffix = unique_id_suffix
        elif has_attribute_name:
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
        return dataclasses.replace(
            super().info_object,
            cluster_handlers=[ch.info_object for ch in self._cluster_handlers],
            device_ieee=self._device.ieee,
            endpoint_id=self._endpoint.id,
            available=self.available,
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
        return dataclasses.replace(
            super().info_object,
            group_id=self.group_id,
        )

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

    def debounced_update(self, _: Any | None = None) -> None:
        """Debounce updating group entity from member entity updates."""
        # Delay to ensure that we get updates from all members before updating the group entity
        assert self._change_listener_debouncer
        self.group.gateway.create_task(self._change_listener_debouncer.async_call())

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._group.register_group_entity(self)

    async def on_remove(self) -> None:
        """Cancel tasks this entity owns."""
        await super().on_remove()
        self._group.unregister_group_entity(self)

        if self._change_listener_debouncer:
            self._change_listener_debouncer.async_cancel()

    @abstractmethod
    def update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""

    async def async_update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""
        self.update()
