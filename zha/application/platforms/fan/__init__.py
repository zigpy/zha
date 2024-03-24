"""Fans on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import abstractmethod
import functools
import math
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters import hvac

from zha.application import Platform
from zha.application.platforms import BaseEntity, GroupEntity, PlatformEntity
from zha.application.platforms.fan.const import (
    ATTR_PERCENTAGE,
    ATTR_PRESET_MODE,
    DEFAULT_ON_PERCENTAGE,
    LEGACY_SPEED_LIST,
    OFF_SPEED_VALUES,
    PRESET_MODE_AUTO,
    PRESET_MODE_SMART,
    PRESET_MODES_TO_NAME,
    SPEED_OFF,
    SPEED_RANGE,
    SUPPORT_SET_SPEED,
    FanEntityFeature,
)
from zha.application.platforms.fan.helpers import (
    NotValidPresetModeError,
    int_states_in_range,
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers import (
    ClusterAttributeUpdatedEvent,
    wrap_zigpy_exceptions,
)
from zha.zigbee.cluster_handlers.const import CLUSTER_HANDLER_EVENT, CLUSTER_HANDLER_FAN
from zha.zigbee.group import Group

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.FAN)
GROUP_MATCH = functools.partial(PLATFORM_ENTITIES.group_match, Platform.FAN)
MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.FAN)


class BaseFan(BaseEntity):
    """Base representation of a ZHA fan."""

    PLATFORM = Platform.FAN

    _attr_supported_features = FanEntityFeature.SET_SPEED
    _attr_translation_key: str = "fan"

    @property
    def preset_modes(self) -> list[str]:
        """Return the available preset modes."""
        return list(self.preset_modes_to_name.values())

    @property
    def preset_modes_to_name(self) -> dict[int, str]:
        """Return a dict from preset mode to name."""
        return PRESET_MODES_TO_NAME

    @property
    def preset_name_to_mode(self) -> dict[str, int]:
        """Return a dict from preset name to mode."""
        return {v: k for k, v in self.preset_modes_to_name.items()}

    @property
    def default_on_percentage(self) -> int:
        """Return the default on percentage."""
        return DEFAULT_ON_PERCENTAGE

    @property
    def speed_range(self) -> tuple[int, int]:
        """Return the range of speeds the fan supports. Off is not included."""
        return SPEED_RANGE

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return int_states_in_range(self.speed_range)

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return SUPPORT_SET_SPEED

    @property
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return self.speed not in [SPEED_OFF, None]  # pylint: disable=no-member

    @property
    def percentage_step(self) -> float:
        """Return the step size for percentage."""
        return 100 / self.speed_count

    @property
    def speed_list(self) -> list[str]:
        """Get the list of available speeds."""
        speeds = [SPEED_OFF, *LEGACY_SPEED_LIST]
        if preset_modes := self.preset_modes:
            speeds.extend(preset_modes)
        return speeds

    async def async_turn_on(  # pylint: disable=unused-argument
        self,
        speed: str | None = None,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the entity on."""
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif speed is not None:
            await self.async_set_percentage(self.speed_to_percentage(speed))
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            percentage = self.default_on_percentage
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity off."""
        await self.async_set_percentage(0)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        fan_mode = math.ceil(percentage_to_ranged_value(self.speed_range, percentage))
        await self._async_set_fan_mode(fan_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode for the fan."""
        try:
            mode = self.preset_name_to_mode[preset_mode]
        except KeyError as ex:
            raise NotValidPresetModeError(
                f"{preset_mode} is not a valid preset mode"
            ) from ex
        await self._async_set_fan_mode(mode)

    @abstractmethod
    async def _async_set_fan_mode(self, fan_mode: int) -> None:
        """Set the fan mode for the fan."""

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state update from cluster handler."""
        self.maybe_emit_state_changed_event()

    def speed_to_percentage(self, speed: str) -> int:
        """Map a legacy speed to a percentage."""
        if speed in OFF_SPEED_VALUES:
            return 0
        if speed not in LEGACY_SPEED_LIST:
            raise ValueError(f"The speed {speed} is not a valid speed.")
        return ordered_list_item_to_percentage(LEGACY_SPEED_LIST, speed)

    def percentage_to_speed(self, percentage: int) -> str:
        """Map a percentage to a legacy speed."""
        if percentage == 0:
            return SPEED_OFF
        return percentage_to_ordered_list_item(LEGACY_SPEED_LIST, percentage)

    def to_json(self) -> dict:
        """Return a JSON representation of the binary sensor."""
        json = super().to_json()
        json["preset_modes"] = self.preset_modes
        json["supported_features"] = self.supported_features
        json["speed_count"] = self.speed_count
        json["speed_list"] = self.speed_list
        json["percentage_step"] = self.percentage_step
        json["default_on_percentage"] = self.default_on_percentage
        return json


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_FAN)
class ZhaFan(PlatformEntity, BaseFan):
    """Representation of a ZHA fan."""

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ) -> None:
        """Initialize the fan."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._fan_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_FAN
        )
        if self._fan_cluster_handler:
            self._fan_cluster_handler.on_event(
                CLUSTER_HANDLER_EVENT, self._handle_event_protocol
            )

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if (
            self._fan_cluster_handler.fan_mode is None
            or self._fan_cluster_handler.fan_mode > self.speed_range[1]
        ):
            return None
        if self._fan_cluster_handler.fan_mode == 0:
            return 0
        return ranged_value_to_percentage(
            self.speed_range, self._fan_cluster_handler.fan_mode
        )

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self.preset_modes_to_name.get(self._fan_cluster_handler.fan_mode)

    @property
    def speed(self) -> str | None:
        """Return the current speed."""
        if preset_mode := self.preset_mode:
            return preset_mode
        if (percentage := self.percentage) is None:
            return None
        return self.percentage_to_speed(percentage)

    def get_state(self) -> dict:
        """Return the state of the fan."""
        response = super().get_state()
        response.update(
            {
                "preset_mode": self.preset_mode,
                "percentage": self.percentage,
                "is_on": self.is_on,
                "speed": self.speed,
            }
        )
        return response

    async def _async_set_fan_mode(self, fan_mode: int) -> None:
        """Set the fan mode for the fan."""
        await self._fan_cluster_handler.async_set_speed(fan_mode)
        self.maybe_emit_state_changed_event()


@GROUP_MATCH()
class FanGroup(GroupEntity, BaseFan):
    """Representation of a fan group."""

    _attr_translation_key: str = "fan_group"

    def __init__(self, group: Group):
        """Initialize a fan group."""
        self._fan_cluster_handler: ClusterHandler = group.endpoint[hvac.Fan.cluster_id]
        super().__init__(group)
        self._available: bool = False
        self._percentage = None
        self._preset_mode = None

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        return self._percentage

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self._preset_mode

    @property
    def speed(self) -> str | None:
        """Return the current speed."""
        if preset_mode := self.preset_mode:
            return preset_mode
        if (percentage := self.percentage) is None:
            return None
        return self.percentage_to_speed(percentage)

    def get_state(self) -> dict:
        """Return the state of the fan."""
        response = super().get_state()
        response.update(
            {
                "preset_mode": self.preset_mode,
                "percentage": self.percentage,
                "is_on": self.is_on,
                "speed": self.speed,
            }
        )
        return response

    async def _async_set_fan_mode(self, fan_mode: int) -> None:
        """Set the fan mode for the group."""

        with wrap_zigpy_exceptions():
            await self._fan_cluster_handler.write_attributes({"fan_mode": fan_mode})

        self.maybe_emit_state_changed_event()

    def update(self, _: Any = None) -> None:
        """Attempt to retrieve on off state from the fan."""
        self.debug("Updating fan group entity state")
        platform_entities = self._group.get_platform_entities(self.PLATFORM)
        all_entities = [entity.to_json() for entity in platform_entities]
        all_states = [entity["state"] for entity in all_entities]
        self.debug(
            "All platform entity states for group entity members: %s", all_states
        )

        self._available = any(entity.available for entity in platform_entities)
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


IKEA_SPEED_RANGE = (1, 10)  # off is not included
IKEA_PRESET_MODES_TO_NAME = {
    1: PRESET_MODE_AUTO,
    2: "Speed 1",
    3: "Speed 1.5",
    4: "Speed 2",
    5: "Speed 2.5",
    6: "Speed 3",
    7: "Speed 3.5",
    8: "Speed 4",
    9: "Speed 4.5",
    10: "Speed 5",
}


@MULTI_MATCH(
    cluster_handler_names="ikea_airpurifier",
    models={"STARKVIND Air purifier", "STARKVIND Air purifier table"},
)
class IkeaFan(ZhaFan):
    """Representation of an Ikea fan."""

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ):
        """Initialize the fan."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._fan_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            "ikea_airpurifier"
        )
        self._fan_cluster_handler.on_event(
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )

    @property
    def preset_modes_to_name(self) -> dict[int, str]:
        """Return a dict from preset mode to name."""
        return IKEA_PRESET_MODES_TO_NAME

    @property
    def speed_range(self) -> tuple[int, int]:
        """Return the range of speeds the fan supports. Off is not included."""
        return IKEA_SPEED_RANGE

    @property
    def default_on_percentage(self) -> int:
        """Return the default on percentage."""
        return int(
            (100 / self.speed_count) * self.preset_name_to_mode[PRESET_MODE_AUTO]
        )


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_FAN,
    models={"HBUniversalCFRemote", "HDC52EastwindFan"},
)
class KofFan(ZhaFan):
    """Representation of a fan made by King Of Fans."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE

    @property
    def speed_range(self) -> tuple[int, int]:
        """Return the range of speeds the fan supports. Off is not included."""
        return (1, 4)

    @property
    def preset_modes_to_name(self) -> dict[int, str]:
        """Return a dict from preset mode to name."""
        return {6: PRESET_MODE_SMART}
