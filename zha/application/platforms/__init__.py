"""Platform module for zhas."""

from __future__ import annotations

import abc
import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any, Final, Optional

from zigpy.quirks.v2 import EntityMetadata, EntityType
from zigpy.types.named import EUI64

from zha.application import Platform
from zha.const import EVENT, EVENT_TYPE, STATE_CHANGED, EventTypes
from zha.event import EventBase
from zha.mixins import LogMixin

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)


class EntityCategory(StrEnum):
    """Category of an entity.

    An entity with a category will:
    - Not be exposed to cloud, Alexa, or Google Assistant components
    - Not be included in indirect service calls to devices or areas
    """

    # Config: An entity which allows changing the configuration of a device.
    CONFIG = "config"

    # Diagnostic: An entity exposing some configuration parameter,
    # or diagnostics of a device.
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, kw_only=True)
class MinimalPlatformEntity:
    """Platform entity model."""

    name: str
    unique_id: str
    platform: str


@dataclass(frozen=True, kw_only=True)
class MinimalEndpoint:
    """Minimal endpoint model."""

    id: int
    unique_id: str


@dataclass(frozen=True, kw_only=True)
class MinimalDevice:
    """Minimal device model."""

    ieee: EUI64


@dataclass(frozen=True, kw_only=True)
class Attribute:
    """Attribute model."""

    id: int
    name: str
    value: Any


@dataclass(frozen=True, kw_only=True)
class MinimalCluster:
    """Minimal cluster model."""

    id: int
    endpoint_attribute: str
    name: str
    endpoint_id: int


@dataclass(frozen=True, kw_only=True)
class MinimalClusterHandler:
    """Minimal cluster handler model."""

    unique_id: str
    cluster: MinimalCluster


@dataclass(frozen=True, kw_only=True)
class MinimalGroup:
    """Minimal group model."""

    id: int


@dataclass(frozen=True, kw_only=True)
class DeviceTrackerState:
    """Device tracker state model."""

    connected: bool
    battery_level: Optional[float]


@dataclass(frozen=True, kw_only=True)
class BooleanState:
    """Boolean value state model."""

    state: bool


@dataclass(frozen=True, kw_only=True)
class CoverState:
    """Cover state model."""

    current_position: int
    state: Optional[str]
    is_opening: bool
    is_closing: bool
    is_closed: bool


@dataclass(frozen=True, kw_only=True)
class ShadeState:
    """Cover state model."""

    current_position: Optional[
        int
    ]  # TODO: how should we represent this when it is None?
    is_closed: bool
    state: Optional[str]


@dataclass(frozen=True, kw_only=True)
class FanState:
    """Fan state model."""

    preset_mode: Optional[
        str
    ]  # TODO: how should we represent these when they are None?
    percentage: Optional[int]  # TODO: how should we represent these when they are None?
    is_on: bool
    speed: Optional[str]


@dataclass(frozen=True, kw_only=True)
class LockState:
    """Lock state model."""

    is_locked: bool


@dataclass(frozen=True, kw_only=True)
class BatteryState:
    """Battery state model."""

    state: Optional[str | float | int]
    battery_size: Optional[str]
    battery_quantity: Optional[int]
    battery_voltage: Optional[float]


@dataclass(frozen=True, kw_only=True)
class ElectricalMeasurementState:
    """Electrical measurement state model."""

    state: Optional[str | float | int]
    measurement_type: Optional[str]
    active_power_max: Optional[str]
    rms_current_max: Optional[str]
    rms_voltage_max: Optional[str]


@dataclass(frozen=True, kw_only=True)
class LightState:
    """Light state model."""

    on: bool
    brightness: Optional[int]
    hs_color: Optional[tuple[float, float]]
    color_temp: Optional[int]
    effect: Optional[str]
    off_brightness: Optional[int]


@dataclass(frozen=True, kw_only=True)
class ThermostatState:
    """Thermostat state model."""

    current_temperature: Optional[float]
    target_temperature: Optional[float]
    target_temperature_low: Optional[float]
    target_temperature_high: Optional[float]
    hvac_action: Optional[str]
    hvac_mode: Optional[str]
    preset_mode: Optional[str]
    fan_mode: Optional[str]


@dataclass(frozen=True, kw_only=True)
class SwitchState:
    """Switch state model."""

    state: bool


class SmareEnergyMeteringState:
    """Smare energy metering state model."""

    state: Optional[str | float | int]
    device_type: Optional[str]
    status: Optional[str]


@dataclass(frozen=True, kw_only=True)
class PlatformEntityStateChangedEvent:
    """Platform entity event."""

    event_type: Final[str] = "platform_entity_event"
    event: Final[str] = "platform_entity_state_changed"
    platform_entity: MinimalPlatformEntity
    endpoint: Optional[MinimalEndpoint]
    device: Optional[MinimalDevice]
    group: Optional[MinimalGroup]
    state: (
        DeviceTrackerState
        | CoverState
        | ShadeState
        | FanState
        | LockState
        | BatteryState
        | ElectricalMeasurementState
        | LightState
        | SwitchState
        | SmareEnergyMeteringState
        | BooleanState
        | ThermostatState
    )


@dataclass(frozen=True, kw_only=True)
class EntityStateChangedEvent:
    """Event for when an entity state changes."""

    event_type: Final[str] = "entity"
    event: Final[str] = STATE_CHANGED
    platform: str
    unique_id: str
    device_ieee: Optional[EUI64]
    endpoint_id: Optional[int]
    group_id: Optional[int]


class PlatformEntityEvents(StrEnum):
    """WS platform entity events."""

    PLATFORM_ENTITY_STATE_CHANGED = "platform_entity_state_changed"


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
        self._extra_state_attributes: dict[str, Any] = {}
        self._previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []

    @property
    def unique_id(self) -> str:
        """Return the unique id."""
        return self._unique_id

    @abc.abstractmethod
    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this platform entity."""

    @abc.abstractmethod
    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""

    def get_state(self) -> dict:
        """Return the arguments to use in the command."""
        return {
            "class_name": self.__class__.__name__,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device specific state attributes."""
        return self._extra_state_attributes

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

    def maybe_send_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        state = self.get_state()
        if self._previous_state != state:
            self.send_event(
                {
                    "state": self.get_state(),
                    EVENT: PlatformEntityEvents.PLATFORM_ENTITY_STATE_CHANGED,
                    EVENT_TYPE: EventTypes.PLATFORM_ENTITY_EVENT,
                }
            )
            self.emit(STATE_CHANGED, EntityStateChangedEvent(**self.get_identifiers()))
            self._previous_state = state

    def to_json(self) -> dict:
        """Return a JSON representation of the platform entity."""
        return {
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
            "class_name": self.__class__.__name__,
            "state": self.get_state(),
        }

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
        device: ZHADevice,
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
        self._device: ZHADevice = device
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
        device: ZHADevice,
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
    def device(self) -> ZHADevice:
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

    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""
        return {
            "unique_id": self.unique_id,
            "platform": self.PLATFORM,
            "device_ieee": self.device.ieee,
            "endpoint_id": self.endpoint.id,
        }

    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this platform entity."""
        signal["platform_entity"] = {
            "name": self._name,
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
        }
        signal["endpoint"] = {
            "id": self._endpoint.id,
            "unique_id": self._endpoint.unique_id,
        }
        _LOGGER.info("Sending event from platform entity: %s", signal)
        self.device.send_event(signal)

    def to_json(self) -> dict:
        """Return a JSON representation of the platform entity."""
        json = super().to_json()
        json["name"] = self._name
        json["cluster_handlers"] = [ch.to_json() for ch in self._cluster_handlers]
        json["device_ieee"] = str(self._device.ieee)
        json["endpoint_id"] = self._endpoint.id
        return json

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
            self.maybe_send_state_changed_event()


class GroupEntity(BaseEntity):
    """A base class for group entities."""

    def __init__(
        self,
        group: Group,
    ) -> None:
        """Initialize a group."""
        super().__init__(f"{self.PLATFORM}.{group.group_id}")
        self._zigpy_group: Group = group
        self._name: str = f"{group.name}_0x{group.group_id:04x}"
        self._group: Group = group
        self._group.register_group_entity(self)
        self.update()

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

    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""
        return {
            "unique_id": self.unique_id,
            "platform": self.PLATFORM,
            "group_id": self.group.group_id,
        }

    def update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""

    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this group entity."""
        signal["platform_entity"] = {
            "name": self._name,
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
        }
        signal["group"] = {
            "id": self._group.group_id,
        }
        _LOGGER.info("Sending event from group entity: %s", signal)
        self._group.send_event(signal)

    def to_json(self) -> dict[str, Any]:
        """Return a JSON representation of the group."""
        json = super().to_json()
        json["name"] = self._name
        json["group_id"] = self.group_id
        return json
