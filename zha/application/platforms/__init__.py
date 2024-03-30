"""Platform module for Zigbee Home Automation."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
import logging
from typing import TYPE_CHECKING, Any, Final, Optional

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

    unique_id: str
    platform: str
    class_name: str


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

    name: str
    cluster_handlers: list[ClusterHandlerInfo]
    device_ieee: EUI64
    endpoint_id: int
    available: bool


@dataclass(frozen=True, kw_only=True)
class GroupEntityInfo(BaseEntityInfo):
    """Information about a group entity."""

    name: str
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

    _unique_id_suffix: str | None = None
    """suffix to add to the unique_id of the entity. Used for multi
       entities using the same cluster handler/cluster id for the entity."""

    def __init__(self, unique_id: str, **kwargs: Any) -> None:
        """Initialize the platform entity."""
        super().__init__()
        self._unique_id: str = unique_id
        if self._unique_id_suffix:
            self._unique_id += f"-{self._unique_id_suffix}"
        self._state: Any = None
        self._previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []

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
            unique_id=self._unique_id,
            platform=self.PLATFORM,
            class_name=self.__class__.__name__,
        )

    def get_state(self) -> dict:
        """Return the arguments to use in the command."""
        return {
            "class_name": self.__class__.__name__,
        }

    async def async_update(self) -> None:
        """Retrieve latest state."""

    async def on_remove(self) -> None:
        """Cancel tasks this entity owns."""
        tasks = [t for t in self._tracked_tasks if not (t.done() or t.cancelled())]
        for task in tasks:
            self.debug("Cancelling task: %s", task)
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    def maybe_emit_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        state = self.get_state()
        if self._previous_state != state:
            self.emit(
                STATE_CHANGED, EntityStateChangedEvent(**self.identifiers.__dict__)
            )
            self._previous_state = state

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a message."""
        msg = f"%s: {msg}"
        args = (self._unique_id,) + args
        _LOGGER.log(level, msg, *args, **kwargs)


class PlatformEntity(BaseEntity):
    """Class that represents an entity for a device platform."""

    _attr_entity_registry_enabled_default: bool
    _attr_translation_key: str | None
    _attr_unit_of_measurement: str | None
    _attr_entity_category: EntityCategory | None

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ):
        """Initialize the platform entity."""
        super().__init__(unique_id, **kwargs)
        ieeetail = "".join([f"{o:02x}" for o in device.ieee[:4]])
        ch_names = ", ".join(sorted(ch.name for ch in cluster_handlers))
        self._name: str = f"{device.name} {ieeetail} {ch_names}"
        if self._unique_id_suffix:
            self._name += f" {self._unique_id_suffix}"
        self._cluster_handlers: list[ClusterHandler] = cluster_handlers
        self.cluster_handlers: dict[str, ClusterHandler] = {}
        for cluster_handler in cluster_handlers:
            self.cluster_handlers[cluster_handler.name] = cluster_handler
        self._device: Device = device
        self._endpoint = endpoint
        # we double create these in discovery tests because we reissue the create calls to count and prove them out
        if self.unique_id not in self._device.platform_entities:
            self._device.platform_entities[self.unique_id] = self

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
        if not has_device_class or (
            has_device_class and entity_metadata.device_class is None
        ):
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
    def name(self) -> str:
        """Return the name of the platform entity."""
        return self._name

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
            unique_id=self._unique_id,
            platform=self.PLATFORM,
            class_name=self.__class__.__name__,
            name=self._name,
            cluster_handlers=[ch.info_object for ch in self._cluster_handlers],
            device_ieee=self._device.ieee,
            endpoint_id=self._endpoint.id,
            available=self.available,
        )

    def get_state(self) -> dict:
        """Return the arguments to use in the command."""
        state = super().get_state()
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
    ) -> None:
        """Initialize a group."""
        super().__init__(f"{self.PLATFORM}.{group.group_id}")
        self._name: str = f"{group.name}_0x{group.group_id:04x}"
        self._group: Group = group
        self._group.register_group_entity(self)

    @property
    def name(self) -> str:
        """Return the name of the group entity."""
        return self._name

    @property
    def group_id(self) -> int:
        """Return the group id."""
        return self._group.group_id

    @property
    def group(self) -> Group:
        """Return the group."""
        return self._group

    @cached_property
    def identifiers(self) -> GroupEntityIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return GroupEntityIdentifiers(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
            group_id=self.group_id,
        )

    @abstractmethod
    def update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""

    @cached_property
    def info_object(self) -> GroupEntityInfo:
        """Return a representation of the group."""
        return GroupEntityInfo(
            unique_id=self._unique_id,
            platform=self.PLATFORM,
            class_name=self.__class__.__name__,
            name=self._name,
            group_id=self.group_id,
        )
