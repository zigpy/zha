"""Platform module for Zigbee Home Automation."""

from __future__ import annotations

from abc import abstractmethod
import asyncio
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from contextlib import suppress
import dataclasses
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from functools import cached_property, partial
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, cast, final
import warnings

from zigpy.profiles.zha import PROFILE_ID as ZHA_PROFILE_ID
from zigpy.profiles.zll import PROFILE_ID as ZLL_PROFILE_ID
from zigpy.types import ClusterId
from zigpy.types.named import EUI64
import zigpy.zcl
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
    foundation,
)
from zigpy.zcl.foundation import ZCLAttributeDef
from zigpy.zcl.helpers import UnsupportedAttribute

from zha.application import EntityType, Platform
from zha.application.const import UniqueIdMigration
from zha.const import STATE_CHANGED
from zha.debounce import Debouncer
from zha.event import EventBase
from zha.exceptions import ZHAException
from zha.mixins import LogMixin
from zha.zigbee.store import (
    ENTITY_ASSUMED_STATE_NAMESPACE,
    ENTITY_STATE_NAMESPACE,
    GROUP_ENTITY_STATE_NAMESPACE,
    DeviceValueWriter,
    entity_state_key,
    get_device_store,
    get_network_store_namespace,
    get_store_namespace,
    group_entity_state_key,
)

if TYPE_CHECKING:
    from zigpy.store import (
        StoredValue,
        StoreNamespace,
        StoreValueDeletedEvent,
        StoreValueUpdatedEvent,
    )

    from zha.zigbee.device import BaseDevice, Device
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)

DEFAULT_UPDATE_GROUP_FROM_CHILD_DELAY: float = 0.5

# Seconds an assumed value is held before it is saved, so that a command the device
# confirms within this time causes no store write
ASSUMED_STATE_SAVE_DELAY: Final = 5

ENTITY_REGISTRY: dict[ClusterId | int, list[type[ZclPlatformEntity]]] = defaultdict(
    list
)
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

    # Whether `reporting` replaces the non-overriding reporting configs other
    # entities declare for the same attribute, instead of being merged with them.
    # By default the tightest config wins, which means a config can only ever make
    # reporting more frequent. Device specific configs (e.g. from quirks) set this to
    # relax ZHA's built-in defaults, such as for devices reporting with a high
    # divisor. Multiple overriding configs are still merged with each other.
    reporting_override: bool = False

    def __post_init__(self) -> None:
        """Validate the configuration."""
        if self.reporting_override and self.reporting is None:
            raise ValueError("reporting_override requires a reporting config")


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


def register_entity[T: type[ZclPlatformEntity]](
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
class BaseEntityState:
    """State for the base entity."""

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

    extra_state_attribute_names: frozenset[str]

    # For platform entities
    device_ieee: EUI64 | None
    endpoint_id: int | None
    available: bool | None

    # For group entities
    group_id: int | None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the extra state attributes as a name to value mapping."""
        return {name: getattr(self, name) for name in self.extra_state_attribute_names}


@dataclasses.dataclass(frozen=True, kw_only=True)
class BaseIdentifiers:
    """Identifiers for the base entity."""

    unique_id: str
    platform: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlatformEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the platform entity."""

    device_ieee: EUI64
    endpoint_id: int | None = None


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
    state_diff: dict[str, Any]


def compute_state_diff(
    old: BaseEntityState | None, new: BaseEntityState
) -> dict[str, Any]:
    """Return the fields of `new` that differ from `old`."""
    new_values = new.__dict__

    if old is None:
        return dict(new_values)

    old_values = old.__dict__
    return {
        name: value for name, value in new_values.items() if old_values[name] != value
    }


@dataclass(frozen=True, kw_only=True)
class AssumedValue:
    """A value a successful command set, and when the command was sent."""

    value: Any
    since: datetime

    def to_json(self) -> dict[str, Any]:
        """Return the value as stored."""
        return {"value": self.value, "since": self.since.isoformat()}

    @classmethod
    def from_json(cls, entry: Any) -> AssumedValue | None:
        """Return a stored value, or `None` if it is malformed."""
        if not isinstance(entry, dict) or "value" not in entry:
            return None

        if not isinstance(since := entry.get("since"), str):
            return None

        try:
            parsed = datetime.fromisoformat(since)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            return None

        return cls(value=entry["value"], since=parsed.astimezone(UTC))


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
    _attr_extra_state_attribute_names: set[str] | None = None

    # Explicitly marks the entity as (not) primary, set by entity classes and quirks.
    # It takes precedence over (and is never overwritten by) the weight-based primary
    # entity election, whose result is held by the device.
    _attr_primary: bool | None = None

    # When two entities both want to be primary, the one with the higher weight will be
    # chosen. If there is a tie, both lose.
    _attr_primary_weight: int = 0

    # Fields of host-side state that no ZCL attribute holds, such as a light's
    # brightness before it was turned off. They are kept in a store (the device's for
    # device entities, the network store for group entities) and restored when the
    # entity is added. By default, field `x` is attribute `_x`.
    _persisted_state_fields: tuple[str, ...] = ()

    def __init__(self, unique_id: str) -> None:
        """Initialize the platform entity."""
        super().__init__()

        self._unique_id: str = unique_id
        self._migrate_unique_ids: list[str] = []

        self.__previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []
        self._tracked_handles: list[asyncio.Handle] = []
        self._on_remove_callbacks: list[Callable[[], None]] = []

        # Persisted state is only saved once it has been loaded, so that the defaults
        # set in `__init__` never overwrite a stored record
        self._persisted_state_loaded: bool = False
        # Fields the store holds for this entity: restored from it, or saved to it.
        # Home Assistant's restored copies of these are older and are ignored.
        self._stored_state_fields: frozenset[str] = frozenset()
        # The fields as they were right after loading
        self._loaded_state: dict[str, Any] | None = None

    def is_supported(self) -> bool:
        """Return if the entity is supported for the device."""
        return self._is_supported()

    def _is_supported(self) -> bool:
        """Return if the entity is supported for the device, internal."""
        return True

    def is_supported_in_list(self, entities: Collection[BaseEntity]) -> bool:
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
        return bool(self._attr_primary)

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

    @property
    def state(self) -> BaseEntityState:
        """Return the state of this entity."""
        return BaseEntityState(
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
            extra_state_attribute_names=frozenset(
                self._attr_extra_state_attribute_names or ()
            ),
            # Set by platform entities
            device_ieee=None,
            endpoint_id=None,
            available=None,
            # Set by group entities
            group_id=None,
        )

    def enable(self) -> None:
        """Enable the entity."""
        self.enabled = True

    def disable(self) -> None:
        """Disable the entity."""
        self.enabled = False

    def on_add(self) -> None:
        """Run when entity is added."""
        self._load_persisted_state()

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
        previous_state = self.__previous_state
        if previous_state != state:
            self.emit(
                STATE_CHANGED,
                EntityStateChangedEvent(
                    **self.identifiers.__dict__,
                    state_diff=compute_state_diff(previous_state, state),
                ),
            )
            self.__previous_state = state

        self._save_persisted_state()

    def subscribe_state(
        self, callback: Callable[[EntityStateChangedEvent], None]
    ) -> Callable[[], None]:
        """Subscribe to state changes, receiving the full state as the first event."""
        self.maybe_emit_state_changed_event()
        unsub = self.on_event(STATE_CHANGED, callback)

        try:
            callback(
                EntityStateChangedEvent(
                    **self.identifiers.__dict__,
                    state_diff=compute_state_diff(None, self.__previous_state),
                )
            )
        except Exception:
            unsub()
            raise

        return unsub

    def _persisted_state_namespace(self) -> StoreNamespace | None:
        """Return the store namespace holding restore records, if there is a store."""
        return None

    def _persisted_state_key(self, unique_id: str) -> str:
        """Return the key of the restore record of this entity under `unique_id`."""
        raise NotImplementedError

    def _owns_persisted_state(self) -> bool:
        """Return whether this entity object may write its records.

        Only the entity its device or group has added does: discovery creates
        candidate copies of live entities, and a removed entity can still finish a
        command, and neither may overwrite the live entity's records.
        """
        return False

    def _dump_persisted_state(self) -> dict[str, Any]:
        """Return the persisted fields as a JSON-compatible record."""
        return {
            name: getattr(self, f"_{name}") for name in self._persisted_state_fields
        }

    def _apply_persisted_state(self, record: Mapping[str, Any]) -> frozenset[str]:
        """Apply a stored record and return the names of the fields it restored."""
        restored = set()

        for name in self._persisted_state_fields:
            if name in record:
                setattr(self, f"_{name}", record[name])
                restored.add(name)

        return frozenset(restored)

    def _load_persisted_state(self) -> None:
        """Restore persisted fields from the store."""
        if self._persisted_state_loaded:
            return

        self._persisted_state_loaded = True

        if not self._persisted_state_fields:
            return

        namespace = self._persisted_state_namespace()

        if namespace is None:
            return

        key = self._persisted_state_key(self.unique_id)

        if self._find_persisted_record(namespace, key):
            self._restore_persisted_record(namespace[key])

        self._loaded_state = self._dump_persisted_state()

    def _find_persisted_record(self, namespace: StoreNamespace, key: str) -> bool:
        """Return whether `namespace` has a record of this entity under `key`.

        A record stored under a previous unique ID is moved to `key` first, so that it
        follows the entity when its unique ID changes.
        """
        if key in namespace:
            return True

        for old_unique_id in sorted(self.migrate_unique_ids):
            old_key = self._persisted_state_key(old_unique_id)

            if old_key in namespace:
                namespace[key] = namespace[old_key]
                del namespace[old_key]
                return True

        return False

    def _restore_persisted_record(self, record: Any) -> None:
        """Apply the stored record of this entity."""
        if not isinstance(record, dict):
            self.warning("Ignoring invalid stored state %r", record)
            return

        try:
            self._stored_state_fields = self._apply_persisted_state(record)
        except Exception:  # noqa: BLE001
            self.error("Failed to restore stored state %r", record, exc_info=True)
            return

        if (
            ignored := (set(record) & set(self._persisted_state_fields))
            - self._stored_state_fields
        ):
            self.debug("Ignoring invalid stored %s in %r", sorted(ignored), record)

    def _save_persisted_state(self, *, take_over: Collection[str] = ()) -> None:
        """Store the persisted fields if they changed.

        Only the entity its device or group has added saves (`_owns_persisted_state`).
        A field is only written once it is owned: restored from the record, changed
        since loading, or named in `take_over` because its value came from Home
        Assistant. Fields still at their loaded values are left out, and no record is
        created for them alone.
        """
        if not self._persisted_state_fields or not self._persisted_state_loaded:
            return

        if not self._owns_persisted_state():
            return

        namespace = self._persisted_state_namespace()

        if namespace is None:
            return

        key = self._persisted_state_key(self.unique_id)
        state = self._dump_persisted_state()
        loaded = self._loaded_state or {}

        # Fields changed since loading are newer than any copy Home Assistant kept.
        # A field still at its loaded value is not, and is left out of the record, so
        # that HA can still fill it after a restart.
        changed = {name for name in state if state[name] != loaded.get(name)}
        owned = self._stored_state_fields | changed | set(take_over)

        if not owned:
            return

        # Keys this version does not know, e.g. from a newer one, are kept
        stored = namespace.get(key)
        record = dict(stored) if isinstance(stored, dict) else {}
        record.update({name: state[name] for name in owned})

        if record != stored:
            namespace[key] = record

        self._stored_state_fields = frozenset(owned)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a message."""
        msg = f"%s: {msg}"
        args = (self._unique_id,) + args
        _LOGGER.log(level, msg, *args, **kwargs)


class PlatformEntity(BaseEntity):
    """Class that represents a device-bound entity for a device platform."""

    # suffix to add to the unique_id of the entity. Used for multi
    # entities using the same cluster handler/cluster id for the entity.
    _unique_id_suffix: str | None = None

    _migrate_platform_unique_ids: tuple[tuple[UniqueIdMigration, str]] | None = None

    # Fields of device state that a successful command sets without the attribute
    # cache changing, such as a lock's state after a lock command. Each has an
    # attribute behind it (`_assumed_state_attribute`). The commanded value is kept in
    # the device's store, with the time the command was sent, until that attribute is
    # reported or read, and is restored when the entity is added unless the attribute
    # cache holds a newer value. By default, field `x` is attribute `_x`.
    _assumed_state_fields: tuple[str, ...] = ()

    def __init__(
        self,
        device: BaseDevice,
        *,
        unique_id: str,
        force_create: bool = False,
        fallback_name: str | None = None,
        translation_key: str | None = None,
        translation_placeholders: Mapping[str, str] | None = None,
        unique_id_suffix: str | None = None,
        entity_type: EntityType | None = None,
        primary: bool | None = None,
        initially_disabled: bool = False,
        **kwargs: Any,
    ):
        """Initialize the platform entity.

        The generic config keywords (`fallback_name`, `translation_key`, `entity_type`,
        etc.) override the class's values when given; the platform subclasses add their
        own keywords. `force_create=True` creates the entity without checking if it is
        supported.
        """
        self._force_create = force_create

        self._apply_entity_config(
            fallback_name=fallback_name,
            translation_key=translation_key,
            translation_placeholders=translation_placeholders,
            unique_id_suffix=unique_id_suffix,
            entity_type=entity_type,
            primary=primary,
            initially_disabled=initially_disabled,
        )

        self._unique_id_base = unique_id

        if self._unique_id_suffix is not None:
            unique_id = f"{unique_id}-{self._unique_id_suffix}"

        super().__init__(unique_id=unique_id, **kwargs)

        self._device: BaseDevice = device

        # Assumed values of `_assumed_state_fields`, by field
        self._assumed_state: dict[str, AssumedValue] = {}
        self._assumed_state_save_handle: asyncio.TimerHandle | None = None
        # Whether a save ran before the device added the entity, and is still to do
        self._assumed_state_save_deferred: bool = False
        # When the assumed values were loaded: a read or report after that is newer
        # than Home Assistant's restored state
        self._state_loaded_at: datetime | None = None

    def _apply_entity_config(
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
        """Apply the generic entity configuration keywords that are given."""
        if initially_disabled:
            self._attr_entity_registry_enabled_default = False

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
        elif entity_type == EntityType.STANDARD:
            self._attr_entity_category = None

        if primary is not None:
            self._attr_primary = primary

    @property
    def device(self) -> BaseDevice:
        """Return the device."""
        return self._device

    @property
    def force_create(self) -> bool:
        """Return if the entity is created without checking if it is supported."""
        return self._force_create

    @property
    def unique_id_base(self) -> str:
        """Return the unique ID the entity was created with, without its suffix."""
        return self._unique_id_base

    @property
    def unique_id_suffix(self) -> str | None:
        """Return the suffix appended to the unique ID base, if any."""
        return self._unique_id_suffix

    @property
    def primary(self) -> bool:
        """Return if the entity is the primary device control."""
        if self._attr_primary is not None:
            return self._attr_primary

        return self._device.primary_entity is self

    @cached_property
    def identifiers(self) -> PlatformEntityIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return PlatformEntityIdentifiers(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
            device_ieee=self.device.ieee,
        )

    @property
    def should_poll(self) -> bool:
        """Return True if we need to poll for state changes."""
        return False

    @property
    def available(self) -> bool:
        """Return true if the device this entity belongs to is available."""
        return self.device.available

    async def async_update(self) -> None:
        """Retrieve latest state.

        Default no-op: subclasses that need polling override this to read their
        own attributes directly from the relevant cluster(s).
        """

    @property
    def state(self) -> BaseEntityState:
        """Return the state of this entity."""
        return dataclasses.replace(
            super().state,
            device_ieee=self._device.ieee,
            available=self.available,
        )

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._subscribe_assumed_state()

    async def on_remove(self) -> None:
        """Save pending assumed values, then cancel tasks and timers."""
        # The device removes an entity before dropping it, so it still owns its record
        self._save_assumed_state()
        await super().on_remove()

    def maybe_emit_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        super().maybe_emit_state_changed_event()

        # The device calls this right after adding the entity: a save that ran before
        # then, such as the one scheduled at load, is done now
        if self._assumed_state_save_deferred and self._owns_persisted_state():
            self._save_assumed_state()

    def _persisted_state_namespace(self) -> StoreNamespace | None:
        """Return the store namespace holding restore records, if there is a store."""
        return get_store_namespace(self._device.device, ENTITY_STATE_NAMESPACE)

    def _persisted_state_key(self, unique_id: str) -> str:
        """Return the key of the restore record of this entity under `unique_id`."""
        return entity_state_key(self.PLATFORM, unique_id)

    def _owns_persisted_state(self) -> bool:
        """Return whether this is the entity the device has added."""
        return (
            self._device.platform_entities.get((self.PLATFORM, self.unique_id)) is self
        )

    def _load_persisted_state(self) -> None:
        """Restore persisted fields and assumed values from the device's store."""
        if self._persisted_state_loaded:
            return

        super()._load_persisted_state()
        self._load_assumed_state()

    def _assumed_state_namespace(self) -> StoreNamespace | None:
        """Return the store namespace holding assumed values, if there is a store."""
        return get_store_namespace(self._device.device, ENTITY_ASSUMED_STATE_NAMESPACE)

    def _assumed_state_attribute(
        self, name: str
    ) -> tuple[zigpy.zcl.Cluster, ZCLAttributeDef] | None:
        """Return the cluster attribute that reports field `name`, if there is one."""
        return None

    def _apply_assumed_value(self, name: str, value: Any) -> bool:
        """Set field `name` to an assumed value and return whether it was valid."""
        setattr(self, f"_{name}", value)
        return True

    def _apply_assumed_state(self) -> None:
        """Set the fields that have assumed values again, after reading the cache."""
        for name, assumed in self._assumed_state.items():
            self._apply_assumed_value(name, assumed.value)

    def _assumed_value_is_current(self, name: str, since: datetime) -> bool:
        """Return whether a value commanded at `since` is newer than the cache.

        A field without an attribute behind it is never kept.
        """
        if (source := self._assumed_state_attribute(name)) is None:
            return False

        cluster, attr_def = source

        try:
            last_updated: datetime = cluster._attr_cache.get_last_updated(  # noqa: SLF001
                attr_def
            )
        except (KeyError, UnsupportedAttribute):
            return True

        return last_updated < since

    def _restored_value_is_stale(self, name: str) -> bool:
        """Return whether Home Assistant's restored copy of field `name` is older.

        It is when the field has an assumed value, or when its attribute was read or
        reported after the entity loaded its state.
        """
        if name in self._assumed_state:
            return True

        if self._state_loaded_at is None or self._assumed_state_attribute(name) is None:
            return False

        return not self._assumed_value_is_current(name, self._state_loaded_at)

    def _assume_state(self, sent: Mapping[str, datetime]) -> None:
        """Keep fields that a successful command set until the device reports them.

        `sent` maps each field to when the command that set it was sent. A field whose
        attribute was reported or read after that already holds the device's answer,
        and is not kept. Saving is delayed (`ASSUMED_STATE_SAVE_DELAY`), so a command
        the device confirms right away writes nothing.
        """
        previous = dict(self._assumed_state)

        for name, since in sent.items():
            if name not in self._assumed_state_fields:
                continue

            if self._assumed_value_is_current(name, since):
                self._assumed_state[name] = AssumedValue(
                    value=getattr(self, f"_{name}"), since=since
                )
            else:
                self._assumed_state.pop(name, None)

        if self._assumed_state != previous:
            self._schedule_assumed_state_save()

    def _schedule_assumed_state_save(self) -> None:
        """Save the assumed values after `ASSUMED_STATE_SAVE_DELAY`.

        The delay starts at the first change and is not extended by later ones.
        """
        if self._assumed_state_save_handle is not None:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._save_assumed_state()
            return

        self._assumed_state_save_handle = loop.call_later(
            ASSUMED_STATE_SAVE_DELAY, self._save_assumed_state
        )
        self._tracked_handles.append(self._assumed_state_save_handle)

    def _subscribe_assumed_state(self) -> None:
        """Drop an assumed value when its attribute is reported or read."""
        by_cluster: dict[int, tuple[zigpy.zcl.Cluster, dict[int, str]]] = {}

        for name in self._assumed_state_fields:
            if (source := self._assumed_state_attribute(name)) is None:
                continue

            cluster, attr_def = source
            by_cluster.setdefault(id(cluster), (cluster, {}))[1][attr_def.id] = name

        for cluster, names_by_attribute in by_cluster.values():
            handler = partial(
                self._handle_assumed_attribute_event, cluster, names_by_attribute
            )

            for event_type in (
                AttributeReadEvent,
                AttributeReportedEvent,
                AttributeUpdatedEvent,
                AttributeWrittenEvent,
            ):
                self._on_remove_callbacks.append(
                    cluster.on_event(event_type.event_type, handler)
                )

    def _handle_assumed_attribute_event(
        self,
        cluster: zigpy.zcl.Cluster,
        names_by_attribute: Mapping[int, str],
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Drop the assumed value of a field whose attribute the device answered for.

        The value read, reported or successfully written confirms or contradicts the
        assumed one, and is newer either way.
        """
        if (name := names_by_attribute.get(event.attribute_id)) is None:
            return

        if (
            isinstance(event, AttributeWrittenEvent)
            and event.status != foundation.Status.SUCCESS
        ):
            return

        # A manufacturer-specific attribute can share the ID of a standard one
        source = self._assumed_state_attribute(name)

        if (
            source is None
            or event.manufacturer_code
            != cluster._get_effective_manufacturer_code(source[1])  # noqa: SLF001
        ):
            return

        if self._assumed_state.pop(name, None) is not None:
            self._schedule_assumed_state_save()

    def _load_assumed_state(self) -> None:
        """Restore assumed values that are newer than the attribute cache.

        Entries that are not restored are removed by a save scheduled here, which
        runs once the device has added the entity.
        """
        if not self._assumed_state_fields:
            return

        self._state_loaded_at = datetime.now(UTC)

        namespace = self._assumed_state_namespace()

        if namespace is None:
            return

        key = self._persisted_state_key(self.unique_id)

        if not self._find_persisted_record(namespace, key):
            return

        record = namespace[key]

        if not isinstance(record, dict):
            self.warning("Ignoring invalid assumed state %r", record)
            self._schedule_assumed_state_save()
            return

        for name in self._assumed_state_fields:
            if name not in record:
                continue

            if (assumed := AssumedValue.from_json(record[name])) is None:
                self.debug("Ignoring invalid assumed %s: %r", name, record[name])
                self._schedule_assumed_state_save()
                continue

            if not self._assumed_value_is_current(name, assumed.since):
                self.debug("Ignoring assumed %s older than the cache", name)
                self._schedule_assumed_state_save()
                continue

            try:
                valid = self._apply_assumed_value(name, assumed.value)
            except Exception:  # noqa: BLE001
                self.error("Failed to restore assumed %s %r", name, assumed.value)
                self._schedule_assumed_state_save()
                continue

            if not valid:
                self.debug("Ignoring invalid assumed %s: %r", name, assumed.value)
                self._schedule_assumed_state_save()
                continue

            self._assumed_state[name] = assumed

    def _save_assumed_state(self) -> None:
        """Store the assumed values if they changed.

        Entries that were not restored (older than the cache, or invalid) and entries
        that were dropped are removed, and the record with them once it is empty.
        """
        if (handle := self._assumed_state_save_handle) is not None:
            self._assumed_state_save_handle = None
            handle.cancel()

            with suppress(ValueError):
                self._tracked_handles.remove(handle)

        if not self._assumed_state_fields or not self._persisted_state_loaded:
            return

        if not self._owns_persisted_state():
            # Not added by the device yet, e.g. while it reads attributes at
            # initialization: saved once it is (`maybe_emit_state_changed_event`)
            self._assumed_state_save_deferred = True
            return

        self._assumed_state_save_deferred = False
        namespace = self._assumed_state_namespace()

        if namespace is None:
            return

        key = self._persisted_state_key(self.unique_id)
        stored = namespace.get(key)

        # Fields this version does not know, e.g. from a newer one, are kept
        record = (
            {
                name: entry
                for name, entry in stored.items()
                if name not in self._assumed_state_fields
            }
            if isinstance(stored, dict)
            else {}
        )
        record.update(
            {name: assumed.to_json() for name, assumed in self._assumed_state.items()}
        )

        if record == stored:
            return

        if record:
            namespace[key] = record
        elif key in namespace:
            del namespace[key]


class DeviceValueEntity(PlatformEntity):
    """Platform entity showing a device value, kept in the device's store.

    A device value is state that is not a ZCL attribute, such as a Tuya datapoint or
    a setting only the host keeps. The entity is bound to the device only, so it
    needs no endpoint or cluster, and follows the value through the store.
    """

    # Set by the writable platforms: writes the value to the device (see
    # `DeviceValueWriter`). Without one, a written value is only kept in the store.
    _writer: DeviceValueWriter[Any] | None = None

    def __init__(
        self,
        device: BaseDevice,
        *,
        value: StoredValue[Any],
        **kwargs: Any,
    ) -> None:
        """Initialize the device value entity."""
        self._value = value
        super().__init__(device, **kwargs)

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        store = get_device_store(self._device.device)

        if store is not None:
            self._on_remove_callbacks.append(
                store.on_change(self._value, self._handle_value_changed)
            )

    # TODO: remove once HA Core's `websocket_get_groupable_devices` no longer reads
    # `entity.endpoint` for every entity of a groupable device
    @property
    def endpoint(self) -> Endpoint:
        """Return the device's first endpoint, for code that expects every entity on one.

        A device value has no endpoint. Home Assistant's list of groupable devices
        reads the endpoint of each entity of a device, and fails without one.
        """
        warnings.warn(
            f"`{type(self).__name__}.endpoint` is deprecated, device-bound entities"
            " have no endpoint",
            DeprecationWarning,
            stacklevel=2,
        )
        endpoints = cast("Device", self._device).endpoints
        return endpoints[min(ep_id for ep_id in endpoints if ep_id != 0)]

    def _handle_value_changed(
        self, event: StoreValueUpdatedEvent | StoreValueDeletedEvent
    ) -> None:
        """Handle the value being set or deleted."""
        self.maybe_emit_state_changed_event()

    def _get_value(self) -> Any:
        """Return the value, or `None` if it is absent or cannot be decoded."""
        store = get_device_store(self._device.device)

        if store is None:
            return None

        return store.get(self._value)

    async def _async_write_value(self, value: Any) -> None:
        """Write the value.

        With a writer, the writer sends it to the device and sets it in the store, and
        its errors propagate. Without one, the value is a setting only the host keeps
        and is set in the store here. Either way, the store's change callback updates
        the entity's state.
        """
        if self._writer is not None:
            await self._writer(self._device.device, value)
            return

        store = get_device_store(self._device.device)

        if store is None:
            raise ZHAException(
                f"Cannot write {self._value.key}: the device has no store"
            )

        store[self._value] = value


class ZclPlatformEntity(PlatformEntity):
    """Platform entity backed by ZCL cluster(s) on an endpoint."""

    # Direct cluster matching for discovery
    _cluster_match: ClusterMatch | None = None

    # Per-cluster configuration (keyed by cluster ID)
    _server_cluster_config: Mapping[int, ClusterConfig] = MappingProxyType({})

    _client_cluster_config: Mapping[int, ClusterConfig] = MappingProxyType({})

    # Set by entity classes driven by the clusters their platform's group entity
    # sends commands to. Only these entities can be part of a group.
    _attr_group_member: bool = False

    _device: Device

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        cluster: zigpy.zcl.Cluster,
        unique_id: str | None = None,
        legacy_discovery_unique_id: str | None = None,
        # TODO: remove this backwards compatibility shim after zha-device-handlers#5410
        # is merged
        from_quirk: bool = False,
        **kwargs: Any,
    ):
        """Initialize the ZCL platform entity.

        Default-discovery entities pass no config keywords. `unique_id` overrides the
        legacy unique ID base.
        """

        if from_quirk:
            assert unique_id is None
            assert "force_create" not in kwargs

            unique_id = f"{device.ieee}-{endpoint.id}"
            kwargs["force_create"] = True

        if legacy_discovery_unique_id is None:
            legacy_discovery_unique_id = (
                f"{device.ieee}-{endpoint.id}-{cluster.cluster_id}"
            )

        if unique_id is None:
            unique_id = legacy_discovery_unique_id

        self._endpoint = endpoint
        self._cluster: zigpy.zcl.Cluster = cluster

        super().__init__(
            device,
            unique_id=unique_id,
            **kwargs,
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

    @property
    def group_member(self) -> bool:
        """Return if the entity can be part of a group."""
        return self._attr_group_member

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

    @cached_property
    def identifiers(self) -> PlatformEntityIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return PlatformEntityIdentifiers(
            unique_id=self.unique_id,
            platform=self.PLATFORM,
            device_ieee=self.device.ieee,
            endpoint_id=self.endpoint.id,
        )

    @property
    def state(self) -> BaseEntityState:
        """Return the state of this entity."""
        return dataclasses.replace(
            super().state,
            endpoint_id=self._endpoint.id,
        )


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

    @property
    def state(self) -> BaseEntityState:
        """Return the state of this entity."""
        return dataclasses.replace(
            super().state,
            available=self.available,
            group_id=self.group_id,
        )

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

    def _persisted_state_namespace(self) -> StoreNamespace | None:
        """Return the network store namespace holding restore records, if any."""
        return get_network_store_namespace(
            self._group.gateway.application_controller, GROUP_ENTITY_STATE_NAMESPACE
        )

    def _persisted_state_key(self, unique_id: str) -> str:
        """Return the key of the restore record of this entity under `unique_id`."""
        return group_entity_state_key(self.group_id, self.PLATFORM, unique_id)

    def _owns_persisted_state(self) -> bool:
        """Return whether this is the entity its group has registered.

        A group's entities are unregistered when it is torn down or drops below two
        members, and stop writing once the gateway no longer has the group, so that
        nothing writes the records again after the group is removed.
        """
        return (
            self._group.gateway.groups.get(self.group_id) is self._group
            and self._group.group_entities.get(self.unique_id) is self
        )

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
