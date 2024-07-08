"""Lights on Zigbee Home Automation networks."""

# pylint: disable=too-many-lines

from __future__ import annotations

from abc import ABC
import asyncio
from collections import Counter
from collections.abc import Callable
import contextlib
import dataclasses
from dataclasses import dataclass
import functools
import itertools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.types import EUI64
from zigpy.zcl.clusters.general import Identify, LevelControl, OnOff
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import (
    BaseEntity,
    BaseEntityInfo,
    GroupEntity,
    PlatformEntity,
)
from zha.application.platforms.helpers import (
    find_state_attributes,
    mean_tuple,
    reduce_attribute,
)
from zha.application.platforms.light.const import (
    ASSUME_UPDATE_GROUP_FROM_CHILD_DELAY,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_MAX_MIREDS,
    ATTR_MIN_MIREDS,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_SUPPORTED_FEATURES,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    DEFAULT_EXTRA_TRANSITION_DELAY_LONG,
    DEFAULT_EXTRA_TRANSITION_DELAY_SHORT,
    DEFAULT_LONG_TRANSITION_TIME,
    DEFAULT_MIN_BRIGHTNESS,
    DEFAULT_MIN_TRANSITION_MANUFACTURERS,
    DEFAULT_ON_OFF_TRANSITION,
    EFFECT_COLORLOOP,
    FLASH_EFFECTS,
    SUPPORT_GROUP_LIGHT,
    ColorMode,
    LightEntityFeature,
)
from zha.application.platforms.light.helpers import (
    brightness_supported,
    filter_supported_color_modes,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.debounce import Debouncer
from zha.decorators import periodic
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent, ClusterHandlerInfo
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_COLOR,
    CLUSTER_HANDLER_LEVEL,
    CLUSTER_HANDLER_LEVEL_CHANGED,
    CLUSTER_HANDLER_ON_OFF,
)
from zha.zigbee.cluster_handlers.general import LevelChangeEvent

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint
    from zha.zigbee.group import Group

_LOGGER = logging.getLogger(__name__)

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.LIGHT)
GROUP_MATCH = functools.partial(PLATFORM_ENTITIES.group_match, Platform.LIGHT)


@dataclass(frozen=True, kw_only=True)
class LightEntityInfo(BaseEntityInfo):
    """Light entity info."""

    # combination of PlatformEntityInfo and GroupEntityInfo
    unique_id: str
    platform: str
    class_name: str

    cluster_handlers: list[ClusterHandlerInfo] | None = dataclasses.field(default=None)
    device_ieee: EUI64 | None = dataclasses.field(default=None)
    endpoint_id: int | None = dataclasses.field(default=None)
    group_id: int | None = dataclasses.field(default=None)
    name: str | None = dataclasses.field(default=None)
    available: bool | None = dataclasses.field(default=None)

    effect_list: list[str] | None = dataclasses.field(default=None)
    supported_features: LightEntityFeature
    min_mireds: int
    max_mireds: int


class BaseLight(BaseEntity, ABC):
    """Operations common to all light entities."""

    PLATFORM = Platform.LIGHT
    _FORCE_ON = False
    _DEFAULT_MIN_TRANSITION_TIME: float = 0
    _attr_extra_state_attribute_names: set[str] = {
        "off_with_transition",
        "off_brightness",
    }

    def __init__(self, *args, **kwargs):
        """Initialize the light."""
        self._device: Device = None
        super().__init__(*args, **kwargs)
        self._available: bool = False
        self._min_mireds: int | None = 153
        self._max_mireds: int | None = 500
        self._hs_color: tuple[float, float] | None = None
        self._xy_color: tuple[float, float] | None = None
        self._color_mode = ColorMode.UNKNOWN  # Set by subclasses
        self._color_temp: int | None = None
        self._supported_features: int = 0
        self._state: bool | None
        self._brightness: int | None = None
        self._off_with_transition: bool = False
        self._off_brightness: int | None = None
        self._effect_list: list[str] | None = None
        self._effect: str | None = None
        self._supported_color_modes: set[ColorMode] = set()
        self._external_supported_color_modes: set[ColorMode] = set()
        self._zha_config_transition: int = self._DEFAULT_MIN_TRANSITION_TIME
        self._zha_config_enhanced_light_transition: bool = False
        self._zha_config_enable_light_transitioning_flag: bool = True
        self._zha_config_always_prefer_xy_color_mode: bool = True
        self._on_off_cluster_handler: ClusterHandler = None
        self._level_cluster_handler: ClusterHandler = None
        self._color_cluster_handler: ClusterHandler = None
        self._identify_cluster_handler: ClusterHandler = None
        self._transitioning_individual: bool = False
        self._transitioning_group: bool = False
        self._transition_listener: Callable[[], None] | None = None

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the light."""
        response = super().state
        response["on"] = self.is_on
        response["brightness"] = self.brightness
        response["hs_color"] = self.hs_color
        response["xy_color"] = self.xy_color
        response["color_temp"] = self.color_temp
        response["effect"] = self.effect
        response["supported_features"] = self.supported_features
        response["color_mode"] = self.color_mode
        response["supported_color_modes"] = self._supported_color_modes
        response["off_with_transition"] = self._off_with_transition
        response["off_brightness"] = self._off_brightness
        return response

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hs color value [int, int]."""
        return self._hs_color

    @property
    def xy_color(self) -> tuple[float, float] | None:
        """Return the xy color value [float, float]."""
        return self._xy_color

    @property
    def color_temp(self) -> int | None:
        """Return the CT color value in mireds."""
        return self._color_temp

    @property
    def color_mode(self) -> int | None:
        """Return the color mode."""
        return self._color_mode

    @property
    def effect_list(self) -> list[str] | None:
        """Return the list of supported effects."""
        return self._effect_list

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        return self._effect

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._supported_features

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Flag supported color modes."""
        return self._external_supported_color_modes

    @property
    def is_on(self) -> bool:
        """Return true if entity is on."""
        if self._state is None:
            return False
        return self._state

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light."""
        return self._brightness

    @property
    def min_mireds(self) -> int | None:
        """Return the coldest color_temp that this light supports."""
        return self._min_mireds

    @property
    def max_mireds(self) -> int | None:
        """Return the warmest color_temp that this light supports."""
        return self._max_mireds

    def handle_cluster_handler_set_level(self, event: LevelChangeEvent) -> None:
        """Set the brightness of this light between 0..254.

        brightness level 255 is a special value instructing the device to come
        on at `on_level` Zigbee attribute value, regardless of the last set
        level
        """
        if self.is_transitioning:
            self.debug(
                "received level change event %s while transitioning - skipping update",
                event,
            )
            return
        value = max(0, min(254, event.level))
        self._brightness = value
        self.maybe_emit_state_changed_event()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        transition = kwargs.get(ATTR_TRANSITION)
        duration = (
            transition if transition is not None else self._zha_config_transition
        ) or (
            # if 0 is passed in some devices still need the minimum default
            self._DEFAULT_MIN_TRANSITION_TIME
        )
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        effect = kwargs.get(ATTR_EFFECT)
        flash = kwargs.get(ATTR_FLASH)
        temperature = kwargs.get(ATTR_COLOR_TEMP)
        xy_color = kwargs.get(ATTR_XY_COLOR)
        hs_color = kwargs.get(ATTR_HS_COLOR)

        execute_if_off_supported = (
            self._GROUP_SUPPORTS_EXECUTE_IF_OFF
            if isinstance(self, LightGroup)
            else self._color_cluster_handler
            and self._color_cluster_handler.execute_if_off_supported
        )

        set_transition_flag = (
            brightness_supported(self._supported_color_modes)
            or temperature is not None
            or xy_color is not None
            or hs_color is not None
        ) and self._zha_config_enable_light_transitioning_flag
        transition_time = (
            (
                duration + DEFAULT_EXTRA_TRANSITION_DELAY_SHORT
                if (
                    (brightness is not None or transition is not None)
                    and brightness_supported(self._supported_color_modes)
                    or (self._off_with_transition and self._off_brightness is not None)
                    or temperature is not None
                    or xy_color is not None
                    or hs_color is not None
                )
                else DEFAULT_ON_OFF_TRANSITION + DEFAULT_EXTRA_TRANSITION_DELAY_SHORT
            )
            if set_transition_flag
            else 0
        )

        # If we need to pause attribute report parsing, we'll do so here.
        # After successful calls, we later start a timer to unset the flag after
        # transition_time.
        # - On an error on the first move to level call, we unset the flag immediately
        #   if no previous timer is running.
        # - On an error on subsequent calls, we start the transition timer,
        #   as a brightness call might have come through.
        if set_transition_flag:
            self.async_transition_set_flag()

        # If the light is currently off but a turn_on call with a color/temperature is
        # sent, the light needs to be turned on first at a low brightness level where
        # the light is immediately transitioned to the correct color. Afterwards, the
        # transition is only from the low brightness to the new brightness.
        # Otherwise, the transition is from the color the light had before being turned
        # on to the new color. This can look especially bad with transitions longer than
        # a second. We do not want to do this for devices that need to be forced to use
        # the on command because we would end up with 4 commands sent:
        # move to level, on, color, move to level... We also will not set this
        # if the bulb is already in the desired color mode with the desired color
        # or color temperature.
        new_color_provided_while_off = (
            self._zha_config_enhanced_light_transition
            and not self._FORCE_ON
            and not self._state
            and (
                (
                    temperature is not None
                    and (
                        self._color_temp != temperature
                        or self._color_mode != ColorMode.COLOR_TEMP
                    )
                )
                or (
                    xy_color is not None
                    and (self._xy_color != xy_color or self._color_mode != ColorMode.XY)
                )
                or (
                    hs_color is not None
                    and (self._hs_color != hs_color or self._color_mode != ColorMode.HS)
                )
            )
            and brightness_supported(self._supported_color_modes)
            and not execute_if_off_supported
        )

        if (
            brightness is None
            and (self._off_with_transition or new_color_provided_while_off)
            and self._off_brightness is not None
        ):
            brightness = self._off_brightness

        if brightness is not None:
            level = min(254, brightness)
        else:
            level = self._brightness or 254

        t_log = {}

        if new_color_provided_while_off:
            # If the light is currently off, we first need to turn it on at a low
            # brightness level with no transition.
            # After that, we set it to the desired color/temperature with no transition.
            result = await self._level_cluster_handler.move_to_level_with_on_off(
                level=DEFAULT_MIN_BRIGHTNESS,
                transition_time=int(10 * self._DEFAULT_MIN_TRANSITION_TIME),
            )
            t_log["move_to_level_with_on_off"] = result
            if result[1] is not Status.SUCCESS:
                # First 'move to level' call failed, so if the transitioning delay
                # isn't running from a previous call,
                # the flag can be unset immediately
                if set_transition_flag and not self._transition_listener:
                    self.async_transition_complete()
                self.debug("turned on: %s", t_log)
                return
            # Currently only setting it to "on", as the correct level state will
            # be set at the second move_to_level call
            self._state = True

        if execute_if_off_supported:
            self.debug("handling color commands before turning on/level")
            if not await self.async_handle_color_commands(
                temperature,
                duration,  # duration is ignored by lights when off
                hs_color,
                xy_color,
                new_color_provided_while_off,
                t_log,
            ):
                # Color calls before on/level calls failed,
                # so if the transitioning delay isn't running from a previous call,
                # the flag can be unset immediately
                if set_transition_flag and not self._transition_listener:
                    self.async_transition_complete()
                self.debug("turned on: %s", t_log)
                return

        if (
            (brightness is not None or transition is not None)
            and not new_color_provided_while_off
            and brightness_supported(self._supported_color_modes)
        ):
            result = await self._level_cluster_handler.move_to_level_with_on_off(
                level=level,
                transition_time=int(10 * duration),
            )
            t_log["move_to_level_with_on_off"] = result
            if result[1] is not Status.SUCCESS:
                # First 'move to level' call failed, so if the transitioning delay
                # isn't running from a previous call, the flag can be unset immediately
                if set_transition_flag and not self._transition_listener:
                    self.async_transition_complete()
                self.debug("turned on: %s", t_log)
                return
            self._state = bool(level)
            if level:
                self._brightness = level

        if (
            (brightness is None and transition is None)
            and not new_color_provided_while_off
            or (self._FORCE_ON and brightness != 0)
        ):
            # since FORCE_ON lights don't turn on with move_to_level_with_on_off,
            # we should call the on command on the on_off cluster
            # if brightness is not 0.
            result = await self._on_off_cluster_handler.on()
            t_log["on_off"] = result
            if result[1] is not Status.SUCCESS:
                # 'On' call failed, but as brightness may still transition
                # (for FORCE_ON lights), we start the timer to unset the flag after
                # the transition_time if necessary.
                self.async_transition_start_timer(transition_time)
                self.debug("turned on: %s", t_log)
                return
            self._state = True

        if not execute_if_off_supported:
            self.debug("handling color commands after turning on/level")
            if not await self.async_handle_color_commands(
                temperature,
                duration,
                hs_color,
                xy_color,
                new_color_provided_while_off,
                t_log,
            ):
                # Color calls failed, but as brightness may still transition,
                # we start the timer to unset the flag
                self.async_transition_start_timer(transition_time)
                self.debug("turned on: %s", t_log)
                return

        if new_color_provided_while_off:
            # The light has the correct color, so we can now transition
            # it to the correct brightness level.
            result = await self._level_cluster_handler.move_to_level(
                level=level, transition_time=int(10 * duration)
            )
            t_log["move_to_level_if_color"] = result
            if result[1] is not Status.SUCCESS:
                self.debug("turned on: %s", t_log)
                return
            self._state = bool(level)
            if level:
                self._brightness = level

        # Our light is guaranteed to have just started the transitioning process
        # if necessary, so we start the delay for the transition (to stop parsing
        # attribute reports after the completed transition).
        self.async_transition_start_timer(transition_time)

        if effect == EFFECT_COLORLOOP:
            result = await self._color_cluster_handler.color_loop_set(
                update_flags=(
                    Color.ColorLoopUpdateFlags.Action
                    | Color.ColorLoopUpdateFlags.Direction
                    | Color.ColorLoopUpdateFlags.Time
                ),
                action=Color.ColorLoopAction.Activate_from_current_hue,
                direction=Color.ColorLoopDirection.Increment,
                time=transition if transition else 7,
                start_hue=0,
            )
            t_log["color_loop_set"] = result
            self._effect = EFFECT_COLORLOOP
        elif self._effect == EFFECT_COLORLOOP and effect != EFFECT_COLORLOOP:
            result = await self._color_cluster_handler.color_loop_set(
                update_flags=Color.ColorLoopUpdateFlags.Action,
                action=Color.ColorLoopAction.Deactivate,
                direction=Color.ColorLoopDirection.Decrement,
                time=0,
                start_hue=0,
            )
            t_log["color_loop_set"] = result
            self._effect = None

        if flash is not None:
            result = await self._identify_cluster_handler.trigger_effect(
                effect_id=FLASH_EFFECTS[flash],
                effect_variant=Identify.EffectVariant.Default,
            )
            t_log["trigger_effect"] = result

        self._off_with_transition = False
        self._off_brightness = None
        self.debug("turned on: %s", t_log)
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        transition = kwargs.get(ATTR_TRANSITION)
        supports_level = brightness_supported(self._supported_color_modes)

        transition_time = (
            transition or self._DEFAULT_MIN_TRANSITION_TIME
            if transition is not None
            else DEFAULT_ON_OFF_TRANSITION
        ) + DEFAULT_EXTRA_TRANSITION_DELAY_SHORT

        # Start pausing attribute report parsing
        if self._zha_config_enable_light_transitioning_flag:
            self.async_transition_set_flag()

        # is not none looks odd here, but it will override built in bulb
        # transition times if we pass 0 in here
        if transition is not None and supports_level:
            result = await self._level_cluster_handler.move_to_level_with_on_off(
                level=0,
                transition_time=int(
                    10 * (transition or self._DEFAULT_MIN_TRANSITION_TIME)
                ),
            )
        else:
            result = await self._on_off_cluster_handler.off()

        # Pause parsing attribute reports until transition is complete
        if self._zha_config_enable_light_transitioning_flag:
            self.async_transition_start_timer(transition_time)
        self.debug("turned off: %s", result)
        if result[1] is not Status.SUCCESS:
            return
        self._state = False

        if supports_level and not self._off_with_transition:
            # store current brightness so that the next turn_on uses it:
            # when using "enhanced turn on"
            self._off_brightness = self._brightness
            if transition is not None:
                # save for when calling turn_on without a brightness:
                # current_level is set to 1 after transitioning to level 0,
                # needed for correct state with light groups
                self._brightness = 1
                self._off_with_transition = transition is not None

        self.maybe_emit_state_changed_event()

    async def async_handle_color_commands(
        self,
        temperature,
        duration,
        hs_color,
        xy_color,
        new_color_provided_while_off,
        t_log,
    ):
        """Process ZCL color commands."""

        transition_time = (
            self._DEFAULT_MIN_TRANSITION_TIME
            if new_color_provided_while_off
            else duration
        )

        if temperature is not None:
            result = await self._color_cluster_handler.move_to_color_temp(
                color_temp_mireds=temperature,
                transition_time=int(10 * transition_time),
            )
            t_log["move_to_color_temp"] = result
            if result[1] is not Status.SUCCESS:
                return False
            self._color_mode = ColorMode.COLOR_TEMP
            self._color_temp = temperature
            self._xy_color = None
            self._hs_color = None

        if hs_color is not None:
            if (
                not isinstance(self, LightGroup)
                and self._color_cluster_handler.enhanced_hue_supported
            ):
                result = await self._color_cluster_handler.enhanced_move_to_hue_and_saturation(
                    enhanced_hue=int(hs_color[0] * 65535 / 360),
                    saturation=int(hs_color[1] * 2.54),
                    transition_time=int(10 * transition_time),
                )
                t_log["enhanced_move_to_hue_and_saturation"] = result
            else:
                result = await self._color_cluster_handler.move_to_hue_and_saturation(
                    hue=int(hs_color[0] * 254 / 360),
                    saturation=int(hs_color[1] * 2.54),
                    transition_time=int(10 * transition_time),
                )
                t_log["move_to_hue_and_saturation"] = result
            if result[1] is not Status.SUCCESS:
                return False
            self._color_mode = ColorMode.HS
            self._hs_color = hs_color
            self._xy_color = None
            self._color_temp = None
            xy_color = None  # don't set xy_color if it is also present

        if xy_color is not None:
            result = await self._color_cluster_handler.move_to_color(
                color_x=int(xy_color[0] * 65535),
                color_y=int(xy_color[1] * 65535),
                transition_time=int(10 * transition_time),
            )
            t_log["move_to_color"] = result
            if result[1] is not Status.SUCCESS:
                return False
            self._color_mode = ColorMode.XY
            self._xy_color = xy_color
            self._color_temp = None
            self._hs_color = None

        return True

    @property
    def is_transitioning(self) -> bool:
        """Return if the light is transitioning."""
        return self._transitioning_individual or self._transitioning_group

    def async_transition_set_flag(self) -> None:
        """Set _transitioning to True."""
        self.debug("setting transitioning flag to True")
        self._transitioning_individual = True
        self._transitioning_group = False
        if isinstance(self, LightGroup):
            for platform_entity in self.group.get_platform_entities(Light.PLATFORM):
                platform_entity.transition_on()
        self._async_unsub_transition_listener()

    def async_transition_start_timer(self, transition_time) -> None:
        """Start a timer to unset _transitioning_individual after transition_time.

        If necessary.
        """
        if not transition_time:
            return
        # For longer transitions, we want to extend the timer a bit more
        if transition_time >= DEFAULT_LONG_TRANSITION_TIME:
            transition_time += DEFAULT_EXTRA_TRANSITION_DELAY_LONG
        self.debug("starting transitioning timer for %s", transition_time)
        self._transition_listener = asyncio.get_running_loop().call_later(
            transition_time,
            self.async_transition_complete,
        )
        self._tracked_handles.append(self._transition_listener)

    def _async_unsub_transition_listener(self) -> None:
        """Unsubscribe transition listener."""
        if self._transition_listener:
            self._transition_listener.cancel()
            self._transition_listener = None

            with contextlib.suppress(ValueError):
                self._tracked_handles.remove(self._transition_listener)

    def async_transition_complete(self, _=None) -> None:
        """Set _transitioning_individual to False and write HA state."""
        self.debug("transition complete - future attribute reports will write HA state")
        self._transitioning_individual = False
        self._async_unsub_transition_listener()
        self.maybe_emit_state_changed_event()
        if isinstance(self, LightGroup):
            for platform_entity in self.group.get_platform_entities(Light.PLATFORM):
                platform_entity.transition_off()

            if self._debounced_member_refresh is not None:
                self.debug("transition complete - refreshing group member states")

                self.group.gateway.async_create_task(
                    self._debounced_member_refresh.async_call(),
                    "zha.light-refresh-debounced-member",
                )


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF,
    aux_cluster_handlers={CLUSTER_HANDLER_COLOR, CLUSTER_HANDLER_LEVEL},
)
class Light(PlatformEntity, BaseLight):
    """Representation of a ZHA or ZLL light."""

    _supported_color_modes: set[ColorMode]
    _external_supported_color_modes: set[ColorMode]
    _attr_translation_key: str = "light"
    _REFRESH_INTERVAL = (2700, 4500)
    __polling_interval: int

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ) -> None:
        """Initialize the light."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._on_off_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_ON_OFF
        ]
        self._state: bool = bool(self._on_off_cluster_handler.on_off)
        self._level_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_LEVEL
        )
        self._color_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_COLOR
        )
        self._identify_cluster_handler: ClusterHandler = device.identify_ch
        if self._color_cluster_handler:
            self._min_mireds: int = self._color_cluster_handler.min_mireds
            self._max_mireds: int = self._color_cluster_handler.max_mireds
        self._cancel_refresh_handle: Callable | None = None
        effect_list = []

        light_options = device.gateway.config.config.light_options
        self._zha_config_always_prefer_xy_color_mode = (
            light_options.always_prefer_xy_color_mode
        )

        self._supported_color_modes = {ColorMode.ONOFF}
        if self._level_cluster_handler:
            self._supported_color_modes.add(ColorMode.BRIGHTNESS)
            self._supported_features |= LightEntityFeature.TRANSITION
            self._brightness = self._level_cluster_handler.current_level

        if self._color_cluster_handler:
            if self._color_cluster_handler.color_temp_supported:
                self._supported_color_modes.add(ColorMode.COLOR_TEMP)
                self._color_temp = self._color_cluster_handler.color_temperature

            if self._color_cluster_handler.xy_supported and (
                self._zha_config_always_prefer_xy_color_mode
                or not self._color_cluster_handler.hs_supported
            ):
                self._supported_color_modes.add(ColorMode.XY)
                curr_x = self._color_cluster_handler.current_x
                curr_y = self._color_cluster_handler.current_y
                if curr_x is not None and curr_y is not None:
                    self._xy_color = (curr_x / 65535, curr_y / 65535)
                else:
                    self._xy_color = (0, 0)

            if (
                self._color_cluster_handler.hs_supported
                and not self._zha_config_always_prefer_xy_color_mode
            ):
                self._supported_color_modes.add(ColorMode.HS)
                if (
                    self._color_cluster_handler.enhanced_hue_supported
                    and self._color_cluster_handler.enhanced_current_hue is not None
                ):
                    curr_hue = (
                        self._color_cluster_handler.enhanced_current_hue * 65535 / 360
                    )
                elif self._color_cluster_handler.current_hue is not None:
                    curr_hue = self._color_cluster_handler.current_hue * 254 / 360
                else:
                    curr_hue = 0

                if (
                    curr_saturation := self._color_cluster_handler.current_saturation
                ) is None:
                    curr_saturation = 0

                self._hs_color = (
                    int(curr_hue),
                    int(curr_saturation * 2.54),
                )

            if self._color_cluster_handler.color_loop_supported:
                self._supported_features |= LightEntityFeature.EFFECT
                effect_list.append(EFFECT_COLORLOOP)
                if self._color_cluster_handler.color_loop_active == 1:
                    self._effect = EFFECT_COLORLOOP
        self._external_supported_color_modes = supported_color_modes = (
            filter_supported_color_modes(self._supported_color_modes)
        )
        if len(supported_color_modes) == 1:
            self._color_mode = next(iter(supported_color_modes))
        else:  # Light supports color_temp + hs, determine which mode the light is in
            assert self._color_cluster_handler
            if (
                self._color_cluster_handler.color_mode
                == Color.ColorMode.Color_temperature
            ):
                self._color_mode = ColorMode.COLOR_TEMP
            else:
                self._color_mode = ColorMode.XY

        if self._identify_cluster_handler:
            self._supported_features |= LightEntityFeature.FLASH

        if effect_list:
            self._effect_list = effect_list

        self._zha_config_transition = light_options.default_light_transition
        self._zha_config_enhanced_light_transition = (
            light_options.enable_enhanced_light_transition
        )
        self._zha_config_enable_light_transitioning_flag = (
            light_options.enable_light_transitioning_flag
        )

        self._on_off_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

        if self._level_cluster_handler:
            self._level_cluster_handler.on_event(
                CLUSTER_HANDLER_LEVEL_CHANGED, self.handle_cluster_handler_set_level
            )

        self._tracked_tasks.append(
            device.gateway.async_create_background_task(
                self._refresh(),
                name=f"light_refresh_{self.unique_id}",
                eager_start=True,
                untracked=True,
            )
        )
        self.debug(
            "started polling with refresh interval of %s",
            getattr(self, "__polling_interval"),
        )

    @functools.cached_property
    def info_object(self) -> LightEntityInfo:
        """Return a representation of the select."""
        return LightEntityInfo(
            **super().info_object.__dict__,
            effect_list=self.effect_list,
            supported_features=self.supported_features,
            min_mireds=self.min_mireds,
            max_mireds=self.max_mireds,
        )

    @periodic(_REFRESH_INTERVAL)
    async def _refresh(self) -> None:
        """Call async_get_state at an interval."""
        await self.async_update()

    def transition_on(self):
        """Handle a transition start event from a group."""
        self.debug("group transition started - setting member transitioning flag")
        self._transitioning_group = True

    def transition_off(self):
        """Handle a transition finished event from a group."""
        self.debug("group transition completed - unsetting member transitioning flag")
        self._transitioning_group = False

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Set the state."""
        if (
            event.cluster_id != self._on_off_cluster_handler.cluster.cluster_id
            or event.attribute_id != OnOff.AttributeDefs.on_off.id
        ):
            return
        if self.is_transitioning:
            self.debug(
                "received onoff %s while transitioning - skipping update",
                event.attribute_value,
            )
            return
        self._state = bool(event.attribute_value)
        if event.attribute_value:
            self._off_with_transition = False
            self._off_brightness = None
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve the state from the light."""
        if self.is_transitioning:
            self.debug("skipping async_update while transitioning")
            return
        if not self.device.gateway.config.allow_polling or not self._device.available:
            self.debug(
                "skipping polling for updated state, available: %s, allow polled requests: %s",
                self._device.available,
                self.device.gateway.config.allow_polling,
            )
            return
        self.debug("polling current state")

        if self._on_off_cluster_handler:
            state = await self._on_off_cluster_handler.get_attribute_value(
                "on_off", from_cache=False
            )
            # check if transition started whilst waiting for polled state
            if self.is_transitioning:
                return  # type: ignore[unreachable]

            if state is not None:
                self._state = state
                if state:  # reset "off with transition" flag if the light is on
                    self._off_with_transition = False
                    self._off_brightness = None

        if self._level_cluster_handler:
            level = await self._level_cluster_handler.get_attribute_value(
                "current_level", from_cache=False
            )
            # check if transition started whilst waiting for polled state
            if self.is_transitioning:
                return  # type: ignore[unreachable]
            if level is not None:
                self._brightness = level

        if self._color_cluster_handler:
            attributes = [
                "color_mode",
                "current_x",
                "current_y",
            ]
            if (
                not self._zha_config_always_prefer_xy_color_mode
                and self._color_cluster_handler.enhanced_hue_supported
            ):
                attributes.append("enhanced_current_hue")
                attributes.append("current_saturation")
            if (
                self._color_cluster_handler.hs_supported
                and not self._color_cluster_handler.enhanced_hue_supported
                and not self._zha_config_always_prefer_xy_color_mode
            ):
                attributes.append("current_hue")
                attributes.append("current_saturation")
            if self._color_cluster_handler.color_temp_supported:
                attributes.append("color_temperature")
            if self._color_cluster_handler.color_loop_supported:
                attributes.append("color_loop_active")

            results = await self._color_cluster_handler.get_attributes(
                attributes, from_cache=False, only_cache=False
            )

            # although rare, a transition might have been started while we were waiting
            # for the polled attributes, so abort if we are transitioning,
            # as that state will not be accurate
            if self.is_transitioning:
                return  # type: ignore[unreachable]

            if (color_mode := results.get("color_mode")) is not None:
                if color_mode == Color.ColorMode.Color_temperature:
                    self._color_mode = ColorMode.COLOR_TEMP
                    color_temp = results.get("color_temperature")
                    if color_temp is not None and color_mode:
                        self._color_temp = color_temp
                        self._xy_color = None
                        self._hs_color = None
                elif (
                    color_mode == Color.ColorMode.Hue_and_saturation
                    and not self._zha_config_always_prefer_xy_color_mode
                ):
                    self._color_mode = ColorMode.HS
                    if self._color_cluster_handler.enhanced_hue_supported:
                        current_hue = results.get("enhanced_current_hue")
                    else:
                        current_hue = results.get("current_hue")
                    current_saturation = results.get("current_saturation")
                    if current_hue is not None and current_saturation is not None:
                        self._hs_color = (
                            int(current_hue * 360 / 65535)
                            if self._color_cluster_handler.enhanced_hue_supported
                            else int(current_hue * 360 / 254),
                            int(current_saturation / 2.54),
                        )
                        self._xy_color = None
                        self._color_temp = None
                else:
                    self._color_mode = ColorMode.XY
                    color_x = results.get("current_x")
                    color_y = results.get("current_y")
                    if color_x is not None and color_y is not None:
                        self._xy_color = (color_x / 65535, color_y / 65535)
                        self._color_temp = None
                        self._hs_color = None

            color_loop_active = results.get("color_loop_active")
            if color_loop_active is not None:
                if color_loop_active == 1:
                    self._effect = EFFECT_COLORLOOP
                else:
                    self._effect = None
        self.maybe_emit_state_changed_event()

    def _assume_group_state(self, update_params) -> None:
        """Handle an assume group state event from a group."""
        if self.available:
            self.debug("member assuming group state with: %s", update_params)

            state = update_params["state"]
            brightness = update_params.get(ATTR_BRIGHTNESS)
            color_mode = update_params.get(ATTR_COLOR_MODE)
            color_temp = update_params.get(ATTR_COLOR_TEMP)
            xy_color = update_params.get(ATTR_XY_COLOR)
            hs_color = update_params.get(ATTR_HS_COLOR)
            effect = update_params.get(ATTR_EFFECT)

            supported_modes = self._supported_color_modes

            # unset "off brightness" and "off with transition"
            # if group turned on this light
            if state and not self._state:
                self._off_with_transition = False
                self._off_brightness = None

            # set "off brightness" and "off with transition"
            # if group turned off this light, and the light was not already off
            # (to not override _off_with_transition)
            elif not state and self._state and brightness_supported(supported_modes):
                # use individual brightness, instead of possibly averaged
                # brightness from group
                self._off_brightness = self._brightness
                self._off_with_transition = update_params["off_with_transition"]

            # Note: If individual lights have off_with_transition set, but not the
            # group, and the group is then turned on without a level, individual lights
            # might fall back to brightness level 1.
            # Since all lights might need different brightness levels to be turned on,
            # we can't use one group call. And making individual calls when turning on
            # a ZHA group would cause a lot of traffic. In this case,
            # turn_on should either just be called with a level or individual turn_on
            # calls can be used.

            # state is always set (turn_on/turn_off)
            self._state = state

            # before assuming a group state attribute, check if the attribute
            # was actually set in that call
            if brightness is not None and brightness_supported(supported_modes):
                self._brightness = brightness
            if color_mode is not None and color_mode in supported_modes:
                self._color_mode = color_mode
            if color_temp is not None and ColorMode.COLOR_TEMP in supported_modes:
                self._color_temp = color_temp
            if xy_color is not None and ColorMode.XY in supported_modes:
                self._xy_color = xy_color
            if hs_color is not None and ColorMode.HS in supported_modes:
                self._hs_color = hs_color
            # the effect is always deactivated in async_turn_on if not provided
            if effect is None:
                self._effect = None
            elif self._effect_list and effect in self._effect_list:
                self._effect = effect

            self.maybe_emit_state_changed_event()

    def restore_external_state_attributes(
        self,
        *,
        state: bool | None,
        off_with_transition: bool | None,
        off_brightness: int | None,
        brightness: int | None,
        color_temp: int | None,
        xy_color: tuple[float, float] | None,
        hs_color: tuple[float, float] | None,
        color_mode: ColorMode | None,
        effect: str | None,
    ) -> None:
        """Restore extra state attributes that are stored outside of the ZCL cache."""
        if state is not None:
            self._state = state
        if off_with_transition is not None:
            self._off_with_transition = off_with_transition
        if off_brightness is not None:
            self._off_brightness = off_brightness
        if brightness is not None:
            self._brightness = brightness
        if color_temp is not None:
            self._color_temp = color_temp
        if xy_color is not None:
            self._xy_color = xy_color
        if hs_color is not None:
            self._hs_color = hs_color
        if color_mode is not None:
            self._color_mode = color_mode

        # Effect is always restored, as `None` indicates that no effect is active
        self._effect = effect


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF,
    aux_cluster_handlers={CLUSTER_HANDLER_COLOR, CLUSTER_HANDLER_LEVEL},
    manufacturers={"Philips", "Signify Netherlands B.V."},
)
class HueLight(Light):
    """Representation of a HUE light which does not report attributes."""

    _REFRESH_INTERVAL = (180, 300)


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF,
    aux_cluster_handlers={CLUSTER_HANDLER_COLOR, CLUSTER_HANDLER_LEVEL},
    manufacturers={"Jasco", "Jasco Products", "Quotra-Vision", "eWeLight", "eWeLink"},
)
class ForceOnLight(Light):
    """Representation of a light which does not respect on/off for move_to_level_with_on_off commands."""

    _FORCE_ON = True


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF,
    aux_cluster_handlers={CLUSTER_HANDLER_COLOR, CLUSTER_HANDLER_LEVEL},
    manufacturers=DEFAULT_MIN_TRANSITION_MANUFACTURERS,
)
class MinTransitionLight(Light):
    """Representation of a light which does not react to any "move to" calls with 0 as a transition."""

    # Transitions are counted in 1/10th of a second increments, so this is the smallest
    _DEFAULT_MIN_TRANSITION_TIME = 0.1


@GROUP_MATCH()
class LightGroup(GroupEntity, BaseLight):
    """Representation of a light group."""

    _attr_translation_key: str = "light_group"

    def __init__(self, group: Group):
        """Initialize a light group."""
        super().__init__(group)
        self._GROUP_SUPPORTS_EXECUTE_IF_OFF: bool = True

        for member in group.members:
            # Ensure we do not send group commands that violate the minimum transition
            # time of any members.
            if member.device.manufacturer in DEFAULT_MIN_TRANSITION_MANUFACTURERS:
                self._DEFAULT_MIN_TRANSITION_TIME = (
                    MinTransitionLight._DEFAULT_MIN_TRANSITION_TIME
                )

            # Check all group members to see if they support execute_if_off.
            # If at least one member has a color cluster and doesn't support it,
            # it's not used.
            for endpoint in member.device._endpoints.values():
                for cluster_handler in endpoint.all_cluster_handlers.values():
                    if (
                        cluster_handler.name == CLUSTER_HANDLER_COLOR
                        and not cluster_handler.execute_if_off_supported
                    ):
                        self._GROUP_SUPPORTS_EXECUTE_IF_OFF = False
                        break

        self._on_off_cluster_handler: ClusterHandler = group.zigpy_group.endpoint[
            OnOff.cluster_id
        ]
        self._level_cluster_handler: None | (
            ClusterHandler
        ) = group.zigpy_group.endpoint[LevelControl.cluster_id]
        self._color_cluster_handler: None | (
            ClusterHandler
        ) = group.zigpy_group.endpoint[Color.cluster_id]
        self._identify_cluster_handler: None | (
            ClusterHandler
        ) = group.zigpy_group.endpoint[Identify.cluster_id]
        self._debounced_member_refresh: Debouncer | None = None
        light_options = group.gateway.config.config.light_options
        self._zha_config_transition = light_options.default_light_transition
        self._zha_config_enable_light_transitioning_flag = (
            light_options.enable_light_transitioning_flag
        )
        self._zha_config_always_prefer_xy_color_mode = (
            light_options.always_prefer_xy_color_mode
        )
        self._zha_config_group_members_assume_state = (
            light_options.group_members_assume_state
        )
        if self._zha_config_group_members_assume_state:
            self._update_group_from_child_delay = ASSUME_UPDATE_GROUP_FROM_CHILD_DELAY
        self._zha_config_enhanced_light_transition = False

        self._color_mode = ColorMode.UNKNOWN
        self._supported_color_modes = {ColorMode.ONOFF}

        force_refresh_debouncer = Debouncer(
            self.group.gateway,
            _LOGGER,
            cooldown=3,
            immediate=True,
            function=self._force_member_updates,
        )
        self._debounced_member_refresh = force_refresh_debouncer
        if hasattr(self, "info_object"):
            delattr(self, "info_object")
        self.update()

    @functools.cached_property
    def info_object(self) -> LightEntityInfo:
        """Return a representation of the select."""
        return LightEntityInfo(
            **super().info_object.__dict__,
            effect_list=self.effect_list,
            supported_features=self.supported_features,
            min_mireds=self.min_mireds,
            max_mireds=self.max_mireds,
        )

    # remove this when all ZHA platforms and base entities are updated
    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self._available

    async def on_remove(self) -> None:
        """Cancel tasks this entity owns."""
        await super().on_remove()
        if self._debounced_member_refresh:
            self._debounced_member_refresh.async_cancel()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        # "off with transition" and "off brightness" will get overridden when
        # turning on the group, but they are needed for setting the assumed
        # member state correctly, so save them here
        off_brightness = self._off_brightness if self._off_with_transition else None
        await super().async_turn_on(**kwargs)
        if self._zha_config_group_members_assume_state:
            self._make_members_assume_group_state(True, kwargs, off_brightness)
        if self.is_transitioning:  # when transitioning, state is refreshed at the end
            return
        if self._debounced_member_refresh:
            await self._debounced_member_refresh.async_call()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await super().async_turn_off(**kwargs)
        if self._zha_config_group_members_assume_state:
            self._make_members_assume_group_state(False, kwargs)
        if self.is_transitioning:
            return
        if self._debounced_member_refresh:
            await self._debounced_member_refresh.async_call()

    def update(self, _: Any = None) -> None:
        """Query all members and determine the light group state."""
        self.debug("Updating light group entity state")
        platform_entities = self._group.get_platform_entities(self.PLATFORM)
        all_states = [entity.state for entity in platform_entities]
        states: list = list(filter(None, all_states))
        self.debug(
            "All platform entity states for group entity members: %s", all_states
        )
        on_states = [state for state in states if state["on"]]

        self._state = len(on_states) > 0

        # reset "off with transition" flag if any member is on
        if self._state:
            self._off_with_transition = False
            self._off_brightness = None

        self._available = any(
            platform_entity.device.available for platform_entity in platform_entities
        )

        self._brightness = reduce_attribute(on_states, ATTR_BRIGHTNESS)

        self._xy_color = reduce_attribute(on_states, ATTR_XY_COLOR, reduce=mean_tuple)

        if not self._zha_config_always_prefer_xy_color_mode:
            self._hs_color = reduce_attribute(
                on_states, ATTR_HS_COLOR, reduce=mean_tuple
            )

        self._color_temp = reduce_attribute(on_states, ATTR_COLOR_TEMP)
        self._min_mireds = reduce_attribute(
            states, ATTR_MIN_MIREDS, default=153, reduce=min
        )
        self._max_mireds = reduce_attribute(
            states, ATTR_MAX_MIREDS, default=500, reduce=max
        )

        self._effect_list = None
        all_effect_lists = list(find_state_attributes(states, ATTR_EFFECT_LIST))
        if all_effect_lists:
            # Merge all effects from all effect_lists with a union merge.
            self._effect_list = list(set().union(*all_effect_lists))

        self._effect = None
        all_effects = list(find_state_attributes(on_states, ATTR_EFFECT))
        if all_effects:
            # Report the most common effect.
            effects_count = Counter(itertools.chain(all_effects))
            self._effect = effects_count.most_common(1)[0][0]

        supported_color_modes = {ColorMode.ONOFF}
        all_supported_color_modes: list[set[ColorMode]] = list(
            find_state_attributes(states, ATTR_SUPPORTED_COLOR_MODES)
        )
        self._supported_color_modes = set().union(*all_supported_color_modes)

        if all_supported_color_modes:
            # Merge all color modes.
            self._external_supported_color_modes = supported_color_modes = (
                filter_supported_color_modes(set().union(*all_supported_color_modes))
            )

        self._color_mode = ColorMode.UNKNOWN
        all_color_modes = list(find_state_attributes(on_states, ATTR_COLOR_MODE))
        if all_color_modes:
            # Report the most common color mode, select brightness and onoff last
            color_mode_count = Counter(itertools.chain(all_color_modes))
            if ColorMode.ONOFF in color_mode_count:
                if ColorMode.ONOFF in supported_color_modes:
                    color_mode_count[ColorMode.ONOFF] = -1
                else:
                    color_mode_count.pop(ColorMode.ONOFF)
            if ColorMode.BRIGHTNESS in color_mode_count:
                if ColorMode.BRIGHTNESS in supported_color_modes:
                    color_mode_count[ColorMode.BRIGHTNESS] = 0
                else:
                    color_mode_count.pop(ColorMode.BRIGHTNESS)
            if color_mode_count:
                self._color_mode = color_mode_count.most_common(1)[0][0]
            else:
                self._color_mode = next(iter(supported_color_modes))

            if self._color_mode == ColorMode.HS and (
                color_mode_count[ColorMode.HS] != len(self._group.members)
                or self._zha_config_always_prefer_xy_color_mode
            ):  # switch to XY if all members do not support HS
                self._color_mode = ColorMode.XY

        self._supported_features = LightEntityFeature(0)
        for support in find_state_attributes(states, ATTR_SUPPORTED_FEATURES):
            # Merge supported features by emulating support for every feature
            # we find.
            self._supported_features |= support
        # Bitwise-and the supported features with the GroupedLight's features
        # so that we don't break in the future when a new feature is added.
        self._supported_features &= SUPPORT_GROUP_LIGHT
        self.maybe_emit_state_changed_event()

    async def _force_member_updates(self) -> None:
        """Force the update of members to ensure the states are correct for bulbs that don't report their state."""
        for platform_entity in self.group.get_platform_entities(Light.PLATFORM):
            await platform_entity.async_update()

    def _make_members_assume_group_state(
        self, state, service_kwargs, off_brightness=None
    ) -> None:
        """Send an assume event to all members of the group."""
        update_params = {
            "state": state,
            "off_with_transition": self._off_with_transition,
        }

        # check if the parameters were actually updated
        # in the service call before updating members
        if ATTR_BRIGHTNESS in service_kwargs:  # or off brightness
            update_params[ATTR_BRIGHTNESS] = self._brightness
        elif off_brightness is not None:
            # if we turn on the group light with "off brightness",
            # pass that to the members
            update_params[ATTR_BRIGHTNESS] = off_brightness

        if ATTR_COLOR_TEMP in service_kwargs:
            update_params[ATTR_COLOR_MODE] = self._color_mode
            update_params[ATTR_COLOR_TEMP] = self._color_temp

        if ATTR_XY_COLOR in service_kwargs:
            update_params[ATTR_COLOR_MODE] = self._color_mode
            update_params[ATTR_XY_COLOR] = self._xy_color

        if ATTR_HS_COLOR in service_kwargs:
            update_params[ATTR_COLOR_MODE] = self._color_mode
            update_params[ATTR_HS_COLOR] = self._hs_color

        if ATTR_EFFECT in service_kwargs:
            update_params[ATTR_EFFECT] = self._effect

        for platform_entity in self.group.get_platform_entities(Light.PLATFORM):
            platform_entity._assume_group_state(update_params)

    def restore_external_state_attributes(
        self,
        *,
        state: bool | None,
        off_with_transition: bool | None,
        off_brightness: int | None,
        brightness: int | None,
        color_temp: int | None,
        xy_color: tuple[float, float] | None,
        hs_color: tuple[float, float] | None,
        color_mode: ColorMode | None,
        effect: str | None,
    ) -> None:
        """Restore extra state attributes."""
        # Groups do not restore external state attributes
