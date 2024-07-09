"""Entity helpers for the zhaws server."""

from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from zha.application.platforms.binary_sensor.const import BinarySensorDeviceClass
    from zha.application.platforms.number.const import NumberDeviceClass
    from zha.application.platforms.sensor.const import SensorDeviceClass


@overload
def validate_device_class(
    device_class_enum: type[BinarySensorDeviceClass],
    metadata_value,
    platform: str,
    logger: logging.Logger,
) -> BinarySensorDeviceClass | None: ...


@overload
def validate_device_class(
    device_class_enum: type[SensorDeviceClass],
    metadata_value,
    platform: str,
    logger: logging.Logger,
) -> SensorDeviceClass | None: ...


@overload
def validate_device_class(
    device_class_enum: type[NumberDeviceClass],
    metadata_value,
    platform: str,
    logger: logging.Logger,
) -> NumberDeviceClass | None: ...


def validate_device_class(
    device_class_enum: type[BinarySensorDeviceClass]
    | type[SensorDeviceClass]
    | type[NumberDeviceClass],
    metadata_value: enum.Enum,
    platform: str,
    logger: logging.Logger,
) -> BinarySensorDeviceClass | SensorDeviceClass | NumberDeviceClass | None:
    """Validate and return a device class."""
    try:
        return device_class_enum(metadata_value.value)
    except ValueError as ex:
        logger.warning(
            "Quirks provided an invalid device class: %s for platform %s: %s",
            metadata_value,
            platform,
            ex,
        )
        return None
