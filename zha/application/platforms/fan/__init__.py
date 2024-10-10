"""Fans on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
import functools
import math
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.hvac import Fan, FanMode, FanModeSequence

from zha.application import Platform
from zha.application.platforms import (
    BaseEntity,
    BaseEntityInfo,
    GroupEntity,
    PlatformEntity,
)
from zha.application.platforms.fan.const import (
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    DEFAULT_ON_PERCENTAGE,
    PRESET_MODE_AUTO,
    PRESET_MODE_SMART,
    FanEntityFeature,
)
from zha.application.platforms.fan.helpers import (
    NotValidPresetModeError,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers import (
    ClusterAttributeUpdatedEvent,
    wrap_zigpy_exceptions,
)
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_FAN,
)
from zha.zigbee.group import Group

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.FAN)
GROUP_MATCH = functools.partial(PLATFORM_ENTITIES.group_match, Platform.FAN)
MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.FAN)


@dataclass(frozen=True, kw_only=True)
class FanEntityInfo(BaseEntityInfo):
    """Fan entity info."""

    preset_modes: list[str]
    supported_features: FanEntityFeature
    speed_count: int


class BaseFan(BaseEntity):
    """Base representation of a ZHA fan."""

    PLATFORM = Platform.FAN

    _attr_supported_features: FanEntityFeature
    _attr_translation_key: str = "fan"
    _attr_preset_modes: list[str]
    _attr_speed_count: int | None

    @functools.cached_property
    def info_object(self) -> FanEntityInfo:
        """Return a representation of the binary sensor."""
        return FanEntityInfo(
            **super().info_object.__dict__,
            preset_modes=self.preset_modes,
            supported_features=self.supported_features,
            speed_count=self.speed_count,
        )

    @property
    def state(self) -> dict:
        """Return the state of the fan."""
        response = super().state
        response.update(
            {
                "preset_mode": self.preset_mode,
                "percentage": self.percentage,
            }
        )
        return response

    @property
    @abstractmethod
    def percentage(self) -> int | None:
        """Return the current speed percentage."""

    @property
    @abstractmethod
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""

    @functools.cached_property
    def preset_modes(self) -> list[str]:
        """Return the available preset modes."""
        return self._attr_preset_modes

    @functools.cached_property
    def speed_count(self) -> int | None:
        """Return the number of speeds the fan supports."""
        return self._attr_speed_count

    @functools.cached_property
    def supported_features(self) -> FanEntityFeature:
        """Flag supported features."""
        return self._attr_supported_features

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
    ) -> None:
        """Turn the entity on."""
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self.async_set_percentage(DEFAULT_ON_PERCENTAGE)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_percentage(0)

    @abstractmethod
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""

    @abstractmethod
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode for the fan."""

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state update from cluster handler."""
        self.maybe_emit_state_changed_event()


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_FAN)
class StandardsCompliantFan(PlatformEntity, BaseFan):
    """Representation of a ZHA fan."""

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the fan."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._fan_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_FAN
        ]
        self._fan_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

        self._attr_supported_features = FanEntityFeature.TURN_OFF
        self._attr_preset_modes = []

        match self._fan_cluster_handler.fan_mode_sequence:
            case FanModeSequence.Low_Med_High:
                self._attr_supported_features |= FanEntityFeature.SET_SPEED
                self._attr_speed_count = 3

            case FanModeSequence.Low_High:
                self._attr_supported_features |= FanEntityFeature.SET_SPEED
                self._attr_speed_count = 2

            case FanModeSequence.Low_Med_High_Auto:
                self._attr_supported_features |= FanEntityFeature.SET_SPEED
                self._attr_supported_features |= FanEntityFeature.PRESET_MODE
                self._attr_speed_count = 3
                self._attr_preset_modes.append(PRESET_MODE_AUTO)

            case FanModeSequence.Low_High_Auto:
                self._attr_supported_features |= FanEntityFeature.SET_SPEED
                self._attr_supported_features |= FanEntityFeature.PRESET_MODE
                self._attr_speed_count = 2
                self._attr_preset_modes.append(PRESET_MODE_AUTO)

            case FanModeSequence.On_Auto:
                self._attr_supported_features |= FanEntityFeature.TURN_ON
                self._attr_supported_features |= FanEntityFeature.PRESET_MODE
                self._attr_speed_count = None
                self._attr_preset_modes.append(PRESET_MODE_AUTO)

            case _:
                # XXX: Current defaults
                self._attr_supported_features |= FanEntityFeature.SET_SPEED
                self._attr_supported_features |= FanEntityFeature.TURN_ON
                self._attr_speed_count = 3

        # XXX: Note that the "Smart" preset is intentionally omitted here. The spec does
        # not provide any way to tell if a fan supports this mode, only hinting that it
        # MAY be provided if the fan device also has an occupancy cluster.

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if self._fan_cluster_handler.fan_mode is None:
            return None
        if self._fan_cluster_handler.fan_mode == FanMode.Off:
            return 0

        return ranged_value_to_percentage(
            low_high_range=(1, self.speed_count),
            value=self._fan_cluster_handler.fan_mode,
        )

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        match self._fan_cluster_handler.fan_mode:
            case FanMode.Off:
                return None
            case FanMode.Auto:
                return PRESET_MODE_AUTO
            case FanMode.Smart:
                return PRESET_MODE_SMART
            case _:
                return None

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            mode = FanMode.OFF
        elif self._attr_speed_count == 2:
            # If we support only LOW/HIGH, there are two speeds: 50% and 100%
            mode = FanMode.LOW if percentage <= 75 else FanMode.HIGH
        elif self._attr_speed_count == 3:
            # If we support LOW/MED/HIGH, there are three speeds: 33%, 66%, and 100%
            mode = (
                FanMode.LOW
                if percentage <= 50
                else FanMode.MED
                if percentage <= 83
                else FanMode.HIGH
            )
        else:
            raise RuntimeError(f"Unsupported fan speed count: {self._attr_speed_count}")

        await self._fan_cluster_handler.async_set_speed(mode)
        self.maybe_emit_state_changed_event()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode for the fan."""
        if preset_mode == PRESET_MODE_AUTO:
            await self._fan_cluster_handler.async_set_speed(FanMode.Auto)
        elif preset_mode == PRESET_MODE_SMART:
            await self._fan_cluster_handler.async_set_speed(FanMode.Smart)
        else:
            raise NotValidPresetModeError(f"Invalid preset mode: {preset_mode}")

        self.maybe_emit_state_changed_event()


@GROUP_MATCH()
class FanGroup(GroupEntity, BaseFan):
    """Representation of a fan group."""

    def __init__(self, group: Group):
        """Initialize a fan group."""
        self._fan_cluster_handler: ClusterHandler = group.endpoint[Fan.cluster_id]
        super().__init__(group)
        self._percentage = None
        self._preset_mode = None
        if hasattr(self, "info_object"):
            delattr(self, "info_object")
        self.update()

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        return self._percentage

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self._preset_mode

    async def _async_set_fan_mode(self, fan_mode: int) -> None:
        """Set the fan mode for the group."""

        with wrap_zigpy_exceptions():
            await self._fan_cluster_handler.write_attributes({"fan_mode": fan_mode})

        self.maybe_emit_state_changed_event()

    def update(self, _: Any = None) -> None:
        """Query all members and determine the fan group state."""
        self.debug("Updating fan group entity state")
        platform_entities = self._group.get_platform_entities(self.PLATFORM)
        all_states = [entity.state for entity in platform_entities]
        self.debug(
            "All platform entity states for group entity members: %s", all_states
        )

        percentage_states: list[dict] = [
            state for state in all_states if state.get(ATTR_PERCENTAGE)
        ]
        preset_mode_states: list[dict] = [
            state for state in all_states if state.get(ATTR_PRESET_MODE)
        ]

        if percentage_states:
            self._percentage = percentage_states[0][ATTR_PERCENTAGE]
            self._preset_mode = None
        elif preset_mode_states:
            self._preset_mode = preset_mode_states[0][ATTR_PRESET_MODE]
            self._percentage = None
        else:
            self._percentage = None
            self._preset_mode = None

        self.maybe_emit_state_changed_event()


@MULTI_MATCH(
    cluster_handler_names="ikea_airpurifier",
    models={"STARKVIND Air purifier", "STARKVIND Air purifier table"},
)
class IkeaFan(PlatformEntity, BaseFan):
    """Representation of an Ikea fan."""

    _attr_supported_features: FanEntityFeature = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.TURN_ON
    )
    _attr_speed_count = 9  # 10-50 in 5% increments
    _attr_preset_modes = [PRESET_MODE_AUTO]

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ):
        """Initialize the fan."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._ikea_fan_cluster_handler: ClusterHandler = self.cluster_handlers[
            "ikea_airpurifier"
        ]
        self._ikea_fan_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if self._ikea_fan_cluster_handler.fan_mode == 0:
            return 0
        if self._ikea_fan_cluster_handler.fan_speed is None:
            return None

        # Fan speed is 10-50
        return self._ikea_fan_cluster_handler.fan_speed * 2.0

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        match self._ikea_fan_cluster_handler.fan_mode:
            case 0:
                return None
            case FanMode.Auto:
                return PRESET_MODE_AUTO
            case _:
                return None

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
    ) -> None:
        """Turn the entity on."""
        if percentage is None and preset_mode is None:
            # Starkvind turns on in auto mode by default
            await self.async_set_preset_mode(PRESET_MODE_AUTO)
        else:
            await super().async_turn_on(percentage, preset_mode)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""

        if percentage == 0:
            mode = FanMode.Off
        else:
            mode = math.ceil(percentage_to_ranged_value((10, 50), percentage))

        await self._ikea_fan_cluster_handler.async_set_speed(mode)
        self.maybe_emit_state_changed_event()


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_FAN,
    models={"HBUniversalCFRemote", "HDC52EastwindFan"},
)
class StandardsCompliantFanWithSmartMode(StandardsCompliantFan):
    """Fan that supports "Smart" mode. Currently just King Of Fans."""

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ):
        """Initialize the fan."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._attr_preset_modes.append(PRESET_MODE_SMART)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode for the fan."""
        if preset_mode == PRESET_MODE_SMART:
            await self._async_set_fan_mode(FanMode.Smart)
        else:
            await super().async_set_preset_mode(preset_mode)
