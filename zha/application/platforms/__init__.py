"""Platform module for Zigbee Home Automation."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
import logging
from typing import TYPE_CHECKING, Any, Final, Optional, final

from zigpy.quirks.v2 import EntityMetadata, EntityType
from zigpy.types.named import EUI64

from zha.application import Platform
from zha.const import STATE_CHANGED
from zha.event import EventBase
from zha.mixins import LogMixin
from zha.zigbee.cluster_handlers import ClusterHandlerInfo

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)


class EntityCategory(StrEnum):
    """Category of an entity."""

    # Config: An entity which allows changing the configuration of a device.
    CONFIG = "config"

    # Diagnostic: An entity exposing some configuration parameter,
    # or diagnostics of a device.
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, kw_only=True)
class BaseEntityInfo:
    """Information about a base entity."""

    fallback_name: str
    unique_id: str
    platform: str
    class_name: str
    translation_key: str | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    entity_registry_enabled_default: bool


@dataclass(frozen=True, kw_only=True)
class BaseIdentifiers:
    """Identifiers for the base entity."""

    unique_id: str
    platform: str


@dataclass(frozen=True, kw_only=True)
class PlatformEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the platform entity."""

    device_ieee: EUI64
    endpoint_id: int


@dataclass(frozen=True, kw_only=True)
class GroupEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the group entity."""

    group_id: int


@dataclass(frozen=True, kw_only=True)
class PlatformEntityInfo(BaseEntityInfo):
    """Information about a platform entity."""

    cluster_handlers: list[ClusterHandlerInfo]
    device_ieee: EUI64
    endpoint_id: int
    available: bool


@dataclass(frozen=True, kw_only=True)
class GroupEntityInfo(BaseEntityInfo):
    """Information about a group entity."""

    group_id: int


@dataclass(frozen=True, kw_only=True)
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

    _attr_fallback_name: str | None
    _attr_translation_key: str | None
    _attr_entity_category: EntityCategory | None
    _attr_entity_registry_enabled_default: bool = True
    _attr_device_class: str | None
    _attr_state_class: str | None

    def __init__(self, unique_id: str) -> None:
        """Initialize the platform entity."""
        super().__init__()

        self._unique_id: str = unique_id

        self.__previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []
        self._tracked_handles: list[asyncio.Handle] = []

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
    def device_class(self) -> EntityCategory | None:
        """Return the device class."""
        if hasattr(self, "_attr_device_class"):
            return self._attr_device_class
        return None

    @property
    def state_class(self) -> EntityCategory | None:
        """Return the state class."""
        if hasattr(self, "_attr_state_class"):
            return self._attr_state_class
        return None

    @final
    @cached_property
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

    def restore_external_state_attributes(self, **kwargs: Any) -> None:
        """Restore entity specific state attributes from an external source.

        Entities implementing this must accept a keyword argument for each attribute.
        """
        raise NotImplementedError

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
        if self.unique_id not in self._device.platform_entities:
            self._device.platform_entities[self.unique_id] = self
        else:
            _LOGGER.debug(
                "Not registering entity %r, unique id %r already exists: %r",
                self,
                self.unique_id,
                self._device.platform_entities[self.unique_id],
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

        has_device_class = hasattr(entity_metadata, "device_class")
        has_attribute_name = hasattr(entity_metadata, "attribute_name")
        has_command_name = hasattr(entity_metadata, "command_name")

        if not has_device_class or entity_metadata.device_class is None:
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
    def info_object(self) -> PlatformEntityInfo:
        """Return a representation of the platform entity."""
        return PlatformEntityInfo(
            **super().info_object.__dict__,
            cluster_handlers=[ch.info_object for ch in self._cluster_handlers],
            device_ieee=self._device.ieee,
            endpoint_id=self._endpoint.id,
            available=self.available,
        )

    @cached_property
    def device(self) -> Device:
        """Return the device."""
        return self._device

    @cached_property
    def endpoint(self) -> Endpoint:
        """Return the endpoint."""
        return self._endpoint

    @cached_property
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

    def __init__(self, group: Group) -> None:
        """Initialize a group."""
        super().__init__(unique_id=f"{self.PLATFORM}_zha_group_0x{group.group_id:04x}")
        self._attr_fallback_name: str = group.name
        self._group: Group = group
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
    def info_object(self) -> GroupEntityInfo:
        """Return a representation of the group."""
        return GroupEntityInfo(
            **super().info_object.__dict__,
            group_id=self.group_id,
        )

    @property
    def group_id(self) -> int:
        """Return the group id."""
        return self._group.group_id

    @cached_property
    def group(self) -> Group:
        """Return the group."""
        return self._group

    @abstractmethod
    def update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""
