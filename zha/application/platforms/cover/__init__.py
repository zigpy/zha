"""Support for Zigbee Home Automation covers."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
from collections import deque
import functools
import logging
from typing import TYPE_CHECKING, Any, cast

from zigpy.zcl.clusters.general import OnOff
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.cover.const import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    POSITION_CLOSED,
    POSITION_OPEN,
    WCT,
    ZCL_TO_COVER_DEVICE_CLASS,
    CoverDeviceClass,
    CoverEntityFeature,
    CoverState,
    WCAttrs,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.closures import WindowCoveringClusterHandler
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_COVER,
    CLUSTER_HANDLER_LEVEL,
    CLUSTER_HANDLER_LEVEL_CHANGED,
    CLUSTER_HANDLER_ON_OFF,
    CLUSTER_HANDLER_SHADE,
)
from zha.zigbee.cluster_handlers.general import LevelChangeEvent

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)

MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.COVER)

# Timeout for device transition state following a position attribute update
DEFAULT_MOVEMENT_TIMEOUT: float = 5

# Upper limit for dynamic timeout
LIFT_MOVEMENT_TIMEOUT_RANGE: float = 300
TILT_MOVEMENT_TIMEOUT_RANGE: float = 30


class BaseCover(PlatformEntity, ABC):
    """Abstract base class for ZHA covers."""

    PLATFORM = Platform.COVER

    _attr_primary_weight = 10

    @property
    @abstractmethod
    def supported_features(self) -> CoverEntityFeature:
        """Return supported features."""

    @property
    @abstractmethod
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed."""

    @property
    @abstractmethod
    def is_opening(self) -> bool | None:
        """Return if the cover is opening or not."""

    @property
    @abstractmethod
    def is_closing(self) -> bool | None:
        """Return if the cover is closing or not."""

    @property
    @abstractmethod
    def current_cover_position(self) -> int | None:
        """Return the current position of ZHA cover.

        In HA, None is unknown, 0 is closed, 100 is fully open.
        """

    @property
    @abstractmethod
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover.

        In HA, None is unknown, 0 is closed, 100 is fully open.
        """

    @abstractmethod
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""

    @abstractmethod
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""

    @abstractmethod
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""

    @abstractmethod
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_COVER)
class Cover(BaseCover):
    """Representation of a ZHA cover."""

    _attr_translation_key: str = "cover"

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Init this cover."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        cluster_handler = self.cluster_handlers.get(CLUSTER_HANDLER_COVER)
        assert cluster_handler

        self._cover_cluster_handler: WindowCoveringClusterHandler = cast(
            WindowCoveringClusterHandler, cluster_handler
        )
        if self._cover_cluster_handler.window_covering_type is not None:
            self._attr_device_class: CoverDeviceClass | None = (
                ZCL_TO_COVER_DEVICE_CLASS.get(
                    self._cover_cluster_handler.window_covering_type
                )
            )
        self._attr_supported_features: CoverEntityFeature = CoverEntityFeature(0)
        self.recompute_capabilities()

        self._target_lift_position: int | None = None
        self._target_tilt_position: int | None = None
        self._lift_state: CoverState | None = None
        self._tilt_state: CoverState | None = None
        self._lift_position_history: deque[int | None] = deque(
            [self.current_cover_position], maxlen=2
        )
        self._tilt_position_history: deque[int | None] = deque(
            [self.current_cover_tilt_position], maxlen=2
        )
        self._loop = asyncio.get_running_loop()
        self._lift_transition_timer: asyncio.TimerHandle | None = None
        self._tilt_transition_timer: asyncio.TimerHandle | None = None

        self._state: CoverState | None = None
        self._determine_cover_state(refresh=True)

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags based on the window covering type."""
        super().recompute_capabilities()
        supported_features = CoverEntityFeature(0)

        # Enable lift features if the window covering type is not tilt only
        if self._cover_cluster_handler.window_covering_type not in (
            WCT.Shutter,
            WCT.Tilt_blind_tilt_only,
        ):
            supported_features |= (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.STOP
                | CoverEntityFeature.SET_POSITION
            )

        # Enable tilt features if the window covering type supports tilt
        if self._cover_cluster_handler.window_covering_type in (
            WCT.Shutter,
            WCT.Tilt_blind_tilt_only,
            WCT.Tilt_blind_tilt_and_lift,
        ):
            supported_features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.STOP_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )

        self._attr_supported_features = supported_features

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._on_remove_callbacks.append(
            self._cover_cluster_handler.on_event(
                CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
                self.handle_cluster_handler_attribute_updated,
            )
        )
        self._on_remove_callbacks.extend(
            (self._clear_lift_transition, self._clear_tilt_transition)
        )

    def restore_external_state_attributes(
        self,
        *,
        state: CoverState | None,
        **kwargs: Any,  # pylint: disable=unused-argument
    ):
        """Restore external state attributes.

        If the state is OPENING or CLOSING, a callback is scheduled
        to determine the final state after the default timeout period.
        """
        if not self._state or state not in (CoverState.OPENING, CoverState.CLOSING):
            return
        if state == CoverState.CLOSING and self.is_closed:
            return
        if (
            state == CoverState.OPENING
            and self.current_cover_position in (100, None)
            and self.current_cover_tilt_position in (100, None)
        ):
            return

        self._state = state
        self._tracked_handles.append(
            self._loop.call_later(
                DEFAULT_MOVEMENT_TIMEOUT,
                functools.partial(self._determine_cover_state, refresh=True),
            )
        )

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Return supported features."""
        return self._attr_supported_features

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the cover."""
        response = super().state
        response.update(
            {
                ATTR_CURRENT_POSITION: self.current_cover_position,
                ATTR_CURRENT_TILT_POSITION: self.current_cover_tilt_position,
                "state": self._state,
                "is_opening": self.is_opening,
                "is_closing": self.is_closing,
                "is_closed": self.is_closed,
            }
        )
        return response

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed."""
        return self._state == CoverState.CLOSED if self._state else None

    @property
    def is_opening(self) -> bool | None:
        """Return if the cover is opening or not."""
        return self._state == CoverState.OPENING if self._state else None

    @property
    def is_closing(self) -> bool | None:
        """Return if the cover is closing or not."""
        return self._state == CoverState.CLOSING if self._state else None

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of ZHA cover.

        In HA None is unknown, 0 is closed, 100 is fully open.
        In ZCL 0 is fully open, 100 is fully closed.
        Keep in mind the values have already been flipped to match HA
        in the WindowCovering cluster handler.
        """
        if not self.supported_features & CoverEntityFeature.OPEN:
            return None
        return self._cover_cluster_handler.current_position_lift_percentage

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover.

        In HA None is unknown, 0 is closed, 100 is fully open.
        In ZCL 0 is fully open, 100 is fully closed.
        Keep in mind the values have already been flipped to match HA
        in the WindowCovering cluster handler.
        """
        if not self.supported_features & CoverEntityFeature.OPEN_TILT:
            return None
        return self._cover_cluster_handler.current_position_tilt_percentage

    @property
    def _previous_cover_position(self) -> int | None:
        """Return the previous position of ZHA cover."""
        return self._lift_position_history[0]

    @property
    def _previous_cover_tilt_position(self) -> int | None:
        """Return the previous tilt position of ZHA cover."""
        return self._tilt_position_history[0]

    @staticmethod
    def _determine_state(
        current: int | None,
        target: int | None,
        previous: int | None,
        is_position_update: bool = False,
        is_transition: bool = False,
    ):
        """Determine cover axis state (lift/tilt).

        Some device update position during movement, others only after stopping.
        When a target is defined the logic aims to mitigate split-brain scenarios
        where a HA command is interrupted by a device button press/physical obstruction.

        Consider previous position and transition status to determine if the cover is moving.
        """
        if current is None:
            return None

        if (
            target is None
            and is_position_update
            and previous is not None
            and previous != current
        ):
            target = POSITION_OPEN if current > previous else POSITION_CLOSED

        if (
            target is not None
            and current != target
            and (
                previous is None
                or not is_position_update
                or not is_transition
                or previous < current < target
                or target < current < previous
            )
        ):
            # The cover is moving
            return CoverState.OPENING if target > current else CoverState.CLOSING

        # The cover is not moving
        return CoverState.OPEN if current > POSITION_CLOSED else CoverState.CLOSED

    def _determine_cover_state(
        self,
        *,
        is_lift_update: bool = False,
        is_tilt_update: bool = False,
        refresh: bool = False,
    ) -> None:
        """Determine the state of the cover entity.

        This considers current state of both the lift and tilt axis.
        """
        if self._lift_state is None or is_lift_update or refresh:
            self._lift_state = self._determine_state(
                self.current_cover_position,
                self._target_lift_position,
                self._previous_cover_position,
                is_lift_update,
                self._lift_transition_timer is not None,
            )
        if self._tilt_state is None or is_tilt_update or refresh:
            self._tilt_state = self._determine_state(
                self.current_cover_tilt_position,
                self._target_tilt_position,
                self._previous_cover_tilt_position,
                is_tilt_update,
                self._tilt_transition_timer is not None,
            )

        _LOGGER.debug(
            "_determine_state: lift=(state: %s, is_position_update: %s, current: %s, target: %s, history: %s), tilt=(state: %s, is_position_update: %s, current: %s, target: %s, history: %s)",
            self._lift_state,
            is_lift_update,
            self.current_cover_position,
            self._target_lift_position,
            self._lift_position_history,
            self._tilt_state,
            is_tilt_update,
            self.current_cover_tilt_position,
            self._target_tilt_position,
            self._tilt_position_history,
        )

        # Clear transition if the cover axis is not moving, else update the timer
        if self._lift_state not in (CoverState.OPENING, CoverState.CLOSING):
            self._clear_lift_transition()
        elif is_lift_update:
            self._start_lift_transition(is_position_update=True)

        if self._tilt_state not in (CoverState.OPENING, CoverState.CLOSING):
            self._clear_tilt_transition()
        elif is_tilt_update:
            self._start_tilt_transition(is_position_update=True)

        # Keep the last direction if either axis is still moving
        if (
            self.is_closing
            and CoverState.CLOSING in (self._lift_state, self._tilt_state)
            or self.is_opening
            and CoverState.OPENING in (self._lift_state, self._tilt_state)
        ):
            self.maybe_emit_state_changed_event()
            return

        # A moving tilt state overrides a static lift state
        if self._tilt_state in (
            CoverState.OPENING,
            CoverState.CLOSING,
        ) and self._lift_state in (CoverState.CLOSED, CoverState.OPEN):
            self._state = self._tilt_state
        else:
            self._state = self._lift_state or self._tilt_state
        self.maybe_emit_state_changed_event()

    def _set_lift_transition_target(self, target: int) -> None:
        """Set target position for the tilt transition."""
        self._clear_lift_transition()
        self._target_lift_position = target

    def _set_tilt_transition_target(self, target: int) -> None:
        """Set target position for the tilt transition."""
        self._clear_tilt_transition()
        self._target_tilt_position = target

    def _start_lift_transition(self, is_position_update: bool = False) -> None:
        """Start the lift transition."""
        if self._lift_transition_timer:
            self._lift_transition_timer.cancel()
            self._lift_transition_timer = None
            transition_update = True
        else:
            transition_update = False

        if (
            self._target_lift_position is None
            or self.current_cover_position is None
            or self._target_lift_position == self.current_cover_position
        ):
            duration = DEFAULT_MOVEMENT_TIMEOUT
        else:
            duration = (
                abs(self._target_lift_position - self.current_cover_position)
                * 0.01
                * LIFT_MOVEMENT_TIMEOUT_RANGE
            )
        if is_position_update:
            duration = min(DEFAULT_MOVEMENT_TIMEOUT, duration)
        assert duration > 0

        if not transition_update:
            _LOGGER.debug("Lift transition started")
        self._lift_transition_timer = self._loop.call_later(
            duration, self._clear_lift_transition, True
        )

    def _start_tilt_transition(self, is_position_update: bool = False) -> None:
        """Start the tilt transition."""
        if self._tilt_transition_timer:
            self._tilt_transition_timer.cancel()
            self._tilt_transition_timer = None
            transition_update = True
        else:
            transition_update = False

        if (
            self._target_tilt_position is None
            or self.current_cover_tilt_position is None
            or self._target_tilt_position == self.current_cover_tilt_position
        ):
            duration = DEFAULT_MOVEMENT_TIMEOUT
        else:
            duration = (
                abs(self._target_tilt_position - self.current_cover_tilt_position)
                * 0.01
                * TILT_MOVEMENT_TIMEOUT_RANGE
            )
        if is_position_update:
            duration = min(DEFAULT_MOVEMENT_TIMEOUT, duration)
        assert duration > 0

        if not transition_update:
            _LOGGER.debug("Tilt transition started")
        self._tilt_transition_timer = self._loop.call_later(
            duration, self._clear_tilt_transition, True
        )

    def _clear_lift_transition(self, determine_state: bool = False) -> None:
        """Clear the lift transition."""
        self._target_lift_position = None

        if self._lift_transition_timer:
            self._lift_transition_timer.cancel()
            self._lift_transition_timer = None
            _LOGGER.debug("Lift transition cleared")

        if not determine_state:
            return
        self._determine_cover_state(refresh=True)

    def _clear_tilt_transition(self, determine_state: bool = False) -> None:
        """Clear the tilt transition."""
        self._target_tilt_position = None

        if self._tilt_transition_timer:
            self._tilt_transition_timer.cancel()
            self._tilt_transition_timer = None
            _LOGGER.debug("Tilt transition cleared")

        if not determine_state:
            return
        self._determine_cover_state(refresh=True)

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle position updates from cluster handler.

        The previous position is retained for use in state determination.
        """
        _LOGGER.debug("handle_cluster_handler_attribute_updated=%s", event)
        if event.attribute_id == WCAttrs.current_position_lift_percentage.id:
            self._lift_position_history.append(self.current_cover_position)
            self._determine_cover_state(is_lift_update=True)
        elif event.attribute_id == WCAttrs.current_position_tilt_percentage.id:
            self._tilt_position_history.append(self.current_cover_tilt_position)
            self._determine_cover_state(is_tilt_update=True)

    def async_update_state(self, state):
        """Handle state update from HA operations below."""
        _LOGGER.debug("async_update_state=%s", state)
        self._state = state
        self._lift_state = None
        self._tilt_state = None
        self.maybe_emit_state_changed_event()

    async def async_open_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Open the cover."""
        self._set_lift_transition_target(POSITION_OPEN)
        res = await self._cover_cluster_handler.up_open()
        if res[1] is not Status.SUCCESS:
            self._clear_lift_transition()
            raise ZHAException(f"Failed to open cover: {res[1]}")

        if self.current_cover_position != POSITION_OPEN:
            self.async_update_state(CoverState.OPENING)
        self._start_lift_transition()

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Open the cover tilt."""
        self._set_tilt_transition_target(POSITION_OPEN)
        res = await self._cover_cluster_handler.go_to_tilt_percentage(
            self._ha_position_to_zcl(POSITION_OPEN)
        )
        if res[1] is not Status.SUCCESS:
            self._clear_tilt_transition()
            raise ZHAException(f"Failed to open cover tilt: {res[1]}")

        if self.current_cover_tilt_position != POSITION_OPEN:
            self.async_update_state(CoverState.OPENING)
        self._start_tilt_transition()

    async def async_close_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Close the cover."""
        self._set_lift_transition_target(POSITION_CLOSED)
        res = await self._cover_cluster_handler.down_close()
        if res[1] is not Status.SUCCESS:
            self._clear_lift_transition()
            raise ZHAException(f"Failed to close cover: {res[1]}")

        if self.current_cover_position != POSITION_CLOSED:
            self.async_update_state(CoverState.CLOSING)
        self._start_lift_transition()

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Close the cover tilt."""
        self._set_tilt_transition_target(POSITION_CLOSED)
        res = await self._cover_cluster_handler.go_to_tilt_percentage(
            self._ha_position_to_zcl(POSITION_CLOSED)
        )
        if res[1] is not Status.SUCCESS:
            self._clear_tilt_transition()
            raise ZHAException(f"Failed to close cover tilt: {res[1]}")

        if self.current_cover_tilt_position != POSITION_CLOSED:
            self.async_update_state(CoverState.CLOSING)
        self._start_tilt_transition()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        assert self.current_cover_position is not None
        target_position = kwargs[ATTR_POSITION]
        assert target_position is not None

        self._set_lift_transition_target(target_position)
        res = await self._cover_cluster_handler.go_to_lift_percentage(
            self._ha_position_to_zcl(target_position)
        )
        if res[1] is not Status.SUCCESS:
            self._clear_lift_transition()
            raise ZHAException(f"Failed to set cover position: {res[1]}")

        if target_position != self.current_cover_position:
            self.async_update_state(
                CoverState.CLOSING
                if target_position < self.current_cover_position
                else CoverState.OPENING
            )
        self._start_lift_transition()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move the cover tilt to a specific position."""
        assert self.current_cover_tilt_position is not None
        target_position = kwargs[ATTR_TILT_POSITION]
        assert target_position is not None

        self._set_tilt_transition_target(target_position)
        res = await self._cover_cluster_handler.go_to_tilt_percentage(
            self._ha_position_to_zcl(target_position)
        )
        if res[1] is not Status.SUCCESS:
            self._clear_tilt_transition()
            raise ZHAException(f"Failed to set cover tilt position: {res[1]}")

        if target_position != self.current_cover_tilt_position:
            self.async_update_state(
                CoverState.CLOSING
                if target_position < self.current_cover_tilt_position
                else CoverState.OPENING
            )
        self._start_tilt_transition()

    async def async_stop_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Stop the cover.

        Upon receipt of this command the cover stops both lift and tilt movement.
        """
        res = await self._cover_cluster_handler.stop()
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to stop cover: {res[1]}")
        self._clear_lift_transition()
        self._clear_tilt_transition()
        self._determine_cover_state(refresh=True)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the cover tilt.

        This is handled by async_stop_cover because there is no tilt specific command for Zigbee covers.
        """
        await self.async_stop_cover(**kwargs)

    @staticmethod
    def _ha_position_to_zcl(position: int) -> int:
        """Convert the HA position to the ZCL position range.

        In HA None is unknown, 0 is closed, 100 is fully open.
        In ZCL 0 is fully open, 100 is fully closed.
        """
        return 100 - position


@MULTI_MATCH(
    cluster_handler_names={
        CLUSTER_HANDLER_LEVEL,
        CLUSTER_HANDLER_ON_OFF,
        CLUSTER_HANDLER_SHADE,
    }
)
class Shade(BaseCover):
    """ZHA Shade."""

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_translation_key: str = "shade"
    _attr_supported_features: CoverEntityFeature = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the ZHA shade."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._on_off_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_ON_OFF
        ]
        self._level_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_LEVEL
        ]
        self._is_open: bool | None = self._on_off_cluster_handler.on_off
        self._position: int | None = self._zcl_level_to_ha_position(
            self._level_cluster_handler.current_level
        )
        self.recompute_capabilities()

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._on_remove_callbacks.append(
            self._on_off_cluster_handler.on_event(
                CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
                self.handle_cluster_handler_attribute_updated,
            )
        )
        self._on_remove_callbacks.append(
            self._level_cluster_handler.on_event(
                CLUSTER_HANDLER_LEVEL_CHANGED, self.handle_cluster_handler_set_level
            )
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the cover."""
        if (closed := self.is_closed) is None:
            state = None
        else:
            state = CoverState.CLOSED if closed else CoverState.OPEN
        response = super().state
        response.update(
            {
                ATTR_CURRENT_POSITION: self.current_cover_position,
                "is_closed": self.is_closed,
                "state": state,
            }
        )
        return response

    @functools.cached_property
    def supported_features(self) -> CoverEntityFeature:
        """Return supported features."""
        return self._attr_supported_features

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover.

        None is unknown, 0 is closed, 100 is fully open.
        """
        return self._position

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover."""
        return None

    @functools.cached_property
    def is_opening(self) -> bool | None:
        """Return if the cover is opening or not."""
        return None

    @functools.cached_property
    def is_closing(self) -> bool | None:
        """Return if the cover is closing or not."""
        return None

    @property
    def is_closed(self) -> bool | None:
        """Return True if shade is closed."""
        return None if self._is_open is None else not self._is_open

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Set open/closed state."""
        if event.attribute_id == OnOff.AttributeDefs.on_off.id:
            self._is_open = event.attribute_value
            self.maybe_emit_state_changed_event()

    def handle_cluster_handler_set_level(self, event: LevelChangeEvent) -> None:
        """Set the reported position."""
        self._position = self._zcl_level_to_ha_position(event.level)
        self.maybe_emit_state_changed_event()

    async def async_open_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Open the window cover."""
        res = await self._on_off_cluster_handler.on()
        if res[1] != Status.SUCCESS:
            raise ZHAException(f"Failed to open cover: {res[1]}")

        self._is_open = True
        self.maybe_emit_state_changed_event()

    async def async_close_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Close the window cover."""
        res = await self._on_off_cluster_handler.off()
        if res[1] != Status.SUCCESS:
            raise ZHAException(f"Failed to close cover: {res[1]}")

        self._is_open = False
        self.maybe_emit_state_changed_event()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the roller shutter to a specific position."""
        new_pos = kwargs[ATTR_POSITION]
        res = await self._level_cluster_handler.move_to_level_with_on_off(
            self._ha_position_to_zcl_level(new_pos), 1
        )

        if res[1] != Status.SUCCESS:
            raise ZHAException(f"Failed to set cover position: {res[1]}")

        self._position = new_pos
        self.maybe_emit_state_changed_event()

    async def async_stop_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Stop the cover."""
        res = await self._level_cluster_handler.stop()
        if res[1] != Status.SUCCESS:
            raise ZHAException(f"Failed to stop cover: {res[1]}")

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


@MULTI_MATCH(
    cluster_handler_names={CLUSTER_HANDLER_LEVEL, CLUSTER_HANDLER_ON_OFF},
    manufacturers="Keen Home Inc",
)
class KeenVent(Shade):
    """Keen vent cover."""

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_translation_key: str = "keen_vent"

    async def async_open_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Open the cover."""
        position = self._position or 100
        await asyncio.gather(
            self._level_cluster_handler.move_to_level_with_on_off(
                self._ha_position_to_zcl_level(position), 1
            ),
            self._on_off_cluster_handler.on(),
        )

        self._is_open = True
        self._position = position
        self.maybe_emit_state_changed_event()
