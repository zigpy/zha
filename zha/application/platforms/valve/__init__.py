"""Valves on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from zha.application import Platform
from zha.application.platforms import BaseEntity
from zha.application.platforms.valve.const import (
    ATTR_CURRENT_POSITION,
    ValveEntityFeature,
    ValveState,
)


class BaseValve(BaseEntity, ABC):
    """Abstract base class for ZHA valve entities."""

    PLATFORM = Platform.VALVE

    _attr_supported_features: ValveEntityFeature = ValveEntityFeature(0)
    _attr_translation_key: str = "valve"
    _attr_primary_weight = 10

    @property
    def supported_features(self) -> ValveEntityFeature:
        """Return supported features."""
        return self._attr_supported_features

    @property
    @abstractmethod
    def reports_position(self) -> bool:
        """Return if the valve reports position."""

    @property
    @abstractmethod
    def current_valve_position(self) -> int | None:
        """Return the current valve position."""

    @property
    @abstractmethod
    def is_closed(self) -> bool | None:
        """Return if the valve is closed."""

    @property
    @abstractmethod
    def is_opening(self) -> bool | None:
        """Return if the valve is opening."""

    @property
    @abstractmethod
    def is_closing(self) -> bool | None:
        """Return if the valve is closing."""

    @property
    def valve_state(self) -> ValveState | None:
        """Return the current valve state."""
        if self.is_opening:
            return ValveState.OPENING
        if self.is_closing:
            return ValveState.CLOSING

        if self.reports_position:
            if (position := self.current_valve_position) is None:
                return None

            return ValveState.CLOSED if position == 0 else ValveState.OPEN

        if (is_closed := self.is_closed) is None:
            return None

        return ValveState.CLOSED if is_closed else ValveState.OPEN

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the valve."""
        response = super().state
        response.update(
            {
                ATTR_CURRENT_POSITION: (
                    self.current_valve_position if self.reports_position else None
                ),
                "state": self.valve_state,
                "is_opening": self.is_opening,
                "is_closing": self.is_closing,
                "is_closed": self.is_closed,
            }
        )
        return response

    @abstractmethod
    async def async_open_valve(self) -> None:
        """Open the valve."""

    @abstractmethod
    async def async_close_valve(self) -> None:
        """Close the valve."""

    @abstractmethod
    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""

    @abstractmethod
    async def async_stop_valve(self) -> None:
        """Stop the valve."""
