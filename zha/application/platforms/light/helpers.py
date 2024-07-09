"""Helpers for the light platform."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

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


def find_state_attributes(states: list[dict], key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        if (value := state.get(key)) is not None:
            yield value


def mean_int(*args: Any) -> int:
    """Return the mean of the supplied values."""
    return int(sum(args) / len(args))


def mean_tuple(*args: Any) -> tuple:
    """Return the mean values along the columns of the supplied values."""
    return tuple(sum(x) / len(x) for x in zip(*args))


def reduce_attribute(
    states: list[dict],
    key: str,
    default: Any | None = None,
    reduce: Callable[..., Any] = mean_int,
) -> Any:
    """Find the first attribute matching key from states.

    If none are found, return default.
    """
    attrs = list(find_state_attributes(states, key))

    if not attrs:
        return default

    if len(attrs) == 1:
        return attrs[0]

    return reduce(*attrs)
