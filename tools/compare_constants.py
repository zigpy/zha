#!/usr/bin/env python3
"""Compare ZHA's local copies of HA constants against the canonical `homeassistant` package.

Run this whenever `homeassistant` is bumped to surface drift in unit enums,
device-class enums, and module-level constants that ZHA mirrors.

Exits 1 on drift, 0 if fully in sync.
"""

from __future__ import annotations

from enum import Enum
import importlib
import sys
from typing import Any

import homeassistant.const as ha_const

import zha.units as zha_units

# Explicit (zha, ha) pairs for enums that don't live in `zha.units`.
ENUM_PAIRS: list[tuple[str, str]] = [
    (
        "zha.application.platforms.binary_sensor.device_class.BinarySensorDeviceClass",
        "homeassistant.components.binary_sensor.BinarySensorDeviceClass",
    ),
    (
        "zha.application.platforms.sensor.device_class.SensorDeviceClass",
        "homeassistant.components.sensor.SensorDeviceClass",
    ),
    (
        "zha.application.platforms.sensor.device_class.SensorStateClass",
        "homeassistant.components.sensor.SensorStateClass",
    ),
    (
        "zha.application.platforms.number.device_class.NumberDeviceClass",
        "homeassistant.components.number.NumberDeviceClass",
    ),
    (
        "zha.application.platforms.number.device_class.NumberMode",
        "homeassistant.components.number.NumberMode",
    ),
    # zha.application.Platform is intentionally a Zigbee-only subset of
    # homeassistant.const.Platform — comparison would produce noise.
]

# Constants intentionally defined in ZHA without an HA counterpart.
ZHA_ONLY_CONSTANTS: frozenset[str] = frozenset({"COUNT", "KILOJOULES_PER_KG"})


def import_qualified(qualified_name: str) -> Any:
    """Import a dotted name like 'zha.units.UnitOfTemperature'."""
    module_name, attr = qualified_name.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), attr)


def is_enum_class(obj: Any) -> bool:
    """Return True if obj is an Enum subclass."""
    return isinstance(obj, type) and issubclass(obj, Enum)


def compare_enums(zha_enum: type[Enum], ha_enum: type[Enum]) -> list[str]:
    """Return a list of difference lines between two enums (empty if identical)."""
    zha_members = {m.name: m.value for m in zha_enum}
    ha_members = {m.name: m.value for m in ha_enum}

    diffs: list[str] = []
    for name in sorted(set(ha_members) - set(zha_members)):
        diffs.append(f"  missing in ZHA: {name} = {ha_members[name]!r}")
    for name in sorted(set(zha_members) - set(ha_members)):
        diffs.append(f"  extra in ZHA:   {name} = {zha_members[name]!r}")
    for name in sorted(set(zha_members) & set(ha_members)):
        if zha_members[name] != ha_members[name]:
            diffs.append(
                f"  value mismatch: {name}: ZHA={zha_members[name]!r} HA={ha_members[name]!r}"
            )
    return diffs


def compare_units_module() -> list[tuple[str, list[str]]]:
    """Compare zha.units against homeassistant.const in both directions.

    Forward: walk zha.units and compare each against the same-named symbol in
    homeassistant.const. Reverse: surface UnitOf* enums in homeassistant.const
    that don't exist in zha.units at all.
    """
    results: list[tuple[str, list[str]]] = []
    for name in sorted(vars(zha_units)):
        if name.startswith("_"):
            continue
        zha_obj = getattr(zha_units, name)

        # Only compare classes/strings defined in zha.units itself
        # (skip re-imports like StrEnum, Final).
        if is_enum_class(zha_obj):
            if zha_obj.__module__ != zha_units.__name__:
                continue
        elif not isinstance(zha_obj, str):
            continue

        if name in ZHA_ONLY_CONSTANTS:
            continue

        if not hasattr(ha_const, name):
            results.append((name, ["  not present in homeassistant.const"]))
            continue

        ha_obj = getattr(ha_const, name)

        if is_enum_class(zha_obj) and is_enum_class(ha_obj):
            results.append((name, compare_enums(zha_obj, ha_obj)))
        elif isinstance(zha_obj, str) and isinstance(ha_obj, str):
            if zha_obj != ha_obj:
                results.append(
                    (name, [f"  value mismatch: ZHA={zha_obj!r} HA={ha_obj!r}"])
                )
            else:
                results.append((name, []))
        else:
            results.append(
                (
                    name,
                    [
                        f"  type mismatch: ZHA={type(zha_obj).__name__} HA={type(ha_obj).__name__}"
                    ],
                )
            )

    # Reverse scan: UnitOf* enums in homeassistant.const that ZHA doesn't have.
    zha_names = {n for n in vars(zha_units) if not n.startswith("_")}
    for name in sorted(vars(ha_const)):
        if not name.startswith("UnitOf"):
            continue
        ha_obj = getattr(ha_const, name)
        if not is_enum_class(ha_obj):
            continue
        if ha_obj.__module__ != ha_const.__name__:
            continue
        if name in zha_names:
            continue
        members = ", ".join(f"{m.name}={m.value!r}" for m in ha_obj)
        results.append((name, [f"  not present in zha.units (HA has: {members})"]))

    return results


def print_block(title: str, results: list[tuple[str, list[str]]]) -> bool:
    """Print one section. Return True if any drift was found."""
    print(title)
    print("=" * len(title))
    drift = False
    in_sync: list[str] = []
    for name, diffs in results:
        if not diffs:
            in_sync.append(name)
            continue
        drift = True
        print(f"\n{name}:")
        for line in diffs:
            print(line)
    if in_sync:
        print(f"\nin sync ({len(in_sync)}): {', '.join(in_sync)}")
    print()
    return drift


def main() -> int:
    """Run the comparison and return an exit code (0 = in sync, 1 = drift)."""
    units_results = compare_units_module()

    enum_results: list[tuple[str, list[str]]] = []
    for zha_name, ha_name in ENUM_PAIRS:
        label = f"{zha_name.split('.')[-1]} ({zha_name} ↔ {ha_name})"
        try:
            zha_enum = import_qualified(zha_name)
            ha_enum = import_qualified(ha_name)
        except (ImportError, AttributeError) as exc:
            enum_results.append((label, [f"  failed to import: {exc}"]))
            continue
        enum_results.append((label, compare_enums(zha_enum, ha_enum)))

    drift = False
    drift |= print_block("zha.units vs homeassistant.const", units_results)
    drift |= print_block("Device classes & Platform enums", enum_results)

    if drift:
        print("DRIFT detected — ZHA constants are out of sync with homeassistant.")
        return 1
    print("All compared constants match homeassistant.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
