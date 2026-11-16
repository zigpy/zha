"""Access to zigpy's per-device key/value store."""

from __future__ import annotations

from collections.abc import Callable
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


def get_device_store(zigpy_device: ZigpyBaseDevice) -> DeviceStore | None:
    """Return the device's store, or `None` if there is no store."""
    store = getattr(zigpy_device, "store", None)

    # Tests construct devices on mocked applications, whose stores are mocks too
    if not isinstance(store, DeviceStore):
        return None

    return store


def store_diagnostics(zigpy_device: ZigpyBaseDevice) -> dict[str, Any]:
    """Return the contents of the device's store for diagnostics, by namespace."""
    store = get_device_store(zigpy_device)

    if store is None:
        return {}

    return {
        namespace.name: {
            key: {
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


def entity_state_key(platform: Platform, unique_id: str) -> str:
    """Return the store key of an entity's restore record.

    Unique IDs are only unique within a platform, so the key carries both. Platform
    names never contain the separator.
    """
    return f"{platform}/{unique_id}"
