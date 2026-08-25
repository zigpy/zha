"""Quirks support for ZHA, allowing custom `Device` objects to be swapped at runtime."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
import contextlib
from dataclasses import dataclass, field
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypeVar, overload

from zigpy.application import ControllerApplication
import zigpy.device
import zigpy.profiles.zha
from zigpy.types import EUI64, NWK
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Ota

if TYPE_CHECKING:
    from zha.zigbee.device import Device, GreenPowerDevice

_LOGGER = logging.getLogger(__name__)

QUIRK_REGISTRY_ENTRY_ATTR = "_quirk_registry_entry"
FilterType = Callable[[zigpy.device.Device], bool]
GreenPowerFilterType = Callable[[zigpy.device.GreenPowerDevice], bool]

_EntryT = TypeVar("_EntryT", "QuirkRegistryEntry", "GreenPowerQuirkRegistryEntry")

DEVICE_REGISTRY: DeviceRegistry

# Quirk IDs
KONKE_BUTTON = "konke.button_remote"
TUYA_PLUG_ONOFF = "tuya.plug_on_off_attributes"
TUYA_PLUG_MANUFACTURER = "tuya.plug_manufacturer_attributes"
XIAOMI_AQARA_VIBRATION_AQ1 = "xiaomi.aqara_vibration_aq1"
DANFOSS_ALLY_THERMOSTAT = "danfoss.ally_thermostat"
BEGA_LIGHT_SWITCHABLE_WHITE = "bega.light_switchable_white"
SE_POLL_SUMMATION = "se_poll_summation"
SIREN_BASIC = "siren_basic"


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


# A zigpy device class whose constructor takes the device it replaces as a 4th arg.
ReplacingZigpyDeviceFactory = Callable[
    [ControllerApplication, EUI64, NWK, zigpy.device.Device], zigpy.device.Device
]


@dataclass(frozen=True)
class ReplaceZigpyDevice:
    """A transform wrapping a device in `device_cls` (a `ReplacingZigpyDeviceFactory`)."""

    device_cls: ReplacingZigpyDeviceFactory

    def __call__(self, device: zigpy.device.Device) -> zigpy.device.Device:
        """Replace a zigpy device."""
        return self.device_cls(device.application, device.ieee, device.nwk, device)


@dataclass(frozen=True)
class QuirkRegistryEntry:
    """A registered quirk: how to match, mutate, build and locate a device."""

    device_match: DeviceMatch
    zigpy_transforms: tuple[
        Callable[[zigpy.device.Device], zigpy.device.Device], ...
    ] = ()
    zha_device_factory: Callable[..., Device] | None = None
    # Excluded from equality so identical quirks registered at different sites still
    # deduplicate.
    source: QuirkSource | None = field(default=None, compare=False)


@dataclass(frozen=True)
class GreenPowerDeviceMatch:
    """Criteria matching a Green Power quirk to a GPD's commissioning signature.

    Every specified field must match. `src_id_ranges` and `ieee_prefixes`
    together form the identity criterion: when either is present, the device's
    SrcID must fall within one of the ranges or its IEEE address must begin
    with one of the prefixes.
    """

    device_id: int | None = None
    manufacturer_id: int | None = None
    model_id: int | None = None
    src_id_ranges: tuple[tuple[int, int], ...] = ()  # inclusive bounds
    ieee_prefixes: tuple[bytes, ...] = ()  # most-significant-byte first
    filters: tuple[GreenPowerFilterType, ...] = ()

    def matches(self, device: zigpy.device.GreenPowerDevice) -> bool:
        """Return True if `device` satisfies all criteria."""
        if self.device_id is not None and device.device_id != self.device_id:
            return False

        if (
            self.manufacturer_id is not None
            and device.gpd_manufacturer_id != self.manufacturer_id
        ):
            return False

        if self.model_id is not None and device.gpd_model_id != self.model_id:
            return False

        if self.src_id_ranges or self.ieee_prefixes:
            in_range = device.src_id is not None and any(
                lower <= device.src_id <= upper for lower, upper in self.src_id_ranges
            )
            # An EUI64 serializes least-significant-byte first
            ieee = bytes(reversed(device.ieee.serialize()))
            has_prefix = any(ieee.startswith(prefix) for prefix in self.ieee_prefixes)

            if not in_range and not has_prefix:
                return False

        return all(matcher(device) for matcher in self.filters)


@dataclass(frozen=True)
class GreenPowerQuirkRegistryEntry:
    """A registered Green Power quirk: how to match, mutate, and build a device."""

    device_match: GreenPowerDeviceMatch
    zigpy_transforms: tuple[
        Callable[[zigpy.device.GreenPowerDevice], zigpy.device.GreenPowerDevice], ...
    ] = ()
    zha_device_factory: Callable[..., GreenPowerDevice] | None = None
    # Excluded from equality so identical quirks registered at different sites still
    # deduplicate.
    source: QuirkSource | None = field(default=None, compare=False)


class DeviceRegistry:
    """Registry of quirk entries for all device types.

    Zigbee entries are indexed by (manufacturer, model); Green Power entries
    are kept in a flat list matched in registration order.
    """

    def __init__(self) -> None:
        """Initialize the registry."""

        # Normal registry that matches based on at least a model or manufacturer.
        self._registry: defaultdict[ModelInfo, list[QuirkRegistryEntry]] = defaultdict(
            list
        )
        # Matched against every device by their filters alone, used mostly for legacy v1
        # quirks without model/manufacturer filters.
        self._wildcard_registry: list[QuirkRegistryEntry] = []
        # Green Power entries, matched in registration order.
        self._gp_registry: list[GreenPowerQuirkRegistryEntry] = []

    @overload
    def register(self, entry: QuirkRegistryEntry) -> QuirkRegistryEntry: ...

    @overload
    def register(
        self, entry: GreenPowerQuirkRegistryEntry
    ) -> GreenPowerQuirkRegistryEntry: ...

    def register(
        self, entry: QuirkRegistryEntry | GreenPowerQuirkRegistryEntry
    ) -> QuirkRegistryEntry | GreenPowerQuirkRegistryEntry:
        """Add a quirk entry to the registry, ignoring exact duplicates."""
        if isinstance(entry, GreenPowerQuirkRegistryEntry):
            if entry not in self._gp_registry:
                self._gp_registry.insert(0, entry)
            return entry

        if not entry.device_match.applies_to:
            if entry not in self._wildcard_registry:
                self._wildcard_registry.insert(0, entry)
            return entry

        for manufacturer, model in entry.device_match.applies_to:
            if manufacturer is None and model is None:
                raise ValueError(
                    f"{entry!r} must specify a manufacturer and/or model to match"
                )

            entries = self._registry[ModelInfo(manufacturer, model)]
            if entry not in entries:
                entries.insert(0, entry)

        return entry

    def register_device(self, cls: type[Device]) -> type[Device]:
        """Register a hand-written `Device` subclass as a quirk in this registry."""
        if cls._device_match is None:
            raise ValueError(f"{cls!r} does not define `_device_match`")

        transforms: list[Callable[[zigpy.device.Device], zigpy.device.Device]] = []
        if cls._zigpy_device_cls is not None:
            transforms.append(ReplaceZigpyDevice(cls._zigpy_device_cls))
        transforms.extend(cls._zigpy_device_transforms)

        self.register(
            QuirkRegistryEntry(
                device_match=cls._device_match,
                zigpy_transforms=tuple(transforms),
                zha_device_factory=cls,
                source=QuirkSource.from_class(cls),
            )
        )

        return cls

    def match_entry(
        self, zigpy_device: zigpy.device.Device
    ) -> QuirkRegistryEntry | None:
        """Return the first registered entry matching `zigpy_device`."""
        for key in (
            ModelInfo(zigpy_device.manufacturer, zigpy_device.model),
            ModelInfo(zigpy_device.manufacturer, None),
            ModelInfo(None, zigpy_device.model),
        ):
            for entry in self._registry[key]:
                if entry.device_match.matches(zigpy_device):
                    return entry

        for entry in self._wildcard_registry:
            if entry.device_match.matches(zigpy_device):
                return entry

        return None

    def match_green_power_entry(
        self, zigpy_device: zigpy.device.GreenPowerDevice
    ) -> GreenPowerQuirkRegistryEntry | None:
        """Return the first registered entry matching the Green Power device."""
        for entry in self._gp_registry:
            if entry.device_match.matches(zigpy_device):
                return entry

        return None

    def resolve(self, zigpy_device: zigpy.device.BaseDevice) -> zigpy.device.BaseDevice:
        """Apply the quirk transforms registered for `zigpy_device` and return the result."""

        # Resolution is idempotent: an already-quirked device is returned as-is
        if hasattr(zigpy_device, QUIRK_REGISTRY_ENTRY_ATTR):
            return zigpy_device

        entry: QuirkRegistryEntry | GreenPowerQuirkRegistryEntry | None
        if isinstance(zigpy_device, zigpy.device.GreenPowerDevice):
            entry = self.match_green_power_entry(zigpy_device)
        elif isinstance(zigpy_device, zigpy.device.ZigbeeDevice):
            entry = self.match_entry(zigpy_device)
        else:
            return zigpy_device

        if entry is None:
            return zigpy_device

        _LOGGER.debug("Resolved %s to quirk %s", zigpy_device, entry)

        # A failing quirk must not prevent the device from loading: log and fall
        # back to the bare device rather than letting the exception propagate.
        resolved_device = zigpy_device
        try:
            for transform in entry.zigpy_transforms:
                resolved_device = transform(resolved_device)
        except Exception:
            _LOGGER.exception("Failed to load quirk for %s", zigpy_device)
            return zigpy_device

        setattr(resolved_device, QUIRK_REGISTRY_ENTRY_ATTR, entry)

        return resolved_device

    def __iter__(
        self,
    ) -> Iterator[QuirkRegistryEntry | GreenPowerQuirkRegistryEntry]:
        """Yield every registered entry once (deduplicated across model keys)."""
        seen: set[int] = set()
        for entries in (*self._registry.values(), self._wildcard_registry):
            for entry in entries:
                if id(entry) not in seen:
                    seen.add(id(entry))
                    yield entry

        yield from self._gp_registry

    def remove(self, entry: QuirkRegistryEntry | GreenPowerQuirkRegistryEntry) -> None:
        """Remove a quirk entry from the registry."""
        if isinstance(entry, GreenPowerQuirkRegistryEntry):
            self._gp_registry.remove(entry)
            return

        if not entry.device_match.applies_to:
            self._wildcard_registry.remove(entry)
            return

        for manufacturer, model in entry.device_match.applies_to:
            self._registry[ModelInfo(manufacturer, model)].remove(entry)

    @staticmethod
    def _purge_custom_entries(entries: list[_EntryT], custom_quirks_root: Path) -> None:
        """Remove entries defined within `custom_quirks_root` from `entries`."""
        for entry in list(entries):
            if entry.source is None or entry.source.file is None:
                continue
            if Path(entry.source.file).is_relative_to(custom_quirks_root):
                _LOGGER.debug("Removing stale custom quirk: %s", entry)
                entries.remove(entry)

    def purge_custom_quirks(self, custom_quirks_root: Path) -> None:
        """Remove quirks loaded from the custom quirks directory."""

        # Prefer the explicit registry to the wildcard registry
        for entries in (*self._registry.values(), self._wildcard_registry):
            self._purge_custom_entries(entries, custom_quirks_root)

        self._purge_custom_entries(self._gp_registry, custom_quirks_root)

    @contextlib.contextmanager
    def preserve_state(self) -> Iterator[None]:
        """Snapshot the registry and restore it on exit."""
        saved = {key: list(entries) for key, entries in self._registry.items()}
        saved_wildcard = list(self._wildcard_registry)
        saved_gp = list(self._gp_registry)
        try:
            yield
        finally:
            self._registry.clear()
            self._registry.update(saved)
            self._wildcard_registry[:] = saved_wildcard
            self._gp_registry[:] = saved_gp


DEVICE_REGISTRY = DeviceRegistry()
