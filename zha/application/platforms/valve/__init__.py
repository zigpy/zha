"""Valves on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, cast

from zigpy.zcl.clusters.general import OnOff
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import (
    BaseEntity,
    ClusterHandlerMatch,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)
from zha.application.platforms.valve.const import (
    ATTR_CURRENT_POSITION,
    ValveEntityFeature,
    ValveState,
)
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_LEVEL,
    CLUSTER_HANDLER_LEVEL_CHANGED,
    CLUSTER_HANDLER_ON_OFF,
)
from zha.zigbee.cluster_handlers.general import (
    LevelChangeEvent,
    LevelControlClusterHandler,
    OnOffClusterHandler,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


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


@register_entity(OnOff.cluster_id)
class Valve(PlatformEntity, BaseValve):
    """Representation of a ZHA valve."""

    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    _cluster_handler_match = ClusterHandlerMatch(
        cluster_handlers=frozenset({CLUSTER_HANDLER_ON_OFF}),
        optional_cluster_handlers=frozenset({CLUSTER_HANDLER_LEVEL}),
        # Keep valve as opt-in via platform override.
        feature_priority=(PlatformFeatureGroup.GENERIC_OPEN_CLOSE, -2),
    )

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the valve."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._on_off_cluster_handler: OnOffClusterHandler = cast(
            OnOffClusterHandler, self.cluster_handlers[CLUSTER_HANDLER_ON_OFF]
        )
        self._level_cluster_handler: LevelControlClusterHandler | None = cast(
            LevelControlClusterHandler | None,
            self.cluster_handlers.get(CLUSTER_HANDLER_LEVEL),
        )

        if self._level_cluster_handler is not None:
            self._attr_supported_features |= (
                ValveEntityFeature.SET_POSITION | ValveEntityFeature.STOP
            )

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._on_remove_callbacks.append(
            self._on_off_cluster_handler.on_event(
                CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
                self.handle_cluster_handler_attribute_updated,
            )
        )

        if self._level_cluster_handler is not None:
            self._on_remove_callbacks.append(
                self._level_cluster_handler.on_event(
                    CLUSTER_HANDLER_LEVEL_CHANGED,
                    self.handle_cluster_handler_set_level,
                )
            )

    @property
    def reports_position(self) -> bool:
        """Return if the valve reports position."""
        return self._level_cluster_handler is not None

    @property
    def current_valve_position(self) -> int | None:
        """Return current valve position."""
        if self._level_cluster_handler is None:
            return None
        return self._zcl_level_to_ha_position(self._level_cluster_handler.current_level)

    @property
    def is_closed(self) -> bool | None:
        """Return if the valve is closed."""
        if self.reports_position:
            if (position := self.current_valve_position) is None:
                return None
            return position == 0

        if self._on_off_cluster_handler.on_off is None:
            return None
        return not self._on_off_cluster_handler.on_off

    @property
    def is_opening(self) -> bool | None:
        """Return if the valve is opening."""
        return None

    @property
    def is_closing(self) -> bool | None:
        """Return if the valve is closing."""
        return None

    async def async_open_valve(self) -> None:
        """Open the valve."""
        await self._on_off_cluster_handler.turn_on()
        self.maybe_emit_state_changed_event()

    async def async_close_valve(self) -> None:
        """Close the valve."""
        await self._on_off_cluster_handler.turn_off()
        self.maybe_emit_state_changed_event()

    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""
        if self._level_cluster_handler is None:
            if position <= 0:
                await self.async_close_valve()
            else:
                await self.async_open_valve()
            return

        res = await self._level_cluster_handler.move_to_level_with_on_off(
            self._ha_position_to_zcl_level(position), 1
        )
        if res[1] != Status.SUCCESS:
            raise ZHAException(f"Failed to set valve position: {res[1]}")

        self.maybe_emit_state_changed_event()

    async def async_stop_valve(self) -> None:
        """Stop the valve."""
        if self._level_cluster_handler is None:
            return

        res = await self._level_cluster_handler.stop()
        if res[1] != Status.SUCCESS:
            raise ZHAException(f"Failed to stop valve: {res[1]}")

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state update from cluster handler."""
        if event.attribute_name == OnOff.AttributeDefs.on_off.name:
            self.maybe_emit_state_changed_event()

    def handle_cluster_handler_set_level(self, event: LevelChangeEvent) -> None:
        """Handle state update from level cluster handler."""
        self.maybe_emit_state_changed_event()

    @staticmethod
    def _ha_position_to_zcl_level(position: int) -> int:
        """Convert the HA position to the ZCL level range."""
        return round(position * 255 / 100)

    @staticmethod
    def _zcl_level_to_ha_position(level: int | None) -> int | None:
        """Convert the ZCL level to the HA position range."""
        if level is None:
            return None
        level = max(0, min(255, level))
        return round(level * 100 / 255)
