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
from dataclasses import dataclass
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import zigpy.device
import zigpy.profiles.zha
import zigpy.quirks
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Ota

if TYPE_CHECKING:
    from zha.zigbee.device import Device

_LOGGER = logging.getLogger(__name__)

QUIRK_REGISTRY_ENTRY_ATTR = "_quirk_registry_entry"
FilterType = Callable[[zigpy.device.Device], bool]

DEVICE_REGISTRY: DeviceRegistry


class ModelInfo(NamedTuple):
    """A (manufacturer, model) pair to match. `None` is a wildcard."""

    manufacturer: str | None
    model: str | None


def _read_current_firmware_version(zigpy_device: zigpy.device.Device) -> int | None:
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
        if self.applies_to and not any(
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


@dataclass(frozen=True)
class QuirkSource:
    """Where a quirk is defined: provenance for diagnostics and custom-quirk purging."""

    module: str
    file: str | None
    line: int | None
    label: str

    @classmethod
    def from_class(cls, target: type) -> QuirkSource:
        """Derive provenance from a hand-written quirk class."""
        return cls(
            module=target.__module__,
            file=inspect.getsourcefile(target),
            line=inspect.getsourcelines(target)[1],
            label=target.__qualname__,
        )


def make_zigpy_device_replacement(
    device_cls: type[zigpy.device.Device],
) -> Callable[[zigpy.device.Device], zigpy.device.Device]:
    """Return a transform wrapping a device in `device_cls` (a `BaseCustomDevice`)."""

    def _replace(device: zigpy.device.Device) -> zigpy.device.Device:
        return device_cls(device.application, device.ieee, device.nwk, device)

    return _replace


@dataclass(frozen=True)
class QuirkRegistryEntry:
    """A registered quirk: how to match, mutate, build and locate a device."""

    device_match: DeviceMatch
    zigpy_transforms: tuple[
        Callable[[zigpy.device.Device], zigpy.device.Device], ...
    ] = ()
    zha_device_factory: Callable[..., Device] | None = None
    source: QuirkSource | None = None


class DeviceRegistry:
    """Registry of quirk entries, keyed by (manufacturer, model)."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._registry: defaultdict[ModelInfo, list[QuirkRegistryEntry]] = defaultdict(
            list
        )

    def register(self, entry: QuirkRegistryEntry) -> QuirkRegistryEntry:
        """Add a quirk entry to the registry."""
        for manufacturer, model in entry.device_match.applies_to:
            if manufacturer is None and model is None:
                raise ValueError(
                    f"{entry!r} must specify a manufacturer and/or model to match"
                )

            # Most recently registered quirks take precedence, so quirks loaded
            # from the custom quirks directory override built-in ones.
            self._registry[ModelInfo(manufacturer, model)].insert(0, entry)

        return entry

    def get(self, zigpy_device: zigpy.device.Device) -> QuirkRegistryEntry | None:
        """Return the first registered entry matching `zigpy_device`."""
        for key in (
            ModelInfo(zigpy_device.manufacturer, zigpy_device.model),
            ModelInfo(zigpy_device.manufacturer, None),
            ModelInfo(None, zigpy_device.model),
        ):
            for entry in self._registry[key]:
                if entry.device_match.matches(zigpy_device):
                    return entry

        return None

    def remove(self, entry: QuirkRegistryEntry) -> None:
        """Remove a quirk entry from the registry."""
        for manufacturer, model in entry.device_match.applies_to:
            self._registry[ModelInfo(manufacturer, model)].remove(entry)

    def purge_custom_quirks(self, custom_quirks_root: Path) -> None:
        """Remove quirks loaded from the custom quirks directory."""
        for entries in self._registry.values():
            for entry in list(entries):
                if entry.source is None or entry.source.file is None:
                    continue
                if Path(entry.source.file).is_relative_to(custom_quirks_root):
                    _LOGGER.debug("Removing stale custom quirk: %s", entry)
                    entries.remove(entry)


DEVICE_REGISTRY = DeviceRegistry()


def register_device(cls: type[Device]) -> type[Device]:
    """Class decorator registering a hand-written `Device` subclass as a quirk."""
    if cls._device_match is None:
        raise ValueError(f"{cls!r} does not define `_device_match`")

    transforms: list[Callable[[zigpy.device.Device], zigpy.device.Device]] = []
    if cls._zigpy_device_cls is not None:
        transforms.append(make_zigpy_device_replacement(cls._zigpy_device_cls))
    transforms.extend(cls._zigpy_device_transforms)

    DEVICE_REGISTRY.register(
        QuirkRegistryEntry(
            device_match=cls._device_match,
            zigpy_transforms=tuple(transforms),
            zha_device_factory=cls,
            source=QuirkSource.from_class(cls),
        )
    )

    return cls


def resolve_zigpy_device(zigpy_device: zigpy.device.Device) -> zigpy.device.Device:
    """Provide zigpy a way to resolve a bare ZCL-compliant device to its final form."""

    # Resolution is idempotent: an already-quirked device is returned as-is
    if hasattr(zigpy_device, QUIRK_REGISTRY_ENTRY_ATTR):
        return zigpy_device

    # Fall back to legacy zigpy v1 quirks
    entry = DEVICE_REGISTRY.get(zigpy_device)
    if entry is None:
        return zigpy.quirks.get_device(zigpy_device)

    _LOGGER.debug(
        "Resolved %s/%s (%s) to quirk %s",
        zigpy_device.manufacturer,
        zigpy_device.model,
        zigpy_device.ieee,
        entry,
    )

    resolved_device = zigpy_device

    for transform in entry.zigpy_transforms:
        resolved_device = transform(resolved_device)

    # Sneak the registry entry in with the device so ZHA can use it
    setattr(resolved_device, QUIRK_REGISTRY_ENTRY_ATTR, entry)
    return resolved_device
