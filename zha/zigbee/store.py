"""Access to zigpy's per-device key/value store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from zigpy.store import DeviceStore

if TYPE_CHECKING:
    from zigpy.device import BaseDevice as ZigpyBaseDevice
    from zigpy.store import StoreNamespace

    from zha.application import Platform

# Restore records of entities, keyed by `entity_state_key`
ENTITY_STATE_NAMESPACE: Final = "zha.entity_state"


def get_store_namespace(
    zigpy_device: ZigpyBaseDevice, namespace: str
) -> StoreNamespace | None:
    """Return a namespace of the device's store, or `None` if there is no store."""
    store = getattr(zigpy_device, "store", None)

    # Tests construct devices on mocked applications, whose stores are mocks too
    if not isinstance(store, DeviceStore):
        return None

    return store.namespace(namespace)


def entity_state_key(platform: Platform, unique_id: str) -> str:
    """Return the store key of an entity's restore record.

    Unique IDs are only unique within a platform, so the key carries both. Platform
    names never contain the separator.
    """
    return f"{platform}/{unique_id}"
