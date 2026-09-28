"""Valves on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from zigpy import types as t
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.general import OnOff
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.helpers import safe_read
from zha.application.platforms import (
    AttrConfig,
    BaseEntityState,
    ClusterConfig,
    PlatformEntity,
)
from zha.application.platforms.valve.const import ValveDeviceClass, ValveEntityFeature
from zha.exceptions import ZHAException

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


@dataclasses.dataclass(frozen=True, kw_only=True)
class ValveState(BaseEntityState):
    """State for valve entities."""

    reports_position: bool
    current_position: int | None
    is_opening: bool | None
    is_closing: bool | None
    is_closed: bool | None
    auto_close_at: datetime | None
    supported_features: ValveEntityFeature


class BaseValve(PlatformEntity, ABC):
    """Abstract base class for ZHA valves."""

    PLATFORM = Platform.VALVE

    _attr_device_class: ValveDeviceClass | None = None
    _attr_reports_position: bool = False
    _attr_supported_features: ValveEntityFeature = (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )

    @property
    def state(self) -> ValveState:
        """Return the state of the valve."""
        return ValveState(
            **super().state.__dict__,
            reports_position=self.reports_position,
            current_position=self.current_valve_position,
            is_opening=self.is_opening,
            is_closing=self.is_closing,
            is_closed=self.is_closed,
            auto_close_at=self.auto_close_at,
            supported_features=self.supported_features,
        )

    @property
    def supported_features(self) -> ValveEntityFeature:
        """Return supported features."""
        return self._attr_supported_features

    @property
    def reports_position(self) -> bool:
        """Return True if the valve reports its position."""
        return self._attr_reports_position

    @property
    def current_valve_position(self) -> int | None:
        """Return the current position of the valve: 0 is closed, 100 is open."""
        return None

    @property
    def is_opening(self) -> bool | None:
        """Return if the valve is opening."""
        return None

    @property
    def is_closing(self) -> bool | None:
        """Return if the valve is closing."""
        return None

    @property
    @abstractmethod
    def is_closed(self) -> bool | None:
        """Return if the valve is closed."""

    @property
    def auto_close_at(self) -> datetime | None:
        """Return when the valve will close by itself after a timed open."""
        return None

    @abstractmethod
    async def async_open_valve(self) -> None:
        """Open the valve."""

    @abstractmethod
    async def async_close_valve(self) -> None:
        """Close the valve."""

    async def async_open_valve_for(self, duration: timedelta) -> None:
        """Open the valve and close it after a duration."""
        raise NotImplementedError

    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""
        raise NotImplementedError

    async def async_stop_valve(self) -> None:
        """Stop the valve."""
        raise NotImplementedError


class OnOffValve(BaseValve):
    """Valve backed by the On/Off cluster."""

    _attr_supported_features = (
        ValveEntityFeature.OPEN
        | ValveEntityFeature.CLOSE
        | ValveEntityFeature.OPEN_TIMED
    )

    _server_cluster_config = {
        OnOff.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                OnOff.AttributeDefs.on_off: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                OnOff.AttributeDefs.on_time: AttrConfig(read_on_startup=False),
            },
        ),
    }

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the valve."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._auto_close_at: datetime | None = None

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

    @property
    def is_closed(self) -> bool | None:
        """Return if the valve is closed."""
        value = self._cluster.get(OnOff.AttributeDefs.on_off.name)
        if value is None:
            return None
        return not value

    @property
    def auto_close_at(self) -> datetime | None:
        """Return when the valve will close by itself after a timed open."""
        return self._auto_close_at

    async def async_open_valve(self) -> None:
        """Open the valve."""
        # Per the ZCL, `on` does not cancel a running `on_with_timed_off` timer
        result = await self._cluster.on()
        if result[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to open: {result[1]}")
        self._cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.true)
        self.maybe_emit_state_changed_event()

    async def async_close_valve(self) -> None:
        """Close the valve."""
        result = await self._cluster.off()
        if result[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to close: {result[1]}")
        self._auto_close_at = None
        self._cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.false)
        self.maybe_emit_state_changed_event()

    async def async_open_valve_for(self, duration: timedelta) -> None:
        """Open the valve and close it after a duration."""
        result = await self._cluster.on_with_timed_off(
            on_off_control=0,
            on_time=round(duration.total_seconds() * 10),
            off_wait_time=0,
        )
        if result[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to open: {result[1]}")

        # The device keeps the longer of the running and the new on time
        auto_close_at = datetime.now(UTC) + duration
        if self._auto_close_at is not None:
            auto_close_at = max(auto_close_at, self._auto_close_at)

        self._auto_close_at = auto_close_at
        self._cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.true)
        self.maybe_emit_state_changed_event()

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle state update from the On/Off cluster."""
        if event.attribute_id == OnOff.AttributeDefs.on_off.id:
            if not event.value:
                self._auto_close_at = None
        elif event.attribute_id == OnOff.AttributeDefs.on_time.id:
            on_time = cast(t.uint16_t, event.value)

            # 0 and 0xFFFF mean that no timer is running
            if on_time in (0x0000, 0xFFFF):
                self._auto_close_at = None
            else:
                self._auto_close_at = datetime.now(UTC) + timedelta(
                    seconds=on_time / 10
                )
        else:
            return

        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Poll the valve state and its remaining on time."""
        await safe_read(
            self._cluster,
            [OnOff.AttributeDefs.on_off.name, OnOff.AttributeDefs.on_time.name],
            allow_cache=False,
            only_cache=False,
        )
