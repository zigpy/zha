"""Device for Zigbee Home Automation."""

# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
import contextlib
import copy
import dataclasses
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
import logging
import time
from typing import TYPE_CHECKING, Any, Final

from zigpy.device import Device as ZigpyDevice
import zigpy.exceptions
from zigpy.profiles import PROFILES
from zigpy.types import uint1_t, uint8_t, uint16_t
from zigpy.types.named import EUI64, NWK, ExtendedPanId
from zigpy.typing import UNDEFINED, UndefinedType
import zigpy.zcl
from zigpy.zcl.clusters import Cluster
from zigpy.zcl.clusters.general import Basic, Groups, Identify, Ota
from zigpy.zcl.foundation import (
    Status as ZclStatus,
    WriteAttributesResponse,
    ZCLCommandDef,
)
import zigpy.zdo.types as zdo_types
from zigpy.zdo.types import (
    DeviceType,
    PermitJoins,
    Relationship,
    RouteStatus,
    RxOnWhenIdle,
)

from zha.application import Platform, discovery
from zha.application.const import (
    ATTR_ARGS,
    ATTR_ATTRIBUTE,
    ATTR_CLUSTER_ID,
    ATTR_CLUSTER_TYPE,
    ATTR_COMMAND,
    ATTR_COMMAND_TYPE,
    ATTR_ENDPOINT_ID,
    ATTR_ENDPOINTS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NODE_DESCRIPTOR,
    ATTR_PARAMS,
    ATTR_QUIRK_ID,
    ATTR_VALUE,
    CLUSTER_COMMAND_SERVER,
    CLUSTER_COMMANDS_CLIENT,
    CLUSTER_COMMANDS_SERVER,
    CLUSTER_TYPE_IN,
    CLUSTER_TYPE_OUT,
    POWER_BATTERY_OR_UNKNOWN,
    POWER_MAINS_POWERED,
    UNKNOWN,
    UNKNOWN_MANUFACTURER,
    UNKNOWN_MODEL,
    ZHA_CLUSTER_BIND_EVENT,
    ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT,
    ZHA_DEVICE_CONFIGURED_EVENT,
    ZHA_DEVICE_ENTITY_ADDED_EVENT,
    ZHA_DEVICE_ENTITY_REMOVED_EVENT,
    ZHA_DEVICE_UPDATED_EVENT,
    ZHA_EVENT,
)
from zha.application.helpers import convert_to_zcl_values, convert_zcl_value, safe_read
from zha.application.platforms import (
    BaseEntity,
    BaseEntityState,
    EntityStateChangedEvent,
    PlatformEntity,
    sensor,
)
from zha.application.platforms.update import BaseFirmwareUpdateEntity
from zha.const import STATE_CHANGED
from zha.event import EventBase, suppress_events
from zha.exceptions import ZHAException
from zha.mixins import LogMixin
from zha.quirks import (
    QUIRK_REGISTRY_ENTRY_ATTR,
    DeviceMatch,
    ReplacingZigpyDeviceFactory,
)
from zha.zigbee.cluster_config import (
    aggregate_cluster_configs,
    configure_cluster_configs,
    initialize_cluster_configs,
)
from zha.zigbee.endpoint import Endpoint

if TYPE_CHECKING:
    from zha.application.gateway import Gateway

_LOGGER = logging.getLogger(__name__)
_CHECKIN_GRACE_PERIODS = 2
DIAGNOSTICS_JSON_VERSION = 3


def get_cluster_attr_data(cluster: Cluster) -> list[dict]:
    """Return cluster attribute data."""
    attributes_info = []

    for attr_def in cluster.attributes.values():
        info = {
            "id": f"0x{attr_def.id:04x}",
            "name": attr_def.name,
            "zcl_type": (
                attr_def.zcl_type.name if attr_def.zcl_type.name != "bool_" else "bool"
            ),
            "value": cluster.get(attr_def.name),
            "unsupported": cluster.is_attribute_unsupported(attr_def),
        }

        # Don't unnecessarily list out attributes that are just unread
        if info["value"] is None and not info["unsupported"]:
            continue

        # Delete unused keys
        if info["value"] is not None:
            del info["unsupported"]
        else:
            del info["value"]

        attributes_info.append(info)

    return attributes_info


def _cluster_entry(cluster_id: int, cluster: Cluster) -> dict[str, Any]:
    """Build the per-cluster diagnostics entry."""
    return {
        "cluster_id": f"0x{cluster_id:04x}",
        "endpoint_attribute": cluster.ep_attribute,
        "attributes": get_cluster_attr_data(cluster),
    }


def get_device_automation_triggers(
    device: zigpy.device.Device,
) -> dict[tuple[str, str], dict[str, str]]:
    """Get the supported device automation triggers for a zigpy device."""
    return {
        ("device_offline", "device_offline"): {"device_event_type": "device_offline"},
        **getattr(device, "device_automation_triggers", {}),
    }


@dataclass(frozen=True, kw_only=True)
class ClusterBinding:
    """Describes a cluster binding."""

    name: str
    type: str
    id: int
    endpoint_id: int


class DeviceStatus(Enum):
    """Status of a device."""

    CREATED = 1
    INITIALIZED = 2


@dataclass(kw_only=True, frozen=True)
class ZHAEvent:
    """Event generated when a device wishes to send an arbitrary event."""

    device_ieee: EUI64
    unique_id: str
    data: dict[str, Any]
    event_type: Final[str] = ZHA_EVENT
    event: Final[str] = ZHA_EVENT


@dataclass(kw_only=True, frozen=True)
class DeviceFirmwareInfoUpdatedEvent:
    """Event generated when the device firmware information has changed."""

    event_type: Final[str] = ZHA_DEVICE_UPDATED_EVENT
    event: Final[str] = ZHA_DEVICE_UPDATED_EVENT

    old_firmware_version: str | None
    new_firmware_version: str | None


@dataclass(kw_only=True, frozen=True)
class DeviceEntityAddedEvent:
    """Event generated when a new entity is added to a device."""

    event_type: Final[str] = ZHA_DEVICE_ENTITY_ADDED_EVENT
    event: Final[str] = ZHA_DEVICE_ENTITY_ADDED_EVENT

    # TODO: allow all entity information to be serialized and include it here
    platform: Platform
    unique_id: str


@dataclass(kw_only=True, frozen=True)
class DeviceEntityRemovedEvent:
    """Event generated when an entity is removed from a device."""

    event_type: Final[str] = ZHA_DEVICE_ENTITY_REMOVED_EVENT
    event: Final[str] = ZHA_DEVICE_ENTITY_REMOVED_EVENT

    platform: Platform
    unique_id: str
    remove: bool = False


@dataclass(kw_only=True, frozen=True)
class DeviceConfiguredEvent:
    """Emitted when `device.async_configure()` completes."""

    event_type: Final[str] = ZHA_DEVICE_CONFIGURED_EVENT
    event: Final[str] = ZHA_DEVICE_CONFIGURED_EVENT

    device_ieee: EUI64


@dataclass(kw_only=True, frozen=True)
class ClusterBindEvent:
    """Emitted after attempting to bind a cluster to the coordinator."""

    event_type: Final[str] = ZHA_CLUSTER_BIND_EVENT
    event: Final[str] = ZHA_CLUSTER_BIND_EVENT

    device_ieee: EUI64
    endpoint_id: int
    cluster_id: int
    cluster_name: str
    success: bool


@dataclass(kw_only=True, frozen=True)
class ClusterConfigureReportingEvent:
    """Emitted after configuring attribute reporting on a cluster.

    ``attributes`` is keyed by attribute name; each value is
    ``{"id", "name", "min", "max", "change", "status"}`` where ``status`` is
    the per-attribute ZCL status name or ``"FAILURE"`` on transport error.
    """

    event_type: Final[str] = ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT
    event: Final[str] = ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT

    device_ieee: EUI64
    endpoint_id: int
    cluster_id: int
    cluster_name: str
    attributes: dict[str, dict[str, Any]]


@dataclass(kw_only=True, frozen=True)
class DeviceInfo:
    """Describes a device."""

    ieee: EUI64
    nwk: NWK
    manufacturer: str
    model: str
    name: str
    quirk_applied: bool
    quirk_class: str
    exposes_features: set[str]
    manufacturer_code: int | None
    power_source: str
    lqi: int
    rssi: int
    last_seen: str
    available: bool
    device_type: str
    signature: dict[str, Any]


@dataclass(kw_only=True, frozen=True)
class NeighborInfo:
    """Describes a neighbor."""

    device_type: DeviceType
    rx_on_when_idle: RxOnWhenIdle
    relationship: Relationship
    extended_pan_id: ExtendedPanId
    ieee: EUI64
    nwk: NWK
    permit_joining: PermitJoins
    depth: uint8_t
    lqi: uint8_t


@dataclass(kw_only=True, frozen=True)
class RouteInfo:
    """Describes a route."""

    dest_nwk: NWK
    route_status: RouteStatus
    memory_constrained: uint1_t
    many_to_one: uint1_t
    route_record_required: uint1_t
    next_hop: NWK


@dataclass(kw_only=True, frozen=True)
class EndpointNameInfo:
    """Describes an endpoint name."""

    name: str


@dataclass(kw_only=True, frozen=True)
class ExtendedDeviceInfo(DeviceInfo):
    """Describes a ZHA device."""

    active_coordinator: bool
    entities: dict[str, BaseEntityState]
    neighbors: list[NeighborInfo]
    routes: list[RouteInfo]
    endpoint_names: list[EndpointNameInfo]


class Device(LogMixin, EventBase):
    """ZHA Zigbee device object."""

    # Authoring surface for hand-written quirks; `None` marks the unquirked fallback.
    _device_match: DeviceMatch | None = None
    _zigpy_device_cls: ReplacingZigpyDeviceFactory | None = None
    _zigpy_device_transforms: tuple[
        Callable[[zigpy.device.Device], zigpy.device.Device], ...
    ] = ()

    # Cached properties that depend on the zigpy device and must be invalidated
    # when the underlying device is swapped (e.g. after a re-interview).
    _ZIGPY_CACHED_PROPERTIES: Final = (
        "name",
        "manufacturer",
        "model",
        "device_alerts",
        "manufacturer_code",
        "is_mains_powered",
        "device_type",
        "is_router",
        "is_coordinator",
        "is_end_device",
        "skip_configuration",
        "device_automation_commands",
        "device_automation_triggers",
        "zigbee_signature",
    )

    def __init__(
        self,
        zigpy_device: zigpy.device.Device,
        _gateway: Gateway,
    ) -> None:
        """Initialize the gateway."""
        super().__init__()

        self.unique_id = str(zigpy_device.ieee)
        self._gateway: Gateway = _gateway

        self._platform_entities: dict[tuple[Platform, str], PlatformEntity] = {}
        self._pending_entities: list[PlatformEntity] = []
        self._primary_entity: PlatformEntity | None = None
        # All entities discovered for this device, including ones removed by a quirk.
        # Used for aggregating cluster configs so binding/reporting matches the
        # legacy claim-during-discovery flow (which configured handlers even when
        # the visible entity was filtered out later).
        self._discovered_entities: list[PlatformEntity] = []
        self._initialized: bool = False
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(3)
        self._on_remove_callbacks: list[Callable[[], None]] = []
        self._endpoints: dict[int, Endpoint] = {}

        self._available: bool = False
        self._checkins_missed_count: int = 0
        self._on_network: bool = True

        self._init_from_zigpy_device(zigpy_device)

    def _init_from_zigpy_device(self, zigpy_device: zigpy.device.Device) -> None:
        """(Re-)initialize device state from a zigpy device.

        Sets up the zigpy device reference, quirk metadata, cluster handlers,
        and endpoints.  Called from ``__init__`` and after a successful
        re-interview where zigpy swaps the underlying device object.
        """
        # Clear collections that will be rebuilt below.  During __init__ these
        # are already empty; after a re-interview on_remove() has cleaned up
        # the old handlers/entities but the lists themselves still hold stale
        # references.
        self._on_remove_callbacks.clear()
        self._endpoints.clear()
        self._pending_entities.clear()
        self._discovered_entities.clear()

        self._zigpy_device: ZigpyDevice = zigpy_device

        # Invalidate cached properties that depend on the zigpy device before
        # they are read below (e.g. is_mains_powered, is_coordinator).
        for attr in self._ZIGPY_CACHED_PROPERTIES:
            with contextlib.suppress(AttributeError):
                delattr(self, attr)

        # Both v1 and v2 quirks stash their registry entry on the resolved device.
        entry = getattr(self._zigpy_device, QUIRK_REGISTRY_ENTRY_ATTR, None)
        self.quirk_applied: bool = entry is not None
        if entry is not None and entry.source is not None:
            self.quirk_class: str = f"{entry.source.module}:{entry.source.label}"
        else:
            self.quirk_class = (
                f"{self._zigpy_device.__class__.__module__}."
                f"{self._zigpy_device.__class__.__name__}"
            )

        # add v1 quirk exposed features (legacy quirk id)
        qid: set[str] | str = getattr(self._zigpy_device, ATTR_QUIRK_ID, set())
        self.exposes_features: set[str] = {qid} if isinstance(qid, str) else set(qid)

        # add quirk-exposed features (declarative quirks override this hook)
        self.exposes_features |= self._quirk_exposes_features()

        self._firmware_version: str | None = None

        device_options = self._gateway.config.config.device_options
        if self.is_mains_powered:
            self.consider_unavailable_time: int = (
                device_options.consider_unavailable_mains
            )
        else:
            self.consider_unavailable_time = device_options.consider_unavailable_battery
        self._available = self.is_active_coordinator or (
            self.last_seen is not None
            and time.time() - self.last_seen < self.consider_unavailable_time
        )

        self.status: DeviceStatus = DeviceStatus.CREATED

        for ep_id, endpoint in zigpy_device.endpoints.items():
            if ep_id != 0:
                ep = Endpoint.new(endpoint, self)
                self._endpoints[ep_id] = ep
                self._on_remove_callbacks.append(ep.on_remove)

    def __repr__(self) -> str:
        """Return a string representation of the device."""
        return (
            f"{repr(self._zigpy_device)} - "
            f"quirk_applied: {self.quirk_applied} - "
            f"quirk_or_device_class: {self.quirk_class} - "
            f"exposes_features: {self.exposes_features}"
        )

    @property
    def device(self) -> zigpy.device.Device:
        """Return underlying Zigpy device."""
        return self._zigpy_device

    @cached_property
    def name(self) -> str:
        """Return device name."""
        # Nabu Casa devices include a brand name in the model
        if self.manufacturer == "Nabu Casa":
            return self.model
        return f"{self.manufacturer} {self.model}"

    @property
    def ieee(self) -> EUI64:
        """Return ieee address for device."""
        return self._zigpy_device.ieee

    @property
    def quirk_metadata(self) -> Any | None:
        """Return the ZHA-level quirk metadata, or None.

        The base class and hand-written/v1 quirks have none; zhaquirks'
        `QuirkV2Device` overrides this (and the `_quirk_*`/`_resolve_*` hooks
        below) to surface its `QuirkDefinition`.
        """
        return None

    def _quirk_exposes_features(self) -> set[str]:
        """Extra exposed features contributed by a quirk."""
        return set()

    def _quirk_skip_configuration(self) -> bool:
        """Whether a quirk forces configuration to be skipped."""
        return False

    def _quirk_device_automation_triggers(
        self,
    ) -> dict[tuple[str, str], dict[str, str]]:
        """Device automation triggers contributed by a quirk."""
        return {}

    def _is_entity_removed_by_quirk(self, entity: PlatformEntity) -> bool:
        """Whether a quirk hides this default entity (declarative quirks override)."""
        return False

    def _apply_entity_metadata_changes(self, entity: PlatformEntity) -> None:
        """Apply a quirk's metadata overrides to an entity (declarative quirks override)."""

    @cached_property
    def manufacturer(self) -> str:
        """Return manufacturer for device."""
        return self._resolve_manufacturer()

    def _resolve_manufacturer(self) -> str:
        """Resolve the manufacturer name (declarative quirks override this)."""
        if self.is_active_coordinator:
            manufacturer = (
                self.gateway.application_controller.state.node_info.manufacturer
            )
            return manufacturer if manufacturer is not None else ""

        if self._zigpy_device.manufacturer is None:
            return UNKNOWN_MANUFACTURER

        return self._zigpy_device.manufacturer

    @cached_property
    def model(self) -> str:
        """Return model for device."""
        return self._resolve_model()

    def _resolve_model(self) -> str:
        """Resolve the model name (declarative quirks override this)."""
        if self.is_active_coordinator:
            model = self.gateway.application_controller.state.node_info.model
            if model is None:
                return f"Generic Zigbee Coordinator ({self.gateway.radio_type.pretty_name})"
            return model

        if self._zigpy_device.model is None:
            return UNKNOWN_MODEL

        return self._zigpy_device.model

    @cached_property
    def device_alerts(self) -> Iterable[Any]:
        """Return device alerts for this device (declarative quirks override this)."""
        return []

    @cached_property
    def manufacturer_code(self) -> int | None:
        """Return the manufacturer code for the device."""
        if self._zigpy_device.node_desc is None:
            return None

        return self._zigpy_device.node_desc.manufacturer_code

    @property
    def nwk(self) -> NWK:
        """Return nwk for device."""
        return self._zigpy_device.nwk

    @property
    def lqi(self):
        """Return lqi for device."""
        return self._zigpy_device.lqi

    @property
    def rssi(self):
        """Return rssi for device."""
        return self._zigpy_device.rssi

    @property
    def last_seen(self) -> float | None:
        """Return last_seen for device."""
        return self._zigpy_device.last_seen

    @cached_property
    def is_mains_powered(self) -> bool | None:
        """Return true if device is mains powered."""
        if self._zigpy_device.node_desc is None:
            return None

        return self._zigpy_device.node_desc.is_mains_powered

    @cached_property
    def device_type(self) -> str:
        """Return the logical device type for the device."""
        if self._zigpy_device.node_desc is None:
            return UNKNOWN

        return self._zigpy_device.node_desc.logical_type.name

    @property
    def power_source(self) -> str:
        """Return the power source for the device."""
        return (
            POWER_MAINS_POWERED if self.is_mains_powered else POWER_BATTERY_OR_UNKNOWN
        )

    @cached_property
    def is_router(self) -> bool | None:
        """Return true if this is a routing capable device."""
        if self._zigpy_device.node_desc is None:
            return None

        return self._zigpy_device.node_desc.is_router

    @cached_property
    def is_coordinator(self) -> bool | None:
        """Return true if this device represents a coordinator."""
        if self._zigpy_device.node_desc is None:
            return None

        return self._zigpy_device.node_desc.is_coordinator

    @property
    def is_active_coordinator(self) -> bool:
        """Return true if this device is the active coordinator."""
        if not self.is_coordinator:
            return False

        return self.ieee == self.gateway.state.node_info.ieee

    @cached_property
    def is_end_device(self) -> bool | None:
        """Return true if this device is an end device."""
        if self._zigpy_device.node_desc is None:
            return None

        return self._zigpy_device.node_desc.is_end_device

    @property
    def is_groupable(self) -> bool:
        """Return true if this device has a group cluster."""
        return self.is_active_coordinator or (
            self.available and bool(self.async_get_groupable_endpoints())
        )

    @cached_property
    def skip_configuration(self) -> bool:
        """Return true if the device should not issue configuration related commands."""
        if self._quirk_skip_configuration():
            return True
        return self._zigpy_device.skip_configuration or bool(self.is_active_coordinator)

    @property
    def gateway(self):
        """Return the gateway for this device."""
        return self._gateway

    @cached_property
    def device_automation_commands(self) -> dict[str, list[tuple[str, str]]]:
        """Return the a lookup of commands to etype/sub_type."""
        commands: dict[str, list[tuple[str, str]]] = {}
        for etype_subtype, trigger in self.device_automation_triggers.items():
            if command := trigger.get(ATTR_COMMAND):
                commands.setdefault(command, []).append(etype_subtype)
        return commands

    @cached_property
    def device_automation_triggers(self) -> dict[tuple[str, str], dict[str, str]]:
        """Return the device automation triggers for this device."""
        triggers = get_device_automation_triggers(self._zigpy_device)
        triggers.update(self._quirk_device_automation_triggers())
        return triggers

    @property
    def available(self):
        """Return True if device is available."""
        return self.is_active_coordinator or (self._available and self.on_network)

    @available.setter
    def available(self, new_availability: bool) -> None:
        """Set device availability."""
        self._available = new_availability

    @property
    def on_network(self):
        """Return True if device is currently on the network."""
        return self.is_active_coordinator or self._on_network

    @on_network.setter
    def on_network(self, new_on_network: bool) -> None:
        """Set device on_network flag."""
        self.update_available(new_on_network)
        self._on_network = new_on_network
        if not new_on_network:
            self.debug("Device is not on the network, marking unavailable")

    def _first_in_cluster(self, cluster_id: int) -> zigpy.zcl.Cluster | None:
        """Return the first in_cluster with the given cluster_id across endpoints."""
        for ep_id, ep in self._zigpy_device.endpoints.items():
            if ep_id == 0:
                continue
            cluster = ep.in_clusters.get(cluster_id)
            if cluster is not None:
                return cluster
        return None

    @property
    def basic_cluster(self) -> zigpy.zcl.Cluster | None:
        """Return the first Basic cluster across endpoints, if present."""
        return self._first_in_cluster(Basic.cluster_id)

    @property
    def identify_cluster(self) -> zigpy.zcl.Cluster | None:
        """Return the first Identify cluster across endpoints, if present."""
        return self._first_in_cluster(Identify.cluster_id)

    @property
    def endpoints(self) -> dict[int, Endpoint]:
        """Return the endpoints for this device."""
        return self._endpoints

    @cached_property
    def zigbee_signature(self) -> dict[str, Any]:
        """Get zigbee signature for this device."""
        return {
            ATTR_NODE_DESCRIPTOR: self._zigpy_device.node_desc,
            ATTR_ENDPOINTS: {
                signature[0]: signature[1]
                for signature in [
                    endpoint.zigbee_signature for endpoint in self._endpoints.values()
                ]
            },
            ATTR_MANUFACTURER: self.manufacturer,
            ATTR_MODEL: self.model,
        }

    @property
    def firmware_version(self) -> str | None:
        """Return the software version for this device."""
        return self._firmware_version

    @property
    def platform_entities(self) -> dict[tuple[Platform, str], PlatformEntity]:
        """Return the platform entities for this device."""
        return self._platform_entities

    @property
    def primary_entity(self) -> PlatformEntity | None:
        """Return the primary entity of the device, if any."""
        return self._primary_entity

    def get_platform_entity(self, platform: Platform, unique_id: str) -> PlatformEntity:
        """Get a platform entity by unique id."""
        entity = self._platform_entities.get((platform, unique_id))
        if entity is None:
            raise KeyError(f"Entity {unique_id} not found")
        return entity

    def get_entity(
        self,
        platform: Platform,
        endpoint_id: int | None = None,
        cluster_id: int | None = None,
        *,
        pick_first: bool = False,
    ) -> PlatformEntity:
        """Look up the unique entity matching platform/endpoint/cluster filters.

        With pick_first=True, returns the first match instead of raising on multiple
        matches. Always raises if there are zero matches.
        """
        matches = []
        for entity in self._platform_entities.values():
            if platform != entity.PLATFORM:
                continue
            if endpoint_id is not None and entity.endpoint.id != endpoint_id:
                continue
            if cluster_id is not None and entity.cluster.cluster_id != cluster_id:
                continue
            matches.append(entity)
        if not matches or (not pick_first and len(matches) != 1):
            raise LookupError(
                f"Expected {'>=1' if pick_first else '1'} entity matching "
                f"platform={platform!r}, endpoint_id={endpoint_id}, "
                f"cluster_id={cluster_id}; found {len(matches)}"
            )
        return matches[0]

    @classmethod
    def new(
        cls,
        zigpy_dev: zigpy.device.Device,
        gateway: Gateway,
    ) -> Device:
        """Create new device, dispatching to the factory matched during resolution."""
        if zigpy_dev.ieee == gateway.state.node_info.ieee:
            return CoordinatorDevice(zigpy_dev, gateway)

        entry = getattr(zigpy_dev, QUIRK_REGISTRY_ENTRY_ATTR, None)
        if entry is not None and entry.zha_device_factory is not None:
            return entry.zha_device_factory(zigpy_dev, gateway)

        return cls(zigpy_dev, gateway)

    def async_update_firmware_version(self, firmware_version: str) -> None:
        """Update device firmware version."""
        if firmware_version == self._firmware_version:
            return

        old_firmware_version = self._firmware_version
        self._firmware_version = firmware_version

        self.emit(
            DeviceFirmwareInfoUpdatedEvent.event_type,
            DeviceFirmwareInfoUpdatedEvent(
                old_firmware_version=old_firmware_version,
                new_firmware_version=firmware_version,
            ),
        )

    async def _check_available(self, *_: Any) -> None:
        # don't flip the availability state of the coordinator
        if self.is_active_coordinator:
            return
        if self.last_seen is None:
            self.debug("last_seen is None, marking the device unavailable")
            self.update_available(False)
            return

        difference = time.time() - self.last_seen
        if difference < self.consider_unavailable_time:
            self.debug(
                "Device seen - marking the device available and resetting counter"
            )
            self.update_available(True)
            self._checkins_missed_count = 0
            return

        if self._gateway.config.allow_polling:
            if (
                self._checkins_missed_count >= _CHECKIN_GRACE_PERIODS
                or self.manufacturer == "LUMI"
                or not self._endpoints
            ):
                self.debug(
                    (
                        "last_seen is %s seconds ago and ping attempts have been exhausted,"
                        " marking the device unavailable"
                    ),
                    difference,
                )
                self.update_available(False)
                return

            self._checkins_missed_count += 1
            self.debug(
                "Attempting to checkin with device - missed checkins: %s",
                self._checkins_missed_count,
            )
            basic = self.basic_cluster
            if basic is None:
                self.debug("does not have a mandatory basic cluster")
                self.update_available(False)
                return
            res = await safe_read(
                basic, [ATTR_MANUFACTURER], allow_cache=False, only_cache=False
            )
            if res.get(ATTR_MANUFACTURER) is not None:
                self._checkins_missed_count = 0

    def update_available(self, available: bool) -> None:
        """Update device availability and signal entities."""
        self.debug(
            (
                "Update device availability -  device available: %s - new availability:"
                " %s - changed: %s"
            ),
            self.available,
            available,
            self.available ^ available,
        )
        availability_changed = self.available ^ available
        self.available = available
        if availability_changed and available:
            # reinit cluster handlers then signal entities
            self.debug(
                "Device availability changed and device became available,"
                " reinitializing cluster handlers"
            )
            self._gateway.async_create_task(
                self._async_became_available(),
                name=f"({self.nwk},{self.model})_async_became_available",
                eager_start=True,
            )
            return
        if availability_changed and not available:
            self.debug("Device availability changed and device became unavailable")
            for entity in self.platform_entities.values():
                entity.maybe_emit_state_changed_event()
            self.emit_zha_event(
                {
                    "device_event_type": "device_offline",
                },
            )

    def emit_zha_event(self, event_data: dict[str, str | int]) -> None:  # pylint: disable=unused-argument
        """Relay events directly."""
        self.emit(
            ZHA_EVENT,
            ZHAEvent(
                device_ieee=self.ieee,
                unique_id=str(self.ieee),
                data=event_data,
            ),
        )

    async def _async_became_available(self) -> None:
        """Update device availability and signal entities."""
        await self.async_initialize(False)
        for platform_entity in self._platform_entities.values():
            platform_entity.maybe_emit_state_changed_event()

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device."""
        ieee = self.ieee
        time_struct = time.localtime(self.last_seen)
        update_time = time.strftime("%Y-%m-%dT%H:%M:%S", time_struct)
        return DeviceInfo(
            ieee=ieee,
            nwk=self.nwk,
            manufacturer=self.manufacturer,
            model=self.model,
            name=self.name,
            quirk_applied=self.quirk_applied,
            quirk_class=self.quirk_class,
            exposes_features=self.exposes_features,
            manufacturer_code=self.manufacturer_code,
            power_source=self.power_source,
            lqi=self.lqi,
            rssi=self.rssi,
            last_seen=update_time,
            available=self.available,
            device_type=self.device_type,
            signature=self.zigbee_signature,
        )

    @property
    def extended_device_info(self) -> ExtendedDeviceInfo:
        """Get extended device information."""
        topology = self.gateway.application_controller.topology
        names: list[EndpointNameInfo] = []
        for endpoint in (ep for epid, ep in self.device.endpoints.items() if epid):
            profile = PROFILES.get(endpoint.profile_id)
            if profile and endpoint.device_type is not None:
                # DeviceType provides undefined enums
                names.append(
                    EndpointNameInfo(name=profile.DeviceType(endpoint.device_type).name)
                )
            else:
                names.append(
                    EndpointNameInfo(
                        name=(
                            f"unknown {endpoint.device_type} device_type "
                            f"of 0x{(endpoint.profile_id or 0xFFFF):04x} profile id"
                        )
                    )
                )

        return ExtendedDeviceInfo(
            **self.device_info.__dict__,
            active_coordinator=self.is_active_coordinator,
            entities={
                platform_entity.unique_id: platform_entity.state
                for platform_entity in self.platform_entities.values()
            },
            neighbors=[
                NeighborInfo(
                    device_type=neighbor.device_type.name,
                    rx_on_when_idle=neighbor.rx_on_when_idle.name,
                    relationship=neighbor.relationship.name,
                    extended_pan_id=neighbor.extended_pan_id,
                    ieee=neighbor.ieee,
                    nwk=neighbor.nwk,
                    permit_joining=neighbor.permit_joining.name,
                    depth=neighbor.depth,
                    lqi=neighbor.lqi,
                )
                for neighbor in topology.neighbors[self.ieee]
            ],
            routes=[
                RouteInfo(
                    dest_nwk=route.DstNWK,
                    route_status=route.RouteStatus.name,
                    memory_constrained=route.MemoryConstrained,
                    many_to_one=route.ManyToOne,
                    route_record_required=route.RouteRecordRequired,
                    next_hop=route.NextHop,
                )
                for route in topology.routes[self.ieee]
            ],
            endpoint_names=names,
        )

    async def async_configure(self) -> None:
        """Configure the device."""
        self.debug("started configuration")

        if hasattr(self._zigpy_device, "apply_custom_configuration"):
            self.debug("applying quirks custom device configuration")
            await self._zigpy_device.apply_custom_configuration()

        self._discover_new_entities()

        # Configure binding and reporting from entity-level cluster configs
        aggregated = aggregate_cluster_configs(self._discovered_entities)
        if aggregated and not self.skip_configuration:
            await configure_cluster_configs(self, aggregated)

        self.emit_reconfigure_done()

        self.debug("completed configuration")

        identify_cluster = self.identify_cluster
        if (
            self.gateway.config.config.device_options.enable_identify_on_join
            and identify_cluster is not None
            and not self.skip_configuration
        ):
            self._gateway.async_create_task(
                identify_cluster.trigger_effect(
                    effect_id=Identify.EffectIdentifier.Okay,
                    effect_variant=Identify.EffectVariant.Default,
                ),
                name=f"({self.nwk},{self.model}) trigger_effect identify",
                eager_start=True,
            )

    async def async_rebuild_from_zigpy_device(
        self, zigpy_device: zigpy.device.Device
    ) -> None:
        """Tear down and rebuild this device from a new zigpy device.

        Called by the gateway after a successful re-interview swaps the
        underlying zigpy device.  Emits entity removal events so listeners
        (e.g. HA) can clean up stale entities.
        """
        await self.async_teardown(emit_entity_events=True)
        self._init_from_zigpy_device(zigpy_device)

    def emit_reconfigure_done(self) -> None:
        """Emit `DeviceConfiguredEvent`.

        Called by the gateway after a reconfigure (successful or not) so the
        HA frontend's reconfigure dialog unsticks.
        """
        self.emit(
            ZHA_DEVICE_CONFIGURED_EVENT,
            DeviceConfiguredEvent(device_ieee=self.ieee),
        )

    def discover_entities(self) -> Iterator[BaseEntity]:
        """Yield the default (ZCL) entities for this device.

        Declarative quirks add their exposed entities by overriding this in
        zhaquirks' `QuirkV2Device`; hand-written quirks override it directly.
        """
        # TODO: purge old coordinator entities
        if self.is_coordinator:
            return

        for ep_id, endpoint in self.endpoints.items():
            if ep_id == 0:
                continue

            _LOGGER.debug(
                "Discovering entities for endpoint: %s-%s",
                str(endpoint.device.ieee),
                endpoint.id,
            )
            yield from discovery.discover_entities_for_endpoint(endpoint)

    def _discover_new_entities(self) -> None:
        self._discovered_entities.clear()

        # Iterate defensively so a failure in any single entity construction
        # does not abort discovery for the rest of the device.
        iterator = iter(self.discover_entities())
        while True:
            try:
                entity = next(iterator)
            except StopIteration:
                break
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Failed to create entity during discovery")
                continue

            self._discovered_entities.append(entity)

            if self._is_entity_removed_by_quirk(entity):
                continue

            # Apply any metadata changes from quirks v2
            self._apply_entity_metadata_changes(entity)

            entity.on_add()
            self._pending_entities.append(entity)

    def _add_entity(self, entity: PlatformEntity, *, emit_event: bool = True) -> None:
        """Add an entity to the device."""
        key = (entity.PLATFORM, entity.unique_id)

        if key in self._platform_entities:
            raise ValueError(
                f"Cannot add entity {entity!r}, unique ID already taken by {self._platform_entities[key]!r}"
            )

        self.debug("Discovered new entity %s", entity)

        # `entity.on_add()` is assumed to have been called already
        self._platform_entities[key] = entity

        if emit_event:
            self.emit(
                DeviceEntityAddedEvent.event_type,
                DeviceEntityAddedEvent(
                    platform=entity.PLATFORM,
                    unique_id=entity.unique_id,
                ),
            )

    async def _remove_entity(
        self,
        entity: BaseEntity,
        *,
        emit_event: bool = True,
        remove: bool = False,
    ) -> None:
        """Remove an entity from the device."""
        key = (entity.PLATFORM, entity.unique_id)

        if key not in self._platform_entities:
            raise ValueError(f"Cannot remove entity {entity!r}, unique ID not found")

        try:
            await entity.on_remove()
        finally:
            # Always drop the mapping entry — otherwise a re-interview that
            # rediscovers the same unique_id would skip the replacement and
            # leave the stale entity shadowing it indefinitely.
            del self._platform_entities[key]
            if entity is self._primary_entity:
                # No re-election here: every live-removal caller runs the
                # election right after via `_add_pending_entities`
                self._primary_entity = None
            if emit_event:
                self.emit(
                    DeviceEntityRemovedEvent.event_type,
                    DeviceEntityRemovedEvent(
                        platform=entity.PLATFORM,
                        unique_id=entity.unique_id,
                        remove=remove,
                    ),
                )

    def _entity_supported(
        self,
        entity: PlatformEntity,
        others: Iterable[PlatformEntity],
        *,
        on_error: bool,
    ) -> bool:
        """Recompute an entity's capabilities and return whether it is supported.

        Both steps run entity (and, for quirk entities, quirk-supplied) code that
        reads attributes off the cluster. A quirk can leave a cluster without the
        definitions that code assumes, and zigpy raises `KeyError` for those, so a
        single broken entity would otherwise abort device initialization and, via
        `load_devices`, fail the whole ZHA setup.

        `on_error` is what an entity that cannot answer the question counts as.
        A prospective entity is dropped (it could never produce a state anyway),
        but an entity that already exists is kept: removing it is destructive,
        as consumers delete its registry entry along with the user's
        customizations, and its state reads are contained on the paths that
        run them here.
        """
        try:
            entity.recompute_capabilities()
            return entity.is_supported() and entity.is_supported_in_list(others)
        except Exception:  # pylint: disable=broad-except
            self.error(
                "Failed to determine whether %s entity %s is supported,"
                " treating it as %s",
                entity.PLATFORM,
                entity.unique_id,
                "supported" if on_error else "unsupported",
                exc_info=True,
            )
            return on_error

    async def _add_pending_entities(self, *, emit_event: bool = True) -> None:
        """Add pending entities to the device."""
        all_entities = dict(self._platform_entities)
        new_entities: dict[tuple[Platform, str], PlatformEntity] = {}

        for entity in self._pending_entities:
            # Ignore unsupported entities - and entities that cannot even answer the
            # question, which a quirk-gutted cluster produces (see `_entity_supported`)
            if not self._entity_supported(
                entity, all_entities.values(), on_error=False
            ):
                await entity.on_remove()
                continue

            key = (entity.PLATFORM, entity.unique_id)

            # Ignore entities that already exist
            if key in all_entities:
                await entity.on_remove()
                continue

            all_entities[key] = entity
            new_entities[key] = entity

        self._pending_entities.clear()

        # Compute a new primary entity
        self._compute_primary_entity(all_entities.values())

        # Finally, add the new entities
        for entity in new_entities.values():
            self._add_entity(entity, emit_event=emit_event)

        # New entities have no listener yet (consumers capture their initial state when
        # the add event registers them), so silence their changes
        with suppress_events():
            for entity in new_entities.values():
                self._safe_emit_state_changed_event(entity)

        # `_compute_primary_entity` above can flip `primary` on an existing entity, and
        # the caller may have recomputed their capabilities beforehand; emit so those
        # changes reach consumers.
        for key, entity in all_entities.items():
            if key not in new_entities:
                self._safe_emit_state_changed_event(entity)

    def _safe_emit_state_changed_event(self, entity: PlatformEntity) -> None:
        """Emit an entity's state change, tolerating a broken entity.

        Computing a state runs entity (and, for quirk entities, quirk-supplied)
        code. Letting that propagate would abort device initialization and, via
        `load_devices`, fail the whole ZHA setup — one bad entity would take
        every device down with it.
        """
        try:
            entity.maybe_emit_state_changed_event()
        except Exception:  # pylint: disable=broad-except
            self.error(
                "Failed to emit state changed event for %s entity %s",
                entity.PLATFORM,
                entity.unique_id,
                exc_info=True,
            )

    async def recompute_entities(self) -> None:
        """Recompute all entities for this device."""
        self.debug("Recomputing entities")

        entities = list(self._platform_entities.values())

        # Remove all entities that are no longer supported
        for entity in entities[:]:
            if not self._entity_supported(entity, entities, on_error=True):
                self.debug("Removing unsupported entity %s", entity)
                await self._remove_entity(entity, remove=True)
                entities.remove(entity)

        # Discover new entities
        self._discover_new_entities()
        await self._add_pending_entities()

    async def async_initialize(self, from_cache: bool = False) -> None:
        """Initialize cluster handlers."""
        self.debug("started initialization")

        # We discover prospective entities before initialization
        self._discover_new_entities()

        # Read initial attributes from entity-level cluster configs
        aggregated = aggregate_cluster_configs(self._discovered_entities)
        if aggregated and not self.skip_configuration:
            await initialize_cluster_configs(aggregated, from_cache)

        # And add them after. Emit events only on re-initialization, not the first.
        await self._add_pending_entities(emit_event=self._initialized)
        self._initialized = True

        # Sync the device's firmware version with the first platform entity
        for (platform, _unique_id), entity in self.platform_entities.items():
            if platform != Platform.UPDATE:
                continue

            assert isinstance(entity, BaseFirmwareUpdateEntity)
            self._firmware_version = entity.installed_version

            def entity_update_listener(event: EntityStateChangedEvent) -> None:
                """Listen to firmware update entity changes."""
                entity = self.get_platform_entity(event.platform, event.unique_id)
                assert isinstance(entity, BaseFirmwareUpdateEntity)
                self.async_update_firmware_version(entity.installed_version)

            self._on_remove_callbacks.append(
                entity.on_event(STATE_CHANGED, entity_update_listener)
            )

            break

        self.debug("power source: %s", self.power_source)
        self.status = DeviceStatus.INITIALIZED
        self.debug("completed initialization")

    async def async_teardown(self, *, emit_entity_events: bool) -> None:
        """Tear down handlers, entities, and endpoints.

        Args:
            emit_entity_events: When True, emit ``DeviceEntityRemovedEvent``
                for each removed entity so that listeners (e.g. HA) can clean
                up.  Shutdown paths pass False to avoid unnecessary traffic.

        """
        for callback in self._on_remove_callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.warning(
                    "Failed to execute on_remove callback %s for device %s",
                    callback,
                    self,
                    exc_info=True,
                )

        for platform_entity in list(self._platform_entities.values()):
            try:
                await self._remove_entity(
                    platform_entity, emit_event=emit_entity_events
                )
            except Exception:
                _LOGGER.warning(
                    "Failed to remove platform entity %s for device %s",
                    platform_entity,
                    self,
                    exc_info=True,
                )

        for entity in self._pending_entities:
            try:
                await entity.on_remove()
            except Exception:
                _LOGGER.warning(
                    "Failed to remove pending entity %s for device %s",
                    entity,
                    self,
                    exc_info=True,
                )

        # Ensure stale pending entities aren't reprocessed if the device is
        # re-initialized after removal (e.g. re-interview).
        self._pending_entities.clear()

    async def on_remove(self) -> None:
        """Cancel tasks this device owns (shutdown path)."""
        await self.async_teardown(emit_entity_events=False)

    def async_get_clusters(self) -> dict[int, dict[str, dict[int, Cluster]]]:
        """Get all clusters for this device."""
        return {
            ep_id: {
                CLUSTER_TYPE_IN: endpoint.in_clusters,
                CLUSTER_TYPE_OUT: endpoint.out_clusters,
            }
            for (ep_id, endpoint) in self._zigpy_device.endpoints.items()
            if ep_id != 0
        }

    def async_get_groupable_endpoints(self):
        """Get device endpoints that have a group 'in' cluster."""
        return [
            ep_id
            for (ep_id, clusters) in self.async_get_clusters().items()
            if Groups.cluster_id in clusters[CLUSTER_TYPE_IN]
        ]

    def async_get_std_clusters(self):
        """Get ZHA and ZLL clusters for this device."""

        return {
            ep_id: {
                CLUSTER_TYPE_IN: endpoint.in_clusters,
                CLUSTER_TYPE_OUT: endpoint.out_clusters,
            }
            for (ep_id, endpoint) in self._zigpy_device.endpoints.items()
            if ep_id != 0 and endpoint.profile_id in PROFILES
        }

    def async_get_cluster(
        self, endpoint_id: int, cluster_id: int, cluster_type: str = CLUSTER_TYPE_IN
    ) -> Cluster:
        """Get zigbee cluster from this entity."""
        clusters: dict[int, dict[str, dict[int, Cluster]]] = self.async_get_clusters()
        return clusters[endpoint_id][cluster_type][cluster_id]

    def async_get_cluster_attributes(
        self, endpoint_id, cluster_id, cluster_type=CLUSTER_TYPE_IN
    ):
        """Get zigbee attributes for specified cluster."""
        return self.async_get_cluster(endpoint_id, cluster_id, cluster_type).attributes

    def async_get_cluster_commands(
        self, endpoint_id, cluster_id, cluster_type=CLUSTER_TYPE_IN
    ):
        """Get zigbee commands for specified cluster."""
        cluster = self.async_get_cluster(endpoint_id, cluster_id, cluster_type)
        return {
            CLUSTER_COMMANDS_CLIENT: cluster.client_commands,
            CLUSTER_COMMANDS_SERVER: cluster.server_commands,
        }

    async def write_zigbee_attribute(
        self,
        endpoint_id: int,
        cluster_id: int,
        attribute: int | str,
        value: Any,
        cluster_type: str = CLUSTER_TYPE_IN,
        manufacturer: int | UndefinedType | None = UNDEFINED,
    ) -> WriteAttributesResponse | None:
        """Write a value to a zigbee attribute for a cluster in this entity."""
        try:
            cluster: Cluster = self.async_get_cluster(
                endpoint_id, cluster_id, cluster_type
            )
        except KeyError as exc:
            raise ValueError(
                f"Cluster {cluster_id} not found on endpoint {endpoint_id} while"
                f" writing attribute {attribute} with value {value}"
            ) from exc

        attr_def = cluster.find_attribute(attribute)
        value = convert_zcl_value(value, attr_def.type)

        try:
            response = await cluster.write_attributes(
                {attribute: value}, manufacturer=manufacturer
            )
            self.debug(
                "set: %s for attr: %s to cluster: %s for ept: %s - res: %s",
                value,
                attribute,
                cluster_id,
                endpoint_id,
                response,
            )
            return response
        except zigpy.exceptions.ZigbeeException as exc:
            raise ZHAException(
                f"Failed to set attribute: "
                f"{ATTR_VALUE}: {value} "
                f"{ATTR_ATTRIBUTE}: {attribute} "
                f"{ATTR_CLUSTER_ID}: {cluster_id} "
                f"{ATTR_ENDPOINT_ID}: {endpoint_id}"
            ) from exc

    async def issue_cluster_command(
        self,
        endpoint_id: int,
        cluster_id: int,
        command: int,
        command_type: str,
        args: list | None,
        params: dict[str, Any] | None,
        cluster_type: str = CLUSTER_TYPE_IN,
        manufacturer: int | None = None,
    ) -> None:
        """Issue a command against specified zigbee cluster on this device."""
        try:
            cluster: Cluster = self.async_get_cluster(
                endpoint_id, cluster_id, cluster_type
            )
        except KeyError as exc:
            raise ValueError(
                f"Cluster {cluster_id} not found on endpoint {endpoint_id} while"
                f" issuing command {command} with args {args}"
            ) from exc
        commands: dict[int, ZCLCommandDef] = (
            cluster.server_commands
            if command_type == CLUSTER_COMMAND_SERVER
            else cluster.client_commands
        )
        if args is not None:
            self.warning(
                (
                    "args [%s] are deprecated and should be passed with the params key."
                    " The parameter names are: %s"
                ),
                args,
                [field.name for field in commands[command].schema.fields],
            )
            response = await getattr(cluster, commands[command].name)(*args)
        else:
            assert params is not None
            response = await getattr(cluster, commands[command].name)(
                **convert_to_zcl_values(params, commands[command].schema)
            )
        self.debug(
            "Issued cluster command: %s %s %s %s %s %s %s %s",
            f"{ATTR_CLUSTER_ID}: [{cluster_id}]",
            f"{ATTR_CLUSTER_TYPE}: [{cluster_type}]",
            f"{ATTR_ENDPOINT_ID}: [{endpoint_id}]",
            f"{ATTR_COMMAND}: [{command}]",
            f"{ATTR_COMMAND_TYPE}: [{command_type}]",
            f"{ATTR_ARGS}: [{args}]",
            f"{ATTR_PARAMS}: [{params}]",
            f"{ATTR_MANUFACTURER}: [{manufacturer}]",
        )
        if response is None:
            return  # client commands don't return a response
        if isinstance(response, Exception):
            raise ZHAException("Failed to issue cluster command") from response

        # Depending on the command, the reply is either a Default Response
        # (`command_id`, `status`) or the cluster-specific response defined for that
        # command, whose fields differ per command. A field named `status` means the
        # same thing in either kind of reply -- but its position does not carry over:
        # indexing blindly into the response reads an unrelated field (e.g. a Groups
        # `add_response`'s `group_id`) and reports it as a status. Many cluster-specific
        # responses, such as `get_membership_response`, have no `status` field at all.
        status = getattr(response, "status", None)
        if status is not None and status != ZclStatus.SUCCESS:
            raise ZHAException(f"Failed to issue cluster command with status: {status}")

    async def async_add_to_group(self, group_id: int) -> None:
        """Add this device to the provided zigbee group."""
        try:
            # A group name is required. However, the spec also explicitly states that
            # the group name can be ignored by the receiving device if a device cannot
            # store it, so we cannot rely on it existing after being written. This is
            # only done to make the ZCL command valid.
            await self._zigpy_device.add_to_group(group_id, name=f"0x{group_id:04X}")
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
            self.debug(
                "Failed to add device '%s' to group: 0x%04x ex: %s",
                self._zigpy_device.ieee,
                group_id,
                str(ex),
            )

    async def async_remove_from_group(self, group_id: int) -> None:
        """Remove this device from the provided zigbee group."""
        try:
            await self._zigpy_device.remove_from_group(group_id)
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
            self.debug(
                "Failed to remove device '%s' from group: 0x%04x ex: %s",
                self._zigpy_device.ieee,
                group_id,
                str(ex),
            )

    async def async_add_endpoint_to_group(
        self, endpoint_id: int, group_id: int
    ) -> None:
        """Add the device endpoint to the provided zigbee group."""
        try:
            await self._zigpy_device.endpoints[endpoint_id].add_to_group(
                group_id, name=f"0x{group_id:04X}"
            )
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
            self.debug(
                "Failed to add endpoint: %s for device: '%s' to group: 0x%04x ex: %s",
                endpoint_id,
                self._zigpy_device.ieee,
                group_id,
                str(ex),
            )

    async def async_remove_endpoint_from_group(
        self, endpoint_id: int, group_id: int
    ) -> None:
        """Remove the device endpoint from the provided zigbee group."""
        try:
            await self._zigpy_device.endpoints[endpoint_id].remove_from_group(group_id)
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
            self.debug(
                (
                    "Failed to remove endpoint: %s for device '%s' from group: 0x%04x"
                    " ex: %s"
                ),
                endpoint_id,
                self._zigpy_device.ieee,
                group_id,
                str(ex),
            )

    async def async_bind_to_group(
        self, group_id: int, cluster_bindings: list[ClusterBinding]
    ) -> None:
        """Directly bind this device to a group for the given clusters."""
        await self._async_group_binding_operation(
            group_id, zdo_types.ZDOCmd.Bind_req, cluster_bindings
        )

    async def async_unbind_from_group(
        self, group_id: int, cluster_bindings: list[ClusterBinding]
    ) -> None:
        """Unbind this device from a group for the given clusters."""
        await self._async_group_binding_operation(
            group_id, zdo_types.ZDOCmd.Unbind_req, cluster_bindings
        )

    async def _async_group_binding_operation(
        self,
        group_id: int,
        operation: zdo_types.ZDOCmd,
        cluster_bindings: list[ClusterBinding],
    ) -> None:
        """Create or remove a direct zigbee binding between a device and a group."""

        zdo = self._zigpy_device.zdo
        op_msg = "0x%04x: %s %s, ep: %s, cluster: %s to group: 0x%04x"
        destination_address = zdo_types.MultiAddress()
        destination_address.addrmode = uint8_t(1)
        destination_address.nwk = uint16_t(group_id)

        tasks = []

        for cluster_binding in cluster_bindings:
            if cluster_binding.endpoint_id == 0:
                continue
            if (
                cluster_binding.id
                in self._zigpy_device.endpoints[
                    cluster_binding.endpoint_id
                ].out_clusters
            ):
                op_params = (
                    self.nwk,
                    operation.name,
                    str(self.ieee),
                    cluster_binding.endpoint_id,
                    cluster_binding.id,
                    group_id,
                )
                zdo.debug(f"processing {op_msg}", *op_params)
                tasks.append(
                    (
                        zdo.request(
                            operation,
                            self.ieee,
                            cluster_binding.endpoint_id,
                            cluster_binding.id,
                            destination_address,
                        ),
                        op_msg,
                        op_params,
                    )
                )
        res = await asyncio.gather(*(t[0] for t in tasks), return_exceptions=True)
        for outcome, log_msg in zip(res, tasks):
            if isinstance(outcome, Exception):
                fmt = f"{log_msg[1]} failed: %s"
            else:
                fmt = f"{log_msg[1]} completed: %s"
            zdo.debug(fmt, *(log_msg[2] + (outcome,)))

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a message."""
        msg = f"[%s](%s): {msg}"
        args = (self.nwk, self.model) + args
        _LOGGER.log(level, msg, *args, **kwargs)

    def _compute_primary_entity(self, entities: Sequence[PlatformEntity]) -> None:
        """Compute the primary entity from a given set of entities."""
        self._primary_entity = None

        # First, check if any entity is explicitly primary
        explicitly_primary = [entity for entity in entities if entity._attr_primary]

        if len(explicitly_primary) == 1:
            self.debug(
                "Device has a single explicitly primary entity,"
                " not performing weight matching"
            )
            self._primary_entity = explicitly_primary[0]
            return

        # It should not be possible for there to be more than one
        assert not explicitly_primary

        # For weight matching, only consider entities with a non-zero primary weight
        # which are not explicitly marked as not primary. Entities disabled at runtime
        # (via the entity registry in HA) deliberately stay candidates: the primary
        # entity describes the main feature of the device, which does not change when
        # its entity is disabled.
        candidates = [
            e for e in entities if e._attr_primary is not False and e.primary_weight > 0
        ]
        candidates.sort(reverse=True, key=lambda e: e.primary_weight)

        if not candidates:
            return

        winner = candidates[0]
        others = candidates[1:]

        # We have a clear winner
        if not others or winner.primary_weight > others[0].primary_weight:
            self._primary_entity = winner
            return

        self.debug(
            "Primary entity tie between %s and %s, no primary entity", winner, others[0]
        )

    def get_diagnostics_json(self):
        """Get ZHA device information."""

        info: dict[str, Any] = {}
        info["version"] = DIAGNOSTICS_JSON_VERSION
        info["ieee"] = str(self.ieee)
        info["nwk"] = str(self.nwk)
        info["manufacturer"] = self.device.manufacturer
        info["model"] = self.device.model
        info["friendly_manufacturer"] = self.manufacturer
        info["friendly_model"] = self.model
        info["name"] = self.name
        info["quirk_applied"] = self.quirk_applied
        info["quirk_class"] = self.quirk_class
        info["exposes_features"] = self.exposes_features
        info["manufacturer_code"] = self.manufacturer_code
        info["power_source"] = self.power_source
        info["lqi"] = self.lqi
        info["rssi"] = self.rssi
        info["last_seen"] = self.device._last_seen.isoformat()
        info["available"] = self.available
        info["device_type"] = self.device_type
        info["active_coordinator"] = self.is_active_coordinator

        node_desc = self.device.node_desc
        info["node_descriptor"] = {
            "logical_type": node_desc.logical_type.name,
            "complex_descriptor_available": bool(
                node_desc.complex_descriptor_available
            ),
            "user_descriptor_available": bool(node_desc.user_descriptor_available),
            "reserved": node_desc.reserved,
            "aps_flags": node_desc.aps_flags,
            "frequency_band": node_desc.frequency_band,
            "mac_capability_flags": node_desc.mac_capability_flags,
            "manufacturer_code": node_desc.manufacturer_code,
            "maximum_buffer_size": node_desc.maximum_buffer_size,
            "maximum_incoming_transfer_size": node_desc.maximum_incoming_transfer_size,
            "server_mask": node_desc.server_mask,
            "maximum_outgoing_transfer_size": node_desc.maximum_outgoing_transfer_size,
            "descriptor_capability_field": node_desc.descriptor_capability_field,
        }

        info["endpoints"] = {}

        for endpoint in sorted(
            self.device.non_zdo_endpoints, key=lambda ep: ep.endpoint_id
        ):
            info["endpoints"][endpoint.endpoint_id] = {
                "profile_id": endpoint.profile_id,
                "device_type": {
                    "name": (
                        (
                            PROFILES[endpoint.profile_id]
                            .DeviceType(endpoint.device_type)
                            .name
                        )
                        if endpoint.profile_id in PROFILES
                        and endpoint.device_type is not None
                        else UNKNOWN
                    ),
                    "id": endpoint.device_type,
                },
                "in_clusters": [
                    _cluster_entry(cluster_id, cluster)
                    for cluster_id, cluster in sorted(endpoint.in_clusters.items())
                ],
                "out_clusters": [
                    {
                        **_cluster_entry(cluster_id, cluster),
                        **(
                            {
                                "last_query_cmd": {
                                    "manufacturer_code": cluster.last_query_cmd.manufacturer_code,
                                    "image_type": cluster.last_query_cmd.image_type,
                                    "current_file_version": cluster.last_query_cmd.current_file_version,
                                    "hardware_version": cluster.last_query_cmd.hardware_version,
                                }
                            }
                            if isinstance(cluster, Ota)
                            and getattr(cluster, "last_query_cmd", None) is not None
                            else {}
                        ),
                    }
                    for cluster_id, cluster in sorted(endpoint.out_clusters.items())
                ],
            }

        original_signature = copy.deepcopy(self.device.original_signature)

        # if we have a quirked device we add the original signature to the output and
        # convert the profile_id, device_type, input_clusters and output_clusters to hex
        # representation to make it consistent with the rest of the data
        if original_signature is not None:
            if "endpoints" in original_signature:
                for ep in original_signature["endpoints"].values():
                    if "profile_id" in ep:
                        ep["profile_id"] = f"0x{ep['profile_id']:04x}"

                    if "device_type" in ep:
                        ep["device_type"] = f"0x{ep['device_type']:04x}"

                    if "input_clusters" in ep:
                        ep["input_clusters"] = [
                            f"0x{c:04x}" for c in ep["input_clusters"]
                        ]

                    if "output_clusters" in ep:
                        ep["output_clusters"] = [
                            f"0x{c:04x}" for c in ep["output_clusters"]
                        ]

            info["original_signature"] = original_signature

        info["zha_lib_entities"] = defaultdict(list)

        for (platform, _unique_id), platform_entity in sorted(
            self.platform_entities.items()
        ):
            if platform is Platform.VIRTUAL:
                continue

            state_dict = dataclasses.asdict(platform_entity.state)
            state_dict["migrate_unique_ids"] = list(state_dict["migrate_unique_ids"])
            state_dict["device_ieee"] = str(state_dict["device_ieee"])
            state_dict["extra_state_attribute_names"] = sorted(
                state_dict["extra_state_attribute_names"]
            )

            info["zha_lib_entities"][platform].append(state_dict)

        topology = self.gateway.application_controller.topology
        info["neighbors"] = [
            {
                "device_type": neighbor.device_type.name,
                "rx_on_when_idle": neighbor.rx_on_when_idle.name,
                "relationship": neighbor.relationship.name,
                "extended_pan_id": str(neighbor.extended_pan_id),
                "ieee": str(neighbor.ieee),
                "nwk": str(neighbor.nwk),
                "permit_joining": neighbor.permit_joining.name,
                "depth": neighbor.depth,
                "lqi": neighbor.lqi,
            }
            for neighbor in topology.neighbors[self.device.ieee]
        ]

        info["routes"] = [
            {
                "dest_nwk": str(route.DstNWK),
                "route_status": str(route.RouteStatus.name),
                "memory_constrained": bool(route.MemoryConstrained),
                "many_to_one": bool(route.ManyToOne),
                "route_record_required": bool(route.RouteRecordRequired),
                "next_hop": str(route.NextHop),
            }
            for route in topology.routes[self.device.ieee]
        ]

        return info


class CoordinatorDevice(Device):
    """ZHA wrapper for the active coordinator device."""

    def discover_entities(self) -> Iterator[BaseEntity]:
        """Yield counter sensors for the active coordinator."""
        state = self.gateway.application_controller.state
        for counter_groups in (
            "counters",
            "broadcast_counters",
            "device_counters",
            "group_counters",
        ):
            for counter_group, counters in getattr(state, counter_groups).items():
                for counter in counters:
                    yield sensor.DeviceCounterSensor(
                        zha_device=self,
                        counter_groups=counter_groups,
                        counter_group=counter_group,
                        counter=counter,
                    )

                    _LOGGER.debug(
                        "'%s' platform -> '%s' using %s",
                        Platform.SENSOR,
                        sensor.DeviceCounterSensor.__name__,
                        f"counter groups[{counter_groups}] counter group[{counter_group}] counter[{counter}]",
                    )
