"""Valves on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
import dataclasses

from zha.application import Platform
from zha.application.platforms import BaseEntityState, PlatformEntity
from zha.application.platforms.valve.const import ValveDeviceClass, ValveEntityFeature


@dataclasses.dataclass(frozen=True, kw_only=True)
class ValveEntityState(BaseEntityState):
    """State for valve entities."""

    reports_position: bool
    current_position: int | None
    is_opening: bool | None
    is_closing: bool | None
    is_closed: bool | None
    supported_features: ValveEntityFeature


class BaseValve(PlatformEntity, ABC):
    """Abstract base class for ZHA valves."""

    PLATFORM = Platform.VALVE

    _attr_primary_weight = 10
    _attr_device_class: ValveDeviceClass | None = None
    _attr_reports_position: bool = False
    _attr_supported_features: ValveEntityFeature = (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )

    @property
    def state(self) -> ValveEntityState:
        """Return the state of the valve."""
        return ValveEntityState(
            **super().state.__dict__,
            reports_position=self.reports_position,
            current_position=self.current_valve_position,
            is_opening=self.is_opening,
            is_closing=self.is_closing,
            is_closed=self.is_closed,
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

    @abstractmethod
    async def async_open_valve(self) -> None:
        """Open the valve."""

    @abstractmethod
    async def async_close_valve(self) -> None:
        """Close the valve."""

    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""
        raise NotImplementedError

    async def async_stop_valve(self) -> None:
        """Stop the valve."""
        raise NotImplementedError
