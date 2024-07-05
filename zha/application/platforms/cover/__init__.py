"""Support for Zigbee Home Automation covers."""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from zigpy.zcl.clusters.general import OnOff
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.cover.const import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    WCT,
    ZCL_TO_COVER_DEVICE_CLASS,
    CoverDeviceClass,
    CoverEntityFeature,
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


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_COVER)
class Cover(PlatformEntity):
    """Representation of a ZHA cover."""

    PLATFORM = Platform.COVER

    _attr_translation_key: str = "cover"
    _attr_extra_state_attribute_names: set[str] = {
        "target_lift_position",
        "target_tilt_position",
    }

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Init this cover."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        cluster_handler = self.cluster_handlers.get(CLUSTER_HANDLER_COVER)
        assert cluster_handler
        self._cover_cluster_handler: WindowCoveringClusterHandler = cast(
            WindowCoveringClusterHandler, cluster_handler
        )
        if self._cover_cluster_handler.window_covering_type:
            self._attr_device_class: CoverDeviceClass | None = (
                ZCL_TO_COVER_DEVICE_CLASS.get(
                    self._cover_cluster_handler.window_covering_type
                )
            )
        self._attr_supported_features: CoverEntityFeature = (
            self._determine_supported_features()
        )
        self._target_lift_position: int | None = None
        self._target_tilt_position: int | None = None
        self._state: str = STATE_OPEN
        self._determine_initial_state()
        self._cover_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the cover."""
        response = super().state
        response.update(
            {
                ATTR_CURRENT_POSITION: self.current_cover_position,
                "state": self._state,
                "is_opening": self.is_opening,
                "is_closing": self.is_closing,
                "is_closed": self.is_closed,
                "target_lift_position": self._target_lift_position,
                "target_tilt_position": self._target_tilt_position,
            }
        )
        return response

    def restore_external_state_attributes(
        self,
        *,
        state: Literal[
            "open", "opening", "closed", "closing"
        ],  # FIXME: why must these be expanded?
        target_lift_position: int | None,
        target_tilt_position: int | None,
    ):
        """Restore external state attributes."""
        self._state = state
        self._target_lift_position = target_lift_position
        self._target_tilt_position = target_tilt_position

    @property
    def is_closed(self) -> bool | None:
        """Return True if the cover is closed.

        In HA None is unknown, 0 is closed, 100 is fully open.
        In ZCL 0 is fully open, 100 is fully closed.
        Keep in mind the values have already been flipped to match HA
        in the WindowCovering cluster handler
        """
        if self.current_cover_position is None:
            return None
        return self.current_cover_position == 0

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening or not."""
        return self._state == STATE_OPENING

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing or not."""
        return self._state == STATE_CLOSING

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of ZHA cover.

        In HA None is unknown, 0 is closed, 100 is fully open.
        In ZCL 0 is fully open, 100 is fully closed.
        Keep in mind the values have already been flipped to match HA
        in the WindowCovering cluster handler
        """
        return self._cover_cluster_handler.current_position_lift_percentage

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover."""
        return self._cover_cluster_handler.current_position_tilt_percentage

    def _determine_supported_features(self) -> CoverEntityFeature:
        """Determine the supported cover features."""
        supported_features: CoverEntityFeature = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )
        if (
            self._cover_cluster_handler.window_covering_type
            and self._cover_cluster_handler.window_covering_type
            in (
                WCT.Shutter,
                WCT.Tilt_blind_tilt_only,
                WCT.Tilt_blind_tilt_and_lift,
            )
        ):
            supported_features |= CoverEntityFeature.SET_TILT_POSITION
            supported_features |= CoverEntityFeature.OPEN_TILT
            supported_features |= CoverEntityFeature.CLOSE_TILT
            supported_features |= CoverEntityFeature.STOP_TILT
        return supported_features

    def _determine_initial_state(self) -> None:
        """Determine the initial state of the cover."""
        if (
            self._cover_cluster_handler.window_covering_type
            and self._cover_cluster_handler.window_covering_type
            in (
                WCT.Shutter,
                WCT.Tilt_blind_tilt_only,
                WCT.Tilt_blind_tilt_and_lift,
            )
        ):
            self._determine_state(
                self.current_cover_tilt_position, is_lift_update=False
            )
            if (
                self._cover_cluster_handler.window_covering_type
                == WCT.Tilt_blind_tilt_and_lift
            ):
                state = self._state
                self._determine_state(self.current_cover_position)
                if state == STATE_OPEN and self._state == STATE_CLOSED:
                    # let the tilt state override the lift state
                    self._state = STATE_OPEN
        else:
            self._determine_state(self.current_cover_position)

    def _determine_state(self, position_or_tilt, is_lift_update=True) -> None:
        """Determine the state of the cover.

        In HA None is unknown, 0 is closed, 100 is fully open.
        In ZCL 0 is fully open, 100 is fully closed.
        Keep in mind the values have already been flipped to match HA
        in the WindowCovering cluster handler
        """
        if is_lift_update:
            target = self._target_lift_position
            current = self.current_cover_position
        else:
            target = self._target_tilt_position
            current = self.current_cover_tilt_position

        if position_or_tilt == 0:
            self._state = (
                STATE_CLOSED
                if is_lift_update
                else STATE_OPEN
                if self.current_cover_position is not None
                and self.current_cover_position > 0
                else STATE_CLOSED
            )
            return
        if target is not None and target != current:
            # we are mid transition and shouldn't update the state
            return
        self._state = STATE_OPEN

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle position update from cluster handler."""
        if event.attribute_id in (
            WCAttrs.current_position_lift_percentage.id,
            WCAttrs.current_position_tilt_percentage.id,
        ):
            value = (
                self.current_cover_position
                if event.attribute_id == WCAttrs.current_position_lift_percentage.id
                else self.current_cover_tilt_position
            )
            self._determine_state(
                value,
                is_lift_update=(
                    event.attribute_id == WCAttrs.current_position_lift_percentage.id
                ),
            )
        self.maybe_emit_state_changed_event()

    def async_update_state(self, state):
        """Handle state update from HA operations below."""
        _LOGGER.debug("async_update_state=%s", state)
        self._state = state
        self.maybe_emit_state_changed_event()

    async def async_open_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Open the cover."""
        res = await self._cover_cluster_handler.up_open()
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to open cover: {res[1]}")
        self.async_update_state(STATE_OPENING)

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Open the cover tilt."""
        # 0 is open in ZCL
        res = await self._cover_cluster_handler.go_to_tilt_percentage(0)
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to open cover tilt: {res[1]}")
        self.async_update_state(STATE_OPENING)

    async def async_close_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Close the cover."""
        res = await self._cover_cluster_handler.down_close()
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to close cover: {res[1]}")
        self.async_update_state(STATE_CLOSING)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Close the cover tilt."""
        # 100 is closed in ZCL
        res = await self._cover_cluster_handler.go_to_tilt_percentage(100)
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to close cover tilt: {res[1]}")
        self.async_update_state(STATE_CLOSING)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position."""
        self._target_lift_position = kwargs[ATTR_POSITION]
        assert self._target_lift_position is not None
        assert self.current_cover_position is not None
        # the 100 - value is because we need to invert the value before giving it to ZCL
        res = await self._cover_cluster_handler.go_to_lift_percentage(
            100 - self._target_lift_position
        )
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to set cover position: {res[1]}")
        self.async_update_state(
            STATE_CLOSING
            if self._target_lift_position < self.current_cover_position
            else STATE_OPENING
        )

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Move the cover tilt to a specific position."""
        self._target_tilt_position = kwargs[ATTR_TILT_POSITION]
        assert self._target_tilt_position is not None
        assert self.current_cover_tilt_position is not None
        # the 100 - value is because we need to invert the value before giving it to ZCL
        res = await self._cover_cluster_handler.go_to_tilt_percentage(
            100 - self._target_tilt_position
        )
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to set cover tilt position: {res[1]}")
        self.async_update_state(
            STATE_CLOSING
            if self._target_tilt_position < self.current_cover_tilt_position
            else STATE_OPENING
        )

    async def async_stop_cover(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Stop the cover."""
        res = await self._cover_cluster_handler.stop()
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to stop cover: {res[1]}")
        self._target_lift_position = self.current_cover_position
        self._determine_state(self.current_cover_position)
        self.maybe_emit_state_changed_event()

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Stop the cover tilt."""
        res = await self._cover_cluster_handler.stop()
        if res[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to stop cover: {res[1]}")
        self._target_tilt_position = self.current_cover_tilt_position
        self._determine_state(self.current_cover_tilt_position, is_lift_update=False)
        self.maybe_emit_state_changed_event()


@MULTI_MATCH(
    cluster_handler_names={
        CLUSTER_HANDLER_LEVEL,
        CLUSTER_HANDLER_ON_OFF,
        CLUSTER_HANDLER_SHADE,
    }
)
class Shade(PlatformEntity):
    """ZHA Shade."""

    PLATFORM = Platform.COVER

    _attr_device_class = CoverDeviceClass.SHADE
    _attr_translation_key: str = "shade"

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the ZHA light."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._on_off_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_ON_OFF
        ]
        self._level_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_LEVEL
        ]
        self._is_open: bool = bool(self._on_off_cluster_handler.on_off)
        position = self._level_cluster_handler.current_level
        if position is not None:
            position = max(0, min(255, position))
            position = int(position * 100 / 255)
        self._position: int | None = position
        self._on_off_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )
        self._level_cluster_handler.on_event(
            CLUSTER_HANDLER_LEVEL_CHANGED, self.handle_cluster_handler_set_level
        )
        self._attr_supported_features: CoverEntityFeature = (
            CoverEntityFeature.OPEN
            | CoverEntityFeature.CLOSE
            | CoverEntityFeature.STOP
            | CoverEntityFeature.SET_POSITION
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the cover."""
        if (closed := self.is_closed) is None:
            state = None
        else:
            state = STATE_CLOSED if closed else STATE_OPEN
        response = super().state
        response.update(
            {
                ATTR_CURRENT_POSITION: self.current_cover_position,
                "is_closed": self.is_closed,
                "state": state,
            }
        )
        return response

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

    @property
    def is_closed(self) -> bool | None:
        """Return True if shade is closed."""
        return not self._is_open

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Set open/closed state."""
        if event.attribute_id == OnOff.AttributeDefs.on_off.id:
            self._is_open = bool(event.attribute_value)
            self.maybe_emit_state_changed_event()

    def handle_cluster_handler_set_level(self, event: LevelChangeEvent) -> None:
        """Set the reported position."""
        value = max(0, min(255, event.level))
        self._position = int(value * 100 / 255)
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
            new_pos * 255 / 100, 1
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


@MULTI_MATCH(
    cluster_handler_names={CLUSTER_HANDLER_LEVEL, CLUSTER_HANDLER_ON_OFF},
    manufacturers="Keen Home Inc",
)
class KeenVent(Shade):
    """Keen vent cover."""

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_translation_key: str = "keen_vent"

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        position = self._position or 100
        await asyncio.gather(
            self._level_cluster_handler.move_to_level_with_on_off(
                position * 255 / 100, 1
            ),
            self._on_off_cluster_handler.on(),
        )

        self._is_open = True
        self._position = position
        self.maybe_emit_state_changed_event()
