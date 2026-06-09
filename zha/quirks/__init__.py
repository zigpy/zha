"""Quirks support for ZHA.

This package owns the matching, registration and dispatch of quirked `Device`
subclasses. A quirk is a `zha.zigbee.device.Device` subclass decorated with
`@register_device`: its `_device_match` decides which zigpy devices it wraps,
its `_zigpy_ops` describe the modifications applied to the zigpy device during
resolution, and everything else (entities, triggers, alerts, configuration) is
expressed by overriding the `Device` class itself.

`resolve_device` is registered with zigpy as the application's device resolver.
It is handed a freshly-constructed zigpy device exactly once (on join and on
database load), applies the matching quirk's zigpy-level modifications, and
falls back to zigpy's legacy v1/v2 quirks registry when no ZHA quirk matches.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

import zigpy.device
import zigpy.profiles.zha
import zigpy.quirks
from zigpy.zcl import Cluster, ClusterType
from zigpy.zcl.clusters.general import Ota
from zigpy.zcl.foundation import ZCLAttributeDef
from zigpy.zdo.types import NodeDescriptor

if TYPE_CHECKING:
    from zha.zigbee.device import Device

_LOGGER = logging.getLogger(__name__)

FilterType = Callable[[zigpy.device.Device], bool]

# Attribute stamped onto a zigpy device by `resolve_device` so that
# `Device.new` dispatches to the class that already matched during resolution,
# instead of running a second, potentially divergent, match pass.
ZHA_DEVICE_CLASS_ATTRIBUTE = "zha_device_class"


class ModelInfo(NamedTuple):
    """A (manufacturer, model) pair to match. `None` is a wildcard."""

    manufacturer: str | None
    model: str | None


def _read_current_firmware_version(
    zigpy_device: zigpy.device.Device,
) -> int | None:
    """Read `current_file_version` from the device's OTA cluster, or None."""
    try:
        ota = zigpy_device.find_cluster(
            cluster_id=Ota.cluster_id, cluster_type=ClusterType.Client
        )
    except ValueError:
        return None
    return ota.get(Ota.AttributeDefs.current_file_version.id)


@dataclass(frozen=True)
class DeviceMatch:
    """Criteria matching a `Device` subclass to a zigpy device.

    A device matches when any `applies_to` pair matches, all `filters` pass,
    and the firmware version (when filtered on) is within
    `[firmware_version_min, firmware_version_max)`.
    """

    applies_to: tuple[ModelInfo, ...]
    filters: tuple[FilterType, ...] = ()
    firmware_version_min: int | None = None
    firmware_version_max: int | None = None
    firmware_version_allow_missing: bool = True

    def matches(self, zigpy_device: zigpy.device.Device) -> bool:
        """Return True if `zigpy_device` satisfies all criteria."""
        if not any(
            (manufacturer is None or manufacturer == zigpy_device.manufacturer)
            and (model is None or model == zigpy_device.model)
            for manufacturer, model in self.applies_to
        ):
            return False

        if not all(matcher(zigpy_device) for matcher in self.filters):
            return False

        if (
            self.firmware_version_min is not None
            or self.firmware_version_max is not None
        ):
            current = _read_current_firmware_version(zigpy_device)
            if current is None:
                return self.firmware_version_allow_missing
            if self.firmware_version_min is not None and (
                current < self.firmware_version_min
            ):
                return False
            if self.firmware_version_max is not None and (
                current >= self.firmware_version_max
            ):
                return False

        return True


class ZigpyOp(Protocol):
    """A single modification applied to a zigpy device during resolution."""

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""


@dataclass(frozen=True)
class AddCluster:
    """Add a cluster to an endpoint.

    `cluster` is either a bare cluster id or a `Cluster` subclass. When
    `constant_attributes` is provided (mapping `ZCLAttributeDef` to value), the
    values are served by the cluster without contacting the device; this
    requires `cluster` to be a `CustomCluster` subclass.
    """

    cluster: int | type[Cluster]
    endpoint_id: int = 1
    cluster_type: ClusterType = ClusterType.Server
    constant_attributes: dict[ZCLAttributeDef, Any] = field(default_factory=dict)

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        endpoint = device.endpoints[self.endpoint_id]
        is_server = self.cluster_type == ClusterType.Server

        if isinstance(self.cluster, int):
            cluster = None
            cluster_id = self.cluster
        else:
            cluster = self.cluster(endpoint, is_server=is_server)
            cluster_id = cluster.cluster_id

        if is_server:
            cluster = endpoint.add_input_cluster(cluster_id, cluster)
        else:
            cluster = endpoint.add_output_cluster(cluster_id, cluster)

        if self.constant_attributes:
            cluster._CONSTANT_ATTRIBUTES = {
                attribute.id: value
                for attribute, value in self.constant_attributes.items()
            }


@dataclass(frozen=True)
class RemoveCluster:
    """Remove a cluster from an endpoint."""

    cluster_id: int
    endpoint_id: int = 1
    cluster_type: ClusterType = ClusterType.Server

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        endpoint = device.endpoints[self.endpoint_id]
        if self.cluster_type == ClusterType.Server:
            endpoint.in_clusters.pop(self.cluster_id, None)
        else:
            endpoint.out_clusters.pop(self.cluster_id, None)


@dataclass(frozen=True)
class ReplaceCluster:
    """Replace a cluster on an endpoint with a `Cluster` subclass.

    `cluster_id` identifies the cluster to remove and defaults to the
    replacement's own cluster id. Cached attribute values of the replaced
    cluster (e.g. restored from the database) carry over to the replacement.
    """

    cluster: type[Cluster]
    cluster_id: int | None = None
    endpoint_id: int = 1
    cluster_type: ClusterType = ClusterType.Server

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        endpoint = device.endpoints[self.endpoint_id]
        is_server = self.cluster_type == ClusterType.Server
        removed_cluster_id = (
            self.cluster.cluster_id if self.cluster_id is None else self.cluster_id
        )

        if is_server:
            old_cluster = endpoint.in_clusters.pop(removed_cluster_id, None)
        else:
            old_cluster = endpoint.out_clusters.pop(removed_cluster_id, None)

        new_cluster = self.cluster(endpoint, is_server=is_server)
        if is_server:
            endpoint.add_input_cluster(new_cluster.cluster_id, new_cluster)
        else:
            endpoint.add_output_cluster(new_cluster.cluster_id, new_cluster)

        if old_cluster is not None:
            new_cluster._attr_cache_internal = old_cluster._attr_cache.clone(
                new_cluster
            )


@dataclass(frozen=True)
class ReplaceClusterOccurrences:
    """Replace a cluster with a `Cluster` subclass on every endpoint."""

    cluster: type[Cluster]
    cluster_types: tuple[ClusterType, ...] = (ClusterType.Server, ClusterType.Client)

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        for endpoint in device.non_zdo_endpoints:
            if (
                ClusterType.Server in self.cluster_types
                and self.cluster.cluster_id in endpoint.in_clusters
            ):
                ReplaceCluster(
                    cluster=self.cluster,
                    endpoint_id=endpoint.endpoint_id,
                    cluster_type=ClusterType.Server,
                ).apply(device)
            if (
                ClusterType.Client in self.cluster_types
                and self.cluster.cluster_id in endpoint.out_clusters
            ):
                ReplaceCluster(
                    cluster=self.cluster,
                    endpoint_id=endpoint.endpoint_id,
                    cluster_type=ClusterType.Client,
                ).apply(device)


@dataclass(frozen=True)
class AddEndpoint:
    """Add an endpoint to a device, if it does not already exist."""

    endpoint_id: int
    profile_id: int = zigpy.profiles.zha.PROFILE_ID
    device_type: int = 0xFF

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        if self.endpoint_id in device.endpoints:
            return
        endpoint = device.add_endpoint(self.endpoint_id)
        endpoint.profile_id = self.profile_id
        endpoint.device_type = self.device_type


@dataclass(frozen=True)
class RemoveEndpoint:
    """Remove an endpoint from a device."""

    endpoint_id: int

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        device.endpoints.pop(self.endpoint_id, None)


@dataclass(frozen=True)
class ReplaceEndpoint:
    """Set the profile and device type of an endpoint, creating it if needed."""

    endpoint_id: int
    profile_id: int = zigpy.profiles.zha.PROFILE_ID
    device_type: int = 0xFF

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        if self.endpoint_id in device.endpoints:
            endpoint = device.endpoints[self.endpoint_id]
        else:
            endpoint = device.add_endpoint(self.endpoint_id)
        endpoint.profile_id = self.profile_id
        endpoint.device_type = self.device_type


@dataclass(frozen=True)
class SetNodeDescriptor:
    """Replace the node descriptor of a device."""

    node_descriptor: NodeDescriptor

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        device.node_desc = self.node_descriptor.freeze()


@dataclass(frozen=True)
class SetModelInfo:
    """Override the manufacturer and/or model of a device."""

    manufacturer: str | None = None
    model: str | None = None

    def apply(self, device: zigpy.device.Device) -> None:
        """Apply this operation to the given zigpy device."""
        if self.manufacturer is not None:
            device.manufacturer = self.manufacturer
        if self.model is not None:
            device.model = self.model


class DeviceRegistry:
    """Registry of quirked `Device` subclasses, keyed by (manufacturer, model)."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._registry: defaultdict[ModelInfo, list[type[Device]]] = defaultdict(list)

    def register(self, cls: type[Device]) -> type[Device]:
        """Add a `Device` subclass to the registry."""
        match = cls._device_match
        if match is None:
            raise ValueError(f"{cls!r} does not define `_device_match`")
        if not match.applies_to:
            raise ValueError(f"{cls!r} must apply to at least one model")
        for manufacturer, model in match.applies_to:
            if manufacturer is None and model is None:
                raise ValueError(
                    f"{cls!r} must specify a manufacturer and/or model to match"
                )
            # Most recently registered quirks take precedence, so quirks loaded
            # from the custom quirks directory override built-in ones.
            self._registry[ModelInfo(manufacturer, model)].insert(0, cls)
        return cls

    def get(self, zigpy_device: zigpy.device.Device) -> type[Device] | None:
        """Return the first registered class matching `zigpy_device`."""
        for key in (
            ModelInfo(zigpy_device.manufacturer, zigpy_device.model),
            ModelInfo(zigpy_device.manufacturer, None),
            ModelInfo(None, zigpy_device.model),
        ):
            for cls in self._registry[key]:
                if cls._device_match.matches(zigpy_device):
                    return cls
        return None

    def remove(self, cls: type[Device]) -> None:
        """Remove a `Device` subclass from the registry."""
        for manufacturer, model in cls._device_match.applies_to:
            self._registry[ModelInfo(manufacturer, model)].remove(cls)

    def purge_custom_quirks(self, custom_quirks_root: Path) -> None:
        """Remove quirks loaded from the custom quirks directory."""
        for classes in self._registry.values():
            for cls in list(classes):
                if (
                    cls._quirk_definition is not None
                    and cls._quirk_definition.quirk_file is not None
                ):
                    quirk_file = Path(cls._quirk_definition.quirk_file)
                else:
                    module = inspect.getmodule(cls)
                    quirk_file = Path(module.__file__)

                if quirk_file.is_relative_to(custom_quirks_root):
                    _LOGGER.debug("Removing stale custom quirk: %s", cls)
                    classes.remove(cls)


DEVICE_REGISTRY = DeviceRegistry()


def register_device(cls: type[Device]) -> type[Device]:
    """Class decorator registering a `Device` subclass as a quirk."""
    return DEVICE_REGISTRY.register(cls)


def _snapshot_zigpy_device(zigpy_device: zigpy.device.Device) -> tuple:
    """Capture the device state that quirk operations can modify."""
    return (
        zigpy_device.manufacturer,
        zigpy_device.model,
        zigpy_device.node_desc,
        dict(zigpy_device.endpoints),
        {
            endpoint.endpoint_id: (
                endpoint.profile_id,
                endpoint.device_type,
                dict(endpoint.in_clusters),
                dict(endpoint.out_clusters),
            )
            for endpoint in zigpy_device.non_zdo_endpoints
        },
    )


def _restore_zigpy_device(zigpy_device: zigpy.device.Device, snapshot: tuple) -> None:
    """Restore device state captured by `_snapshot_zigpy_device`."""
    manufacturer, model, node_desc, endpoints, endpoint_state = snapshot
    zigpy_device._manufacturer = manufacturer
    zigpy_device._model = model
    zigpy_device.node_desc = node_desc
    zigpy_device.endpoints.clear()
    zigpy_device.endpoints.update(endpoints)
    for endpoint_id, (
        profile_id,
        device_type,
        in_clusters,
        out_clusters,
    ) in endpoint_state.items():
        endpoint = zigpy_device.endpoints[endpoint_id]
        endpoint.profile_id = profile_id
        endpoint.device_type = device_type
        endpoint.in_clusters.clear()
        endpoint.in_clusters.update(in_clusters)
        endpoint.out_clusters.clear()
        endpoint.out_clusters.update(out_clusters)


def resolve_device(zigpy_device: zigpy.device.Device) -> zigpy.device.Device:
    """Resolve a freshly-constructed zigpy device into its final object.

    Registered with zigpy as the application's device resolver. The matching
    quirk class applies its zigpy-level modifications (and may return a
    replacement device object); the class is then stamped onto the zigpy
    device so `Device.new` dispatches to it without a second match pass.

    Devices without a matching ZHA quirk go through zigpy's legacy v1/v2
    quirks registry instead.
    """
    # Resolution is idempotent: an already-quirked device is returned as-is
    # (re-applying in-place operations would clobber cluster state).
    if hasattr(zigpy_device, ZHA_DEVICE_CLASS_ATTRIBUTE):
        return zigpy_device

    quirk_cls = DEVICE_REGISTRY.get(zigpy_device)
    if quirk_cls is None:
        return zigpy.quirks.get_device(zigpy_device)

    _LOGGER.debug(
        "Resolved %s/%s (%s) to quirk %s",
        zigpy_device.manufacturer,
        zigpy_device.model,
        zigpy_device.ieee,
        quirk_cls.__name__,
    )

    # A quirk that fails to apply leaves the device unquirked, matching the
    # zigpy registry's behavior. Operations apply in place, so the prior state
    # is restored on failure.
    snapshot = _snapshot_zigpy_device(zigpy_device)
    try:
        resolved = quirk_cls.apply_to_zigpy_device(zigpy_device)
    except Exception:  # noqa: BLE001
        _restore_zigpy_device(zigpy_device, snapshot)
        _LOGGER.exception(
            "Failed to apply quirk %s to %r. This is a bug, please report it",
            quirk_cls.__name__,
            zigpy_device,
        )
        return zigpy_device

    setattr(resolved, ZHA_DEVICE_CLASS_ATTRIBUTE, quirk_cls)
    return resolved
