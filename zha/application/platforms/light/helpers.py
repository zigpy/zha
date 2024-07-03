"""Helpers for the light platform."""

from __future__ import annotations

from collections.abc import Iterable

from zha.application.platforms.light.const import COLOR_MODES_BRIGHTNESS, ColorMode
from zha.exceptions import ZHAException


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
