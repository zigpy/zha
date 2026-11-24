"""Access to zigpy's per-device key/value store."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re
from typing import TYPE_CHECKING, Any, Final

from zigpy.store import DEFAULT_VERSION, DeviceStore, JSONValue, StoredValue

if TYPE_CHECKING:
    from zigpy.device import BaseDevice as ZigpyBaseDevice
    from zigpy.store import StoreNamespace

    from zha.application import Platform

# Restore records of entities, keyed by `entity_state_key`
ENTITY_STATE_NAMESPACE: Final = "zha.entity_state"

# Device values: state of a device that is not a ZCL attribute, such as a Tuya
# datapoint, written by quirks and shown by value-backed entities
DEVICE_VALUES_NAMESPACE: Final = "device_values"

# Writes a device value to the device: `writer(device, value)`, with the zigpy device.
# A quirk gives one to a writable device value entity. The writer decides when the
# value is set in the store: the Tuya writer stores it when it builds the command,
# like its attribute path; a transport with acknowledgements may store after them.
# Its errors propagate to the caller of the entity's write.
type DeviceValueWriter[T] = Callable[[ZigpyBaseDevice, T], Awaitable[None]]

# Joins the parts of keys built by `store_key`, which no part may contain
STORE_KEY_SEPARATOR: Final = "/"

# What `store_key` renders an integer part as, which string parts may not look like
_INT_PART_RE: Final = re.compile(r"0x[0-9a-f]{4,}")

_EUI64_RE: Final = re.compile(r"(?:[0-9a-f]{2}:){7}[0-9a-f]{2}")


def get_device_store(zigpy_device: ZigpyBaseDevice) -> DeviceStore | None:
    """Return the device's store, or `None` if there is no store."""
    store = getattr(zigpy_device, "store", None)

    # Tests construct devices on mocked applications, whose stores are mocks too
    if not isinstance(store, DeviceStore):
        return None

    return store


def store_diagnostics(zigpy_device: ZigpyBaseDevice) -> dict[str, Any]:
    """Return the contents of the device's store for diagnostics, by namespace.

    Keys can contain the device's IEEE address (entity restore records are keyed by
    unique ID) and those of other devices (the destination of a binding). Home
    Assistant redacts diagnostics by key name only, so addresses are replaced here:
    the device's own by `<ieee>`, others by `<ieee N>`, numbered in order of
    appearance so that keys stay distinct.
    """
    store = get_device_store(zigpy_device)

    if store is None:
        return {}

    replacements = {str(zigpy_device.ieee): "<ieee>"}

    def redact(key: str) -> str:
        def replace(match: re.Match[str]) -> str:
            ieee = match.group(0)

            if ieee not in replacements:
                replacements[ieee] = f"<ieee {len(replacements)}>"

            return replacements[ieee]

        return _EUI64_RE.sub(replace, key)

    return {
        namespace.name: {
            redact(key): {
                "value": item.value,
                "version": item.version,
                "last_updated": item.last_updated.isoformat(),
            }
            for key, item in sorted(namespace.items())
        }
        for namespace in sorted(store.namespaces(), key=lambda ns: ns.name)
        if len(namespace) > 0
    }


def get_store_namespace(
    zigpy_device: ZigpyBaseDevice, namespace: str
) -> StoreNamespace | None:
    """Return a namespace of the device's store, or `None` if there is no store."""
    store = get_device_store(zigpy_device)

    if store is None:
        return None

    return store.namespace(namespace)


def device_value[T](
    key: str,
    type: Callable[[JSONValue], T],
    *,
    encode: Callable[[T], JSONValue] | None = None,
    version: int = DEFAULT_VERSION,
    migrate: Callable[[int, JSONValue], JSONValue | None] | None = None,
) -> StoredValue[T]:
    """Declare a device value: a typed key in the device values namespace.

    The key is part of the API of every entity showing the value, so it should name
    the quantity (`rain_intensity`), not where it comes from (a datapoint number).
    """
    if encode is None:
        return StoredValue(
            namespace=DEVICE_VALUES_NAMESPACE,
            key=key,
            type=type,
            version=version,
            migrate=migrate,
        )

    return StoredValue(
        namespace=DEVICE_VALUES_NAMESPACE,
        key=key,
        type=type,
        encode=encode,
        version=version,
        migrate=migrate,
    )


def store_key(*parts: str | int | None) -> str:
    """Build a store key from structured parts.

    Every key with more than one part must be built here, never by formatting a
    string, and every part is rendered so that it decodes back to one value: integers
    as `0x` and at least four hex digits, `None` as `-`, strings as they are. A string
    part must be non-empty, must not contain the separator, and must not look like an
    integer or `None` part, so a string and an integer never render the same. A prefix
    of whole parts then matches only keys that have those parts (`0x0001/` does not
    match `0x0010/`).
    """
    if not parts:
        raise ValueError("A store key needs at least one part")

    rendered = []

    for part in parts:
        if part is None:
            rendered.append("-")
        elif isinstance(part, bool):
            raise TypeError(f"Boolean store key part: {part!r}")
        elif isinstance(part, int):
            if part < 0:
                raise ValueError(f"Negative store key part: {part}")

            rendered.append(f"0x{part:04x}")
        elif (
            not part
            or STORE_KEY_SEPARATOR in part
            or part == "-"
            or _INT_PART_RE.fullmatch(part)
        ):
            raise ValueError(f"Invalid store key part: {part!r}")
        else:
            rendered.append(part)

    return STORE_KEY_SEPARATOR.join(rendered)


def entity_state_key(platform: Platform, unique_id: str) -> str:
    """Return the store key of an entity's restore record.

    Unique IDs are only unique within a platform, so the key carries both. Platform
    names never contain the separator.
    """
    return f"{platform}/{unique_id}"
