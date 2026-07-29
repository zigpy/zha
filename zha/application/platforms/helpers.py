"""Entity helpers for the zhaws server."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from enum import StrEnum
import logging
from typing import Any

from zha.application.platforms import BaseEntityState


def find_state_attributes(states: list[BaseEntityState], key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        if (value := getattr(state, key, None)) is not None:
            yield value


def mean_int(*args: Any) -> int:
    """Return the mean of the supplied values."""
    return int(sum(args) / len(args))


def mean_tuple(*args: Any) -> tuple:
    """Return the mean values along the columns of the supplied values."""
    return tuple(sum(x) / len(x) for x in zip(*args))


def reduce_attribute(
    states: list[BaseEntityState],
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


def validate_device_class[DeviceClassT: StrEnum](
    device_class_enum: type[DeviceClassT],
    metadata_value: StrEnum,
    platform: str,
    logger: logging.Logger,
) -> DeviceClassT | None:
    """Validate and return a device class."""
    try:
        return device_class_enum(metadata_value)
    except ValueError as ex:
        logger.warning(
            "Quirks provided an invalid device class: %s for platform %s: %s",
            metadata_value,
            platform,
            ex,
        )
        return None
