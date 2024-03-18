"""Support for the ZHA platform."""

from __future__ import annotations

import asyncio
from enum import StrEnum
import functools
import time
from typing import TYPE_CHECKING

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.sensor import Battery
from zha.application.registries import PLATFORM_ENTITIES
from zha.decorators import periodic
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_POWER_CONFIGURATION,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
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
class ZHADeviceScannerEntity(PlatformEntity):
    """Represent a tracked device."""

    _attr_should_poll = True  # BaseZhaEntity defaults to False
    _attr_name: str = "Device scanner"

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
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
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )
        self._tracked_tasks.append(
            device.gateway.async_create_background_task(
                self._refresh(),
                name=f"device_tracker_refresh_{self.unique_id}",
                eager_start=True,
            )
        )

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
        self.maybe_send_state_changed_event()

    @periodic((30, 45))
    async def _refresh(self) -> None:
        """Refresh the state of the device tracker."""
        await self.async_update()

    @property
    def is_connected(self):
        """Return true if the device is connected to the network."""
        return self._connected

    @property
    def source_type(self) -> SourceType:
        """Return the source type, eg gps or router, of the device."""
        return SourceType.ROUTER

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle tracking."""
        if event.attribute_name != "battery_percentage_remaining":
            return
        self.debug("battery_percentage_remaining updated: %s", event.attribute_value)
        self._connected = True
        self._battery_level = Battery.formatter(event.attribute_value)
        self.maybe_send_state_changed_event()

    @property
    def battery_level(self):
        """Return the battery level of the device.

        Percentage from 0-100.
        """
        return self._battery_level

    def get_state(self) -> dict:
        """Return the state of the device."""
        response = super().get_state()
        response.update(
            {
                "connected": self._connected,
                "battery_level": self._battery_level,
            }
        )
        return response
