"""Platform module for Zigbee Home Automation."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
from collections import defaultdict
from collections.abc import Callable, Mapping
from contextlib import suppress
import dataclasses
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, final

from zigpy.profiles.zha import PROFILE_ID as ZHA_PROFILE_ID
from zigpy.profiles.zll import PROFILE_ID as ZLL_PROFILE_ID
from zigpy.types import ClusterId
from zigpy.types.named import EUI64
import zigpy.zcl
from zigpy.zcl import ReportingConfig
from zigpy.zcl.foundation import ZCLAttributeDef

from zha.application import EntityType, Platform
from zha.application.const import UniqueIdMigration
from zha.const import STATE_CHANGED
from zha.debounce import Debouncer
from zha.event import EventBase
from zha.mixins import LogMixin

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY: float = 0.5

ENTITY_REGISTRY: dict[ClusterId | int, list[type[PlatformEntity]]] = defaultdict(list)
GROUP_ENTITY_REGISTRY: list[type[GroupEntity]] = []


class PlatformFeatureGroup(StrEnum):
    """Feature groups for platform entities."""

    # OnOff server clusters can be turned into lights, shades, or switches (fallback)
    LIGHT_OR_SWITCH_OR_SHADE = "light_or_switch_or_shade"

    # OnOff client clusters can be turned into manufacturer-specific motion sensors or
    # fall back to generic binary sensors
    BINARY_SENSOR = "binary_sensor"

    # Thermostat entities encompass the functionality of Fan entities
    THERMOSTAT_FAN = "thermostat_fan"

    # Model-specific overrides for HVAC action
    HVAC_ACTION = "hvac_action"

    # Model-specific overrides for VOC level
    VOC_LEVEL = "voc_level"

    # Manufacturer-specific overrides for EM active power polling
    EM_ACTIVE_POWER = "em_active_power"

    # Suppress EM cluster polling for devices known to report reliably
    EM_POLLING = "em_polling"

    # Model-specific overrides for local temperature calibration
    LOCAL_TEMPERATURE_CALIBRATION = "local_temperature_calibration"

    # Prefer OTA client update entities over OTA server update entities
    OTA_UPDATE = "ota_update"

    # IAS WD siren entity selection
    SIREN = "siren"


@dataclass(frozen=True)
class AttrConfig:
    """Per-attribute configuration for cluster setup."""

    read_on_startup: bool
    reporting: ReportingConfig | None = None


@dataclass(frozen=True)
class ClusterConfig:
    """Per-cluster configuration."""

    # Whether to bind this cluster to the coordinator.
    bind: bool = False

    # Per-attribute configuration keyed by ZCL attribute definition or name.
    attributes: dict[ZCLAttributeDef | str, AttrConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class ClusterMatch:
    """Declares which clusters an entity requires for discovery."""

    server_clusters: frozenset[int] = frozenset()
    client_clusters: frozenset[int] = frozenset()
    optional_server_clusters: frozenset[int] = frozenset()
    optional_client_clusters: frozenset[int] = frozenset()

    # Strict filters: if present, device info must match
    manufacturers: frozenset[str] | None = None
    models: frozenset[str] | None = None
    exposed_features: frozenset[str] | None = None
    not_exposed_features: frozenset[str] | None = None

    # `None` matches any profile.
    profile_ids: frozenset[int] | None = frozenset({ZHA_PROFILE_ID, ZLL_PROFILE_ID})

    # Profile and device type filters
    profile_device_types: frozenset[tuple[int, int]] | None = None
    not_profile_device_types: frozenset[tuple[int, int]] | None = None

    # For a given feature, only entities with the highest priority will be considered
    feature_priority: tuple[PlatformFeatureGroup, int] | None = None

    # By default ClusterMatch skips clusters whose ep_attribute was renamed by
    # a quirk (so a Switch entity doesn't auto-attach to a Tuya-renamed OnOff
    # cluster). Bind-only virtual entities can opt back in via this flag, since
    # they don't care about cluster semantics — only that the cluster_id is
    # what they target.
    match_renamed_clusters: bool = False

    def __post_init__(self) -> None:
        """Validate the ClusterMatch."""
        if self.profile_device_types is not None and self.profile_ids is not None:
            profile_device_type_profiles = {p for p, _ in self.profile_device_types}

            if not profile_device_type_profiles <= self.profile_ids:
                raise ValueError(
                    "profile_device_types contain profiles not in profile_ids: "
                    f"{profile_device_type_profiles - self.profile_ids}"
                )


def register_entity[T: type[PlatformEntity]](
    cluster_id: ClusterId | int,
) -> Callable[[T], T]:
    """Register an entity class for discovery."""

    def inner(cls: T) -> T:
        ENTITY_REGISTRY[cluster_id].append(cls)
        return cls

    return inner


def register_group_entity(cls: type[GroupEntity]) -> type[GroupEntity]:
    """Register a group entity class for discovery."""
    GROUP_ENTITY_REGISTRY.append(cls)
    return cls


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
    translation_placeholders: dict[str, str] | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    entity_registry_enabled_default: bool
    enabled: bool = True
    primary: bool

    # For platform entities
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
    device_ieee: EUI64 | None = None
    endpoint_id: int | None = None
    group_id: int | None = None


class BaseEntity(LogMixin, EventBase):
    """Base class for entities."""

    PLATFORM: Platform

    async def async_configure_cluster(self, cluster: Any) -> None:
        """Run post-bind cluster-level setup (override in subclasses)."""

    async def async_initialize_cluster(self, cluster: Any) -> None:
        """Run post-initialize cluster-level work (override in subclasses)."""

    _attr_fallback_name: str | None = None
    _attr_icon: str | None = None
    _attr_translation_key: str | None = None
    _attr_translation_placeholders: dict[str, str] | None = None
    _attr_entity_category: EntityCategory | None = None
    _attr_entity_registry_enabled_default: bool = True
    _attr_device_class: str | None = None
    _attr_state_class: str | None = None
    _attr_enabled: bool = True
    _attr_always_supported: bool = False
    _attr_primary: bool | None = None

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
        if self._attr_primary is None:
            return False

        return self._attr_primary

    @primary.setter
    def primary(self, value: bool | None) -> None:
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
    def translation_placeholders(self) -> dict[str, str] | None:
        """Return the translation placeholders."""
        return self._attr_translation_placeholders

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
            translation_placeholders=self.translation_placeholders,
            device_class=self.device_class,
            state_class=self.state_class,
            entity_category=self.entity_category,
            entity_registry_enabled_default=self.entity_registry_enabled_default,
            enabled=self.enabled,
            primary=self.primary,
            # Set by platform entities
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

    # Direct cluster matching for discovery
    _cluster_match: ClusterMatch | None = None

    # Per-cluster configuration (keyed by cluster ID)
    _server_cluster_config: Mapping[int, ClusterConfig] = MappingProxyType({})
    _client_cluster_config: Mapping[int, ClusterConfig] = MappingProxyType({})

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        cluster: zigpy.zcl.Cluster,
        from_quirk: bool = False,
        fallback_name: str | None = None,
        translation_key: str | None = None,
        translation_placeholders: Mapping[str, str] | None = None,
        unique_id_suffix: str | None = None,
        entity_type: EntityType | None = None,
        primary: bool | None = None,
        initially_disabled: bool = False,
        legacy_discovery_unique_id: str | None = None,
        **kwargs: Any,
    ):
        """Initialize the platform entity.

        Quirk entities are constructed with `from_quirk=True` and the generic
        config keywords (`fallback_name`, `translation_key`, `entity_type`, etc.);
        the platform subclasses add their own keywords. Default-discovery
        entities pass none of these.
        """
        if from_quirk:
            self._apply_quirk_entity_config(
                fallback_name=fallback_name,
                translation_key=translation_key,
                translation_placeholders=translation_placeholders,
                unique_id_suffix=unique_id_suffix,
                entity_type=entity_type,
                primary=primary,
                initially_disabled=initially_disabled,
            )

        if legacy_discovery_unique_id is None:
            if from_quirk:
                legacy_discovery_unique_id = f"{device.ieee}-{endpoint.id}"
            else:
                legacy_discovery_unique_id = (
                    f"{device.ieee}-{endpoint.id}-{cluster.cluster_id}"
                )

        if self._unique_id_suffix is not None:
            unique_id = f"{legacy_discovery_unique_id}-{self._unique_id_suffix}"
        else:
            unique_id = legacy_discovery_unique_id

        super().__init__(unique_id=unique_id, **kwargs)

        self._device: Device = device
        self._endpoint = endpoint
        self._cluster: zigpy.zcl.Cluster = cluster

    def _apply_quirk_entity_config(
        self,
        *,
        fallback_name: str | None,
        translation_key: str | None,
        translation_placeholders: Mapping[str, str] | None,
        unique_id_suffix: str | None,
        entity_type: EntityType | None,
        primary: bool | None,
        initially_disabled: bool,
    ) -> None:
        """Apply the generic quirk entity configuration keywords."""
        if initially_disabled:
            self._attr_entity_registry_enabled_default = False

        # quirk entities are assumed to always be supported
        self._attr_always_supported = True

        if fallback_name:
            self._attr_fallback_name = fallback_name

        if translation_key:
            self._attr_translation_key = translation_key

        if translation_placeholders:
            self._attr_translation_placeholders = translation_placeholders

        if unique_id_suffix is not None:
            self._unique_id_suffix = unique_id_suffix

        if entity_type == EntityType.CONFIG:
            self._attr_entity_category = EntityCategory.CONFIG
        elif entity_type == EntityType.DIAGNOSTIC:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        else:
            self._attr_entity_category = None

        if primary is not None:
            self._attr_primary = primary

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
    def cluster(self) -> zigpy.zcl.Cluster:
        """Return the ZCL cluster backing this entity."""
        return self._cluster

    def targets_cluster(
        self,
        cluster_id: int,
        cluster_type: zigpy.zcl.ClusterType | None = None,
    ) -> bool:
        """Return True if this entity targets the given cluster."""
        match = self._cluster_match
        if match is None:
            # Generated quirks-v2 entities have no class-level `_cluster_match`
            # but do have a concrete backing cluster; match against it directly.
            cluster = self.cluster
            if cluster.cluster_id != cluster_id:
                return False
            actual_type = (
                zigpy.zcl.ClusterType.Client
                if cluster.is_client
                else zigpy.zcl.ClusterType.Server
            )
            return cluster_type is None or cluster_type == actual_type

        in_server = (
            cluster_id in match.server_clusters
            or cluster_id in match.optional_server_clusters
        )
        in_client = (
            cluster_id in match.client_clusters
            or cluster_id in match.optional_client_clusters
        )

        if cluster_type == zigpy.zcl.ClusterType.Server:
            return in_server
        if cluster_type == zigpy.zcl.ClusterType.Client:
            return in_client
        return in_server or in_client

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
        """Retrieve latest state.

        Default no-op: subclasses that need polling override this to read their
        own attributes directly from the relevant cluster(s).
        """


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
