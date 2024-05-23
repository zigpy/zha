"""Support for the ZHA device tracker platform."""

from __future__ import annotations

from enum import StrEnum
import functools
import time
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.general import PowerConfiguration

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.sensor import Battery
from zha.application.registries import PLATFORM_ENTITIES
from zha.decorators import periodic
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_POWER_CONFIGURATION,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(
    PLATFORM_ENTITIES.strict_match, Platform.DEVICE_TRACKER
)


class SourceType(StrEnum):
    """Source type for device trackers."""

    GPS = "gps"
    ROUTER = "router"
    BLUETOOTH = "bluetooth"
    BLUETOOTH_LE = "bluetooth_le"


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_POWER_CONFIGURATION)
class DeviceScannerEntity(PlatformEntity):
    """Represent a tracked device."""

    PLATFORM = Platform.DEVICE_TRACKER

    _attr_should_poll = True  # BaseZhaEntity defaults to False
    _attr_fallback_name: str = "Device scanner"
    __polling_interval: int

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ):
        """Initialize the ZHA device tracker."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._battery_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_POWER_CONFIGURATION
        )
        self._connected: bool = False
        self._keepalive_interval: int = 60
        self._should_poll: bool = True
        self._battery_level: float | None = None
        self._battery_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )
        self._tracked_tasks.append(
            device.gateway.async_create_background_task(
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
    def state(self) -> dict[str, Any]:
        """Return the state of the device."""
        response = super().state
        response.update(
            {
                "connected": self._connected,
                "battery_level": self._battery_level,
            }
        )
        return response

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

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle tracking."""
        if (
            event.attribute_name
            != PowerConfiguration.AttributeDefs.battery_percentage_remaining.name
        ):
            return
        self.debug("battery_percentage_remaining updated: %s", event.attribute_value)
        self._connected = True
        self._battery_level = Battery.formatter(event.attribute_value)
        self.maybe_emit_state_changed_event()
