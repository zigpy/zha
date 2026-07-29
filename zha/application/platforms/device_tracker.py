"""Support for the ZHA device tracker platform."""

from __future__ import annotations

from abc import ABC, abstractmethod
import dataclasses
from enum import StrEnum
import functools
import time
from typing import TYPE_CHECKING

from zigpy.profiles import zha
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.general import PowerConfiguration

from zha.application import Platform
from zha.application.platforms import (
    AttrConfig,
    BaseEntityState,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    register_entity,
)
from zha.application.platforms.sensor import Battery
from zha.decorators import periodic

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


# TODO: this is a fake device type that is used by a single quirk to match against this
# platform. This needs to be reworked.
SMARTTHINGS_ARRIVAL_SENSOR_DEVICE_TYPE = 0x8000


class SourceType(StrEnum):
    """Source type for device trackers."""

    GPS = "gps"
    ROUTER = "router"
    BLUETOOTH = "bluetooth"
    BLUETOOTH_LE = "bluetooth_le"


@dataclasses.dataclass(frozen=True, kw_only=True)
class DeviceTrackerState(BaseEntityState):
    """State for device tracker entities."""

    connected: bool
    battery_level: float | None


class BaseDeviceTracker(PlatformEntity, ABC):
    """Abstract base class for ZHA device tracker entities."""

    PLATFORM = Platform.DEVICE_TRACKER

    @property
    def state(self) -> DeviceTrackerState:
        """Return the state of the device."""
        return DeviceTrackerState(
            **super().state.__dict__,
            connected=self.is_connected,
            battery_level=self.battery_level,
        )

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return true if the device is connected to the network."""

    @property
    @abstractmethod
    def battery_level(self) -> float | None:
        """Return the battery level of the device."""

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        """Return the source type, eg gps or router, of the device."""


@register_entity(PowerConfiguration.cluster_id)
class DeviceScannerEntity(BaseDeviceTracker):
    """Represent a tracked device."""

    _attr_should_poll = True  # BaseZhaEntity defaults to False
    _attr_fallback_name: str = "Device scanner"
    __polling_interval: int

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({PowerConfiguration.cluster_id}),
        profile_device_types=frozenset(
            {(zha.PROFILE_ID, SMARTTHINGS_ARRIVAL_SENSOR_DEVICE_TYPE)}
        ),
    )

    _server_cluster_config = {
        PowerConfiguration.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                PowerConfiguration.AttributeDefs.battery_voltage: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=3600, max_interval=10800, reportable_change=1
                    ),
                ),
                PowerConfiguration.AttributeDefs.battery_percentage_remaining: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=3600, max_interval=10800, reportable_change=1
                    ),
                ),
                PowerConfiguration.AttributeDefs.battery_size: AttrConfig(
                    read_on_startup=True,
                ),
                PowerConfiguration.AttributeDefs.battery_quantity: AttrConfig(
                    read_on_startup=True,
                ),
            },
        ),
    }

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ):
        """Initialize the ZHA device tracker."""
        super().__init__(
            endpoint=endpoint,
            device=device,
            legacy_discovery_unique_id=f"{endpoint.device.ieee}-{endpoint.id}",
            **kwargs,
        )
        self._cluster = endpoint.zigpy_endpoint.in_clusters[
            PowerConfiguration.cluster_id
        ]
        self._connected: bool = False
        self._keepalive_interval: int = 60
        self._should_poll: bool = True
        self._battery_level: float | None = None

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type, self.handle_attribute_updated
                )
            )

        self._tracked_tasks.append(
            self.device.gateway.async_create_background_task(
                self._refresh(),
                name=f"device_tracker_refresh_{self.unique_id}",
                eager_start=True,
                untracked=True,
            )
        )
        self.debug(
            "started polling with refresh interval of %s",
            getattr(self, "__polling_interval"),
        )

    @property
    def is_connected(self):
        """Return true if the device is connected to the network."""
        return self._connected

    @functools.cached_property
    def source_type(self) -> SourceType:
        """Return the source type, eg gps or router, of the device."""
        return SourceType.ROUTER

    @property
    def battery_level(self):
        """Return the battery level of the device.

        Percentage from 0-100.
        """
        return self._battery_level

    @periodic((30, 45))
    async def _refresh(self) -> None:
        """Refresh the state of the device tracker."""
        await self.async_update()

    async def async_update(self) -> None:
        """Handle polling."""
        if self.device.last_seen is None:
            self._connected = False
        else:
            difference = time.time() - self.device.last_seen
            if difference > self._keepalive_interval:
                self._connected = False
            else:
                self._connected = True
        self.maybe_emit_state_changed_event()

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle tracking."""
        if (
            event.attribute_name
            != PowerConfiguration.AttributeDefs.battery_percentage_remaining.name
        ):
            return
        self.debug("battery_percentage_remaining updated: %s", event.value)
        self._connected = True
        self._battery_level = Battery.formatter(event.value)
        self.maybe_emit_state_changed_event()
