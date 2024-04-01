"""Device for Zigbee Home Automation."""

# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
import logging
import time
from typing import TYPE_CHECKING, Any, Final, Self

from zigpy.device import Device as ZigpyDevice
import zigpy.exceptions
from zigpy.profiles import PROFILES
import zigpy.quirks
from zigpy.quirks.v2 import CustomDeviceV2
from zigpy.types import uint1_t, uint8_t, uint16_t
from zigpy.types.named import EUI64, NWK, ExtendedPanId
from zigpy.zcl.clusters import Cluster
from zigpy.zcl.clusters.general import Groups, Identify
from zigpy.zcl.foundation import (
    Status as ZclStatus,
    WriteAttributesResponse,
    ZCLCommandDef,
)
import zigpy.zdo.types as zdo_types
from zigpy.zdo.types import RouteStatus, _NeighborEnums

from zha.application import discovery
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
    CONF_CONSIDER_UNAVAILABLE_BATTERY,
    CONF_CONSIDER_UNAVAILABLE_MAINS,
    CONF_DEFAULT_CONSIDER_UNAVAILABLE_BATTERY,
    CONF_DEFAULT_CONSIDER_UNAVAILABLE_MAINS,
    CONF_ENABLE_IDENTIFY_ON_JOIN,
    POWER_BATTERY_OR_UNKNOWN,
    POWER_MAINS_POWERED,
    UNKNOWN,
    UNKNOWN_MANUFACTURER,
    UNKNOWN_MODEL,
    ZHA_CLUSTER_HANDLER_CFG_DONE,
    ZHA_CLUSTER_HANDLER_MSG,
    ZHA_EVENT,
    ZHA_OPTIONS,
)
from zha.application.helpers import async_get_zha_config_value, convert_to_zcl_values
from zha.application.platforms import PlatformEntity, PlatformEntityInfo
from zha.event import EventBase
from zha.exceptions import ZHAException
from zha.mixins import LogMixin
from zha.zigbee.cluster_handlers import ClusterHandler, ZDOClusterHandler
from zha.zigbee.endpoint import Endpoint

if TYPE_CHECKING:
    from zha.application.gateway import Gateway

_LOGGER = logging.getLogger(__name__)
_UPDATE_ALIVE_INTERVAL = (60, 90)
_CHECKIN_GRACE_PERIODS = 2


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
class ClusterHandlerConfigurationComplete:
    """Event generated when all cluster handlers are configured."""

    device_ieee: EUI64
    unique_id: str
    event_type: Final[str] = ZHA_CLUSTER_HANDLER_MSG
    event: Final[str] = ZHA_CLUSTER_HANDLER_CFG_DONE


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
    quirk_id: str | None
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

    device_type: _NeighborEnums.DeviceType
    rx_on_when_idle: _NeighborEnums.RxOnWhenIdle
    relationship: _NeighborEnums.Relationship
    extended_pan_id: ExtendedPanId
    ieee: EUI64
    nwk: NWK
    permit_joining: _NeighborEnums.PermitJoins
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
    entities: dict[str, PlatformEntityInfo]
    neighbors: list[NeighborInfo]
    routes: list[RouteInfo]
    endpoint_names: list[EndpointNameInfo]


class Device(LogMixin, EventBase):
    """ZHA Zigbee device object."""

    _ha_device_id: str

    def __init__(
        self,
        zigpy_device: zigpy.device.Device,
        _gateway: Gateway,
    ) -> None:
        """Initialize the gateway."""
        super().__init__()
        self._gateway: Gateway = _gateway
        self._zigpy_device: ZigpyDevice = zigpy_device
        self.quirk_applied: bool = isinstance(
            self._zigpy_device, zigpy.quirks.CustomDevice
        )
        self.quirk_class: str = (
            f"{self._zigpy_device.__class__.__module__}."
            f"{self._zigpy_device.__class__.__name__}"
        )
        self.quirk_id: str | None = getattr(self._zigpy_device, ATTR_QUIRK_ID, None)
        self._power_config_ch: ClusterHandler | None = None
        self._identify_ch: ClusterHandler | None = None
        self._basic_ch: ClusterHandler | None = None
        self._sw_build_id: int | None = None

        if self.is_mains_powered:
            self.consider_unavailable_time: int = async_get_zha_config_value(
                self._gateway.config,
                ZHA_OPTIONS,
                CONF_CONSIDER_UNAVAILABLE_MAINS,
                CONF_DEFAULT_CONSIDER_UNAVAILABLE_MAINS,
            )
        else:
            self.consider_unavailable_time = async_get_zha_config_value(
                self._gateway.config,
                ZHA_OPTIONS,
                CONF_CONSIDER_UNAVAILABLE_BATTERY,
                CONF_DEFAULT_CONSIDER_UNAVAILABLE_BATTERY,
            )
        self._available: bool = self.is_coordinator or (
            self.last_seen is not None
            and time.time() - self.last_seen < self.consider_unavailable_time
        )
        self._checkins_missed_count: int = 0
        self._on_network: bool = False

        self._platform_entities: dict[str, PlatformEntity] = {}
        self.semaphore: asyncio.Semaphore = asyncio.Semaphore(3)
        self._tracked_tasks: list[asyncio.Task] = []
        self._zdo_handler: ZDOClusterHandler = ZDOClusterHandler(self)
        self.status: DeviceStatus = DeviceStatus.CREATED

        self._endpoints: dict[int, Endpoint] = {}
        for ep_id, endpoint in zigpy_device.endpoints.items():
            if ep_id != 0:
                self._endpoints[ep_id] = Endpoint.new(endpoint, self)

    @cached_property
    def device(self) -> zigpy.device.Device:
        """Return underlying Zigpy device."""
        return self._zigpy_device

    @cached_property
    def name(self) -> str:
        """Return device name."""
        return f"{self.manufacturer} {self.model}"

    @cached_property
    def ieee(self) -> EUI64:
        """Return ieee address for device."""
        return self._zigpy_device.ieee

    @cached_property
    def manufacturer(self) -> str:
        """Return manufacturer for device."""
        if self._zigpy_device.manufacturer is None:
            return UNKNOWN_MANUFACTURER
        return self._zigpy_device.manufacturer

    @cached_property
    def model(self) -> str:
        """Return model for device."""
        if self._zigpy_device.model is None:
            return UNKNOWN_MODEL
        return self._zigpy_device.model

    @cached_property
    def manufacturer_code(self) -> int | None:
        """Return the manufacturer code for the device."""
        if self._zigpy_device.node_desc is None:
            return None

        return self._zigpy_device.node_desc.manufacturer_code

    @cached_property
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
        return self.is_coordinator or (
            self.available and bool(self.async_get_groupable_endpoints())
        )

    @cached_property
    def skip_configuration(self) -> bool:
        """Return true if the device should not issue configuration related commands."""
        return self._zigpy_device.skip_configuration or bool(self.is_coordinator)

    @cached_property
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
        return get_device_automation_triggers(self._zigpy_device)

    @property
    def available(self):
        """Return True if device is available."""
        return self._available and self.on_network

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
        self._on_network = new_on_network
        self.update_available(new_on_network)

    @property
    def power_configuration_ch(self) -> ClusterHandler | None:
        """Return power configuration cluster handler."""
        return self._power_config_ch

    @power_configuration_ch.setter
    def power_configuration_ch(self, cluster_handler: ClusterHandler) -> None:
        """Power configuration cluster handler setter."""
        if self._power_config_ch is None:
            self._power_config_ch = cluster_handler

    @property
    def basic_ch(self) -> ClusterHandler | None:
        """Return basic cluster handler."""
        return self._basic_ch

    @basic_ch.setter
    def basic_ch(self, cluster_handler: ClusterHandler) -> None:
        """Set the basic cluster handler."""
        if self._basic_ch is None:
            self._basic_ch = cluster_handler

    @property
    def identify_ch(self) -> ClusterHandler | None:
        """Return power configuration cluster handler."""
        return self._identify_ch

    @identify_ch.setter
    def identify_ch(self, cluster_handler: ClusterHandler) -> None:
        """Power configuration cluster handler setter."""
        if self._identify_ch is None:
            self._identify_ch = cluster_handler

    @cached_property
    def zdo_cluster_handler(self) -> ZDOClusterHandler:
        """Return ZDO cluster handler."""
        return self._zdo_handler

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
    def sw_version(self) -> str | None:
        """Return the software version for this device."""
        return self._sw_build_id

    @property
    def platform_entities(self) -> dict[str, PlatformEntity]:
        """Return the platform entities for this device."""
        return self._platform_entities

    def get_platform_entity(self, unique_id: str) -> PlatformEntity:
        """Get a platform entity by unique id."""
        entity = self._platform_entities.get(unique_id)
        if entity is None:
            raise ValueError(f"Entity {unique_id} not found")
        return entity

    @classmethod
    def new(
        cls,
        zigpy_dev: zigpy.device.Device,
        gateway: Gateway,
    ) -> Self:
        """Create new device."""
        zha_dev = cls(zigpy_dev, gateway)
        # pylint: disable=pointless-string-statement
        """TODO verify
        zha_dev.unsubs.append(
            async_dispatcher_connect(
                hass,
                SIGNAL_UPDATE_DEVICE.format(str(zha_dev.ieee)),
                zha_dev.async_update_sw_build_id,
            )
        )
        """
        discovery.DEVICE_PROBE.discover_device_entities(zha_dev)
        return zha_dev

    def async_update_sw_build_id(self, sw_version: int) -> None:
        """Update device sw version."""
        self._sw_build_id = sw_version

    async def _check_available(self, *_: Any) -> None:
        # don't flip the availability state of the coordinator
        if self.is_coordinator:
            return
        if not self._on_network:
            self.debug("Device is not on the network, marking unavailable")
            self.update_available(False)
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
            if not self.basic_ch:
                self.debug("does not have a mandatory basic cluster")
                self.update_available(False)
                return
            res = await self.basic_ch.get_attribute_value(
                ATTR_MANUFACTURER, from_cache=False
            )
            if res is not None:
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
            self.emit_zha_event(
                {
                    "device_event_type": "device_offline",
                },
            )

    def emit_zha_event(self, event_data: dict[str, str | int]) -> None:  # pylint: disable=unused-argument
        """Relay events to hass."""
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
            quirk_id=self.quirk_id,
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
                unique_id: platform_entity.info_object
                for unique_id, platform_entity in self.platform_entities.items()
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
        should_identify = async_get_zha_config_value(
            self._gateway.config,
            ZHA_OPTIONS,
            CONF_ENABLE_IDENTIFY_ON_JOIN,
            True,
        )
        self.debug("started configuration")
        await self._zdo_handler.async_configure()
        self._zdo_handler.debug("'async_configure' stage succeeded")
        await asyncio.gather(
            *(endpoint.async_configure() for endpoint in self._endpoints.values())
        )
        if isinstance(self._zigpy_device, CustomDeviceV2):
            self.debug("applying quirks v2 custom device configuration")
            await self._zigpy_device.apply_custom_configuration()

        self.emit(
            ZHA_CLUSTER_HANDLER_CFG_DONE,
            ClusterHandlerConfigurationComplete(
                device_ieee=self.ieee,
                unique_id=self.ieee,
            ),
        )

        self.debug("completed configuration")

        if (
            should_identify
            and self.identify_ch is not None
            and not self.skip_configuration
        ):
            await self.identify_ch.trigger_effect(
                effect_id=Identify.EffectIdentifier.Okay,
                effect_variant=Identify.EffectVariant.Default,
            )

    async def async_initialize(self, from_cache: bool = False) -> None:
        """Initialize cluster handlers."""
        self.debug("started initialization")
        await self._zdo_handler.async_initialize(from_cache)
        self._zdo_handler.debug("'async_initialize' stage succeeded")

        # We intentionally do not use `gather` here! This is so that if, for example,
        # three `device.async_initialize()`s are spawned, only three concurrent requests
        # will ever be in flight at once. Startup concurrency is managed at the device
        # level.
        for endpoint in self._endpoints.values():
            try:
                await endpoint.async_initialize(from_cache)
            except Exception:  # pylint: disable=broad-exception-caught
                self.debug("Failed to initialize endpoint", exc_info=True)

        self.debug("power source: %s", self.power_source)
        self.status = DeviceStatus.INITIALIZED
        self.debug("completed initialization")

    async def on_remove(self) -> None:
        """Cancel tasks this device owns."""
        tasks = [t for t in self._tracked_tasks if not (t.done() or t.cancelled())]
        for task in tasks:
            self.debug("Cancelling task: %s", task)
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)
        for platform_entity in self._platform_entities.values():
            await platform_entity.on_remove()

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
        cluster = self.async_get_cluster(endpoint_id, cluster_id, cluster_type)
        if cluster is None:
            return None
        return cluster.attributes

    def async_get_cluster_commands(
        self, endpoint_id, cluster_id, cluster_type=CLUSTER_TYPE_IN
    ):
        """Get zigbee commands for specified cluster."""
        cluster = self.async_get_cluster(endpoint_id, cluster_id, cluster_type)
        if cluster is None:
            return None
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
        manufacturer: int | None = None,
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
        if response[1] is not ZclStatus.SUCCESS:
            raise ZHAException(
                f"Failed to issue cluster command with status: {response[1]}"
            )

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
