"""Helpers for the light platform."""

from __future__ import annotations

from collections.abc import Iterable

from zigpy.zcl.clusters.lighting import ColorMode as ZclColorMode

from zha.application.platforms.light.const import COLOR_MODES_BRIGHTNESS, ColorMode
from zha.exceptions import ZHAException

ZCL_TO_ENTITY_COLOR_MODE = {
    None: ColorMode.UNKNOWN,
    ZclColorMode.Hue_and_saturation: ColorMode.HS,
    ZclColorMode.X_and_Y: ColorMode.XY,
    ZclColorMode.Color_temperature: ColorMode.COLOR_TEMP,
}

ENTITY_TO_ZCL_COLOR_MODE = {v: k for k, v in ZCL_TO_ENTITY_COLOR_MODE.items()}


def filter_supported_color_modes(color_modes: Iterable[ColorMode]) -> set[ColorMode]:
    """Filter the given color modes."""
    color_modes = set(color_modes)
    if not color_modes or ColorMode.UNKNOWN in color_modes:
        raise ZHAException

    if ColorMode.ONOFF in color_modes and len(color_modes) > 1:
        color_modes.remove(ColorMode.ONOFF)
    if ColorMode.BRIGHTNESS in color_modes and len(color_modes) > 1:
        color_modes.remove(ColorMode.BRIGHTNESS)
    return color_modes


def brightness_supported(color_modes: Iterable[ColorMode | str] | None) -> bool:
    """Test if brightness is supported."""
    if not color_modes:
        return False
    return not COLOR_MODES_BRIGHTNESS.isdisjoint(color_modes)
