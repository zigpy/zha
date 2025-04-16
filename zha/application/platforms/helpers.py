"""Entity helpers for the zhaws server."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import enum
import logging
from typing import TYPE_CHECKING, Any, overload

from zigpy.zcl import Cluster

from zha.application.const import UniqueIdMigration, UniqueIdRoot

if TYPE_CHECKING:
    from zha.application.platforms.binary_sensor.const import BinarySensorDeviceClass
    from zha.application.platforms.number.const import NumberDeviceClass
    from zha.application.platforms.sensor.const import SensorDeviceClass
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


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


@overload
def validate_device_class(
    device_class_enum: type[BinarySensorDeviceClass],
    metadata_value: enum.Enum,
    platform: str,
    logger: logging.Logger,
) -> BinarySensorDeviceClass | None: ...


@overload
def validate_device_class(
    device_class_enum: type[SensorDeviceClass],
    metadata_value: enum.Enum,
    platform: str,
    logger: logging.Logger,
) -> SensorDeviceClass | None: ...


@overload
def validate_device_class(
    device_class_enum: type[NumberDeviceClass],
    metadata_value: enum.Enum,
    platform: str,
    logger: logging.Logger,
) -> NumberDeviceClass | None: ...


def validate_device_class(
    device_class_enum: (
        type[BinarySensorDeviceClass]
        | type[SensorDeviceClass]
        | type[NumberDeviceClass]
    ),
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


def format_legacy_platform_unique_id(
    migration_type: UniqueIdMigration,
    device: Device,
    endpoint: Endpoint,
    cluster: Cluster,
    suffix: str,
) -> str:
    """Create a unique ID based on the provided information."""
    if suffix != "":
        suffix = "-" + suffix

    match migration_type:
        case UniqueIdMigration.LEGACY_CLUSTER:
            assert endpoint is not None
            assert cluster is not None
            return f"{device.ieee}-{endpoint.id}-{cluster.cluster_id}{suffix}"
        case UniqueIdMigration.LEGACY_ENDPOINT:
            assert endpoint is not None
            return f"{device.ieee}-{endpoint.id}{suffix}"
        case _:
            raise ValueError(
                f"Invalid migration type: {migration_type}"
            )  # pragma: no cover


def format_platform_unique_id(
    root: UniqueIdRoot,
    device: Device,
    endpoint: Endpoint,
    cluster: Cluster,
    suffix: str,
) -> str:
    """Create a unique ID based on the provided information."""
    if suffix != "":
        suffix = "-" + suffix

    match root:
        case UniqueIdRoot.CLUSTER:
            assert endpoint is not None
            assert cluster is not None
            return f"{device.ieee}-{endpoint.id}-0x{cluster.cluster_id:04x}{suffix}"
        case UniqueIdRoot.ENDPOINT:
            assert endpoint is not None
            return f"{device.ieee}-{endpoint.id}{suffix}"
        case UniqueIdRoot.DEVICE:
            return f"{device.ieee}{suffix}"
        case _:
            raise ValueError(f"Invalid unique_id_root: {root}")  # pragma: no cover
