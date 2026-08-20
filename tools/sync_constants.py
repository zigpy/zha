#!/usr/bin/env python3
"""Sync ZHA's local copies of Home Assistant constants from the `homeassistant` package.

ZHA keeps near 1:1 copies of some Home Assistant enums and constants (unit enums
in `zha.units`, and the device-class / mode enums under `zha.application.platforms`).
This tool copies them verbatim from the installed `homeassistant` package —
including docstrings and comments — so they stay in sync. Point it at Home
Assistant's `dev` branch (install it editable) to track upcoming changes.

What it does, per mirrored file:

* Device-class / mode enums are replaced verbatim with HA's definition.
* Every ``UnitOf*`` enum HA defines is copied into `zha.units`: ones ZHA already
  has are refreshed in place, missing ones are appended (above the backwards-
  compatibility marker), and ones HA has since removed are deleted. Docstrings
  and in-class comments come along, since whole classes are copied.

Only enums are synced. The module-level constants ZHA mirrors live in a
hand-maintained "backwards compatibility" section at the end of `zha.units`
(some, like ``PERCENTAGE``, derive from the enums exactly as HA does). Copying
those verbatim would reorder the file and create forward references, and they
double as ZHA's public API, so they are deliberately left for humans to update.
This tool never touches that section or ZHA-only symbols (so only enums, never
constants, are added, changed, or removed).

Run ``ruff format`` afterwards to normalise whitespace. Use ``--check`` for a dry
run that exits 1 if anything would change.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from enum import Enum
import importlib
import inspect
from pathlib import Path
import sys
from typing import Any

import homeassistant.const as ha_const

# zha.units source file, relative to the repo root (parsed as text, never
# imported, so the tool works even if a bad prior sync left it un-importable).
UNITS_FILE = "zha/units.py"

# Device-class / mode enums ZHA mirrors, mapped to the ZHA file that holds a copy.
# Each entry is the fully-qualified HA name of the enum to copy verbatim.
DEVICE_CLASS_ENUMS: dict[str, list[str]] = {
    "zha/application/platforms/binary_sensor/device_class.py": [
        "homeassistant.components.binary_sensor.BinarySensorDeviceClass",
    ],
    "zha/application/platforms/sensor/device_class.py": [
        "homeassistant.components.sensor.SensorDeviceClass",
        "homeassistant.components.sensor.SensorStateClass",
    ],
    "zha/application/platforms/number/device_class.py": [
        "homeassistant.components.number.NumberDeviceClass",
        "homeassistant.components.number.NumberMode",
    ],
}

# Substring marking the start of the hand-maintained backwards-compatibility
# section in zha/units.py. New enums are inserted above this line; the section
# below it is never rewritten by this tool.
UNITS_BACKCOMPAT_ANCHOR = "Backwards-compatibility constants"


def import_qualified(qualified_name: str) -> Any:
    """Import a dotted name like 'homeassistant.components.sensor.SensorDeviceClass'."""
    module_name, attr = qualified_name.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), attr)


def is_enum_class(obj: Any) -> bool:
    """Return True if obj is an Enum subclass."""
    return isinstance(obj, type) and issubclass(obj, Enum)


def ha_unit_enum_names() -> list[str]:
    """Return the names of all ``UnitOf*`` enums defined in homeassistant.const."""
    names = []
    for name in sorted(vars(ha_const)):
        if not name.startswith("UnitOf"):
            continue
        obj = getattr(ha_const, name)
        if is_enum_class(obj) and obj.__module__ == ha_const.__name__:
            names.append(name)
    return names


class SourceFile:
    """A parsed source file with pending line-range edits, applied bottom-up."""

    def __init__(self, path: Path) -> None:
        """Read and parse ``path``."""
        self.path = path
        self.original = path.read_text(encoding="utf-8")
        self.lines = self.original.splitlines(keepends=True)
        self.tree = ast.parse(self.original)
        # (start_index, end_index_exclusive, replacement_lines)
        self._edits: list[tuple[int, int, list[str]]] = []

    def class_node(self, name: str) -> ast.ClassDef | None:
        """Return the top-level ClassDef named ``name``, or None."""
        for node in self.tree.body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        return None

    def replace_node(self, node: ast.stmt, new_source: str) -> None:
        """Replace the source lines spanned by ``node`` with ``new_source``."""
        block = (new_source.rstrip("\n") + "\n").splitlines(keepends=True)
        self._edits.append((node.lineno - 1, node.end_lineno, block))

    def remove_node(self, node: ast.stmt) -> None:
        """Remove the source lines of ``node`` and the blank lines that follow it."""
        end = node.end_lineno
        while end < len(self.lines) and not self.lines[end].strip():
            end += 1
        self._edits.append((node.lineno - 1, end, []))

    def append_classes(self, sources: list[str], anchor: str | None = None) -> None:
        """Insert new top-level classes.

        If ``anchor`` (a substring) is found on a line, the classes are inserted
        just before it; otherwise they go after the last existing class.
        """
        body: list[str] = []
        for source in sources:
            if body:
                body.extend(("\n", "\n"))
            body.extend((source.rstrip("\n") + "\n").splitlines(keepends=True))

        anchor_index = None
        if anchor is not None:
            anchor_index = next(
                (i for i, line in enumerate(self.lines) if anchor in line), None
            )

        if anchor_index is not None:
            # Existing blank lines before the anchor separate it from the new
            # classes; add trailing blanks to separate the classes from it.
            block = body + ["\n", "\n"]
            insert_at = anchor_index
        else:
            last_class = max(
                (n for n in self.tree.body if isinstance(n, ast.ClassDef)),
                key=lambda n: n.end_lineno,
            )
            block = ["\n", "\n", *body]
            insert_at = last_class.end_lineno
        self._edits.append((insert_at, insert_at, block))

    def render(self) -> str:
        """Return the file text with all edits applied (does not write)."""
        lines = list(self.lines)
        for start, end, replacement in sorted(
            self._edits, key=lambda e: e[0], reverse=True
        ):
            lines[start:end] = replacement
        return "".join(lines)

    def flush(self) -> bool:
        """Apply edits to disk. Return True if the file content changed."""
        new_text = self.render()
        if new_text == self.original:
            return False
        self.path.write_text(new_text, encoding="utf-8")
        return True


@dataclass
class EnumChange:
    """A per-enum summary of what a sync changed, for the run/PR summary."""

    name: str
    is_new: bool = False
    is_removed: bool = False
    added: dict[str, str] = field(default_factory=dict)
    removed_members: dict[str, str] = field(default_factory=dict)
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)
    doc_changed: bool = False


def _enum_members_from_node(node: ast.ClassDef) -> dict[str, str]:
    """Return {member: value} for ``NAME = "value"`` assignments in a class body."""
    members: dict[str, str] = {}
    for stmt in node.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            members[stmt.targets[0].id] = stmt.value.value
    return members


def _normalize_source(text: str) -> str:
    """Strip trailing whitespace and surrounding blank lines, for comparison."""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def diff_enum(
    name: str, zha_node: ast.ClassDef, ha_enum: type[Enum], original: str
) -> EnumChange | None:
    """Return an EnumChange describing how ``ha_enum`` differs from ZHA's copy.

    None if the class is unchanged. Member add/remove/value changes are exact;
    docstring/comment/formatting changes are flagged (only) when no member
    changed, since those already show up alongside member changes in the diff.
    """
    ha_members = {m.name: m.value for m in ha_enum}
    zha_members = _enum_members_from_node(zha_node)
    added = {k: v for k, v in ha_members.items() if k not in zha_members}
    removed = {k: v for k, v in zha_members.items() if k not in ha_members}
    changed = {
        k: (zha_members[k], ha_members[k])
        for k in zha_members.keys() & ha_members.keys()
        if zha_members[k] != ha_members[k]
    }
    doc_changed = not (added or removed or changed) and _normalize_source(
        ast.get_source_segment(original, zha_node) or ""
    ) != _normalize_source(inspect.getsource(ha_enum))
    if not (added or removed or changed or doc_changed):
        return None
    return EnumChange(
        name=name,
        added=added,
        removed_members=removed,
        changed=changed,
        doc_changed=doc_changed,
    )


def format_changes(changes: list[EnumChange]) -> list[str]:
    """Render EnumChange records as indented summary lines."""
    lines: list[str] = []
    for change in changes:
        if change.is_new:
            lines.append(f"  + added enum {change.name}")
            continue
        if change.is_removed:
            lines.append(f"  - removed enum {change.name}")
            continue
        lines.append(f"  {change.name}:")
        for member in sorted(change.added):
            lines.append(f"    + {member} = {change.added[member]!r}")
        for member in sorted(change.removed_members):
            lines.append(f"    - {member} = {change.removed_members[member]!r}")
        for member in sorted(change.changed):
            old, new = change.changed[member]
            lines.append(f"    ~ {member}: {old!r} -> {new!r}")
        if change.doc_changed:
            lines.append("    ~ docstring/comment updates")
    return lines


def build_device_class_edits(
    path: Path, ha_qualnames: list[str]
) -> tuple[SourceFile, list[EnumChange]]:
    """Return a SourceFile and per-enum changes to copy each HA enum into ``path``."""
    source_file = SourceFile(path)
    changes: list[EnumChange] = []
    for qualname in ha_qualnames:
        try:
            ha_enum = import_qualified(qualname)
        except (ImportError, AttributeError) as exc:
            raise LookupError(
                f"Home Assistant no longer defines {qualname}; "
                f"update DEVICE_CLASS_ENUMS in {Path(__file__).name}"
            ) from exc
        node = source_file.class_node(ha_enum.__name__)
        if node is None:
            raise LookupError(f"{ha_enum.__name__} not found in {path}")
        change = diff_enum(ha_enum.__name__, node, ha_enum, source_file.original)
        if change is not None:
            changes.append(change)
        source_file.replace_node(node, inspect.getsource(ha_enum))
    return source_file, changes


def build_units_edits() -> tuple[SourceFile, list[EnumChange]]:
    """Return a SourceFile and per-enum changes to sync zha.units."""
    source_file = SourceFile(Path(UNITS_FILE))
    ha_names = set(ha_unit_enum_names())
    changes: list[EnumChange] = []

    # Unit enums: replace the ones ZHA has, append the ones it's missing.
    new_class_sources: list[str] = []
    for name in ha_unit_enum_names():
        ha_enum = getattr(ha_const, name)
        source = inspect.getsource(ha_enum)
        node = source_file.class_node(name)
        if node is not None:
            change = diff_enum(name, node, ha_enum, source_file.original)
            if change is not None:
                changes.append(change)
            source_file.replace_node(node, source)
        else:
            new_class_sources.append(source)
            changes.append(EnumChange(name=name, is_new=True))
    if new_class_sources:
        source_file.append_classes(new_class_sources, anchor=UNITS_BACKCOMPAT_ANCHOR)

    # Remove unit enums HA no longer defines. ZHA's unit enums exist solely to
    # mirror HA. `ha_names` only holds enums *defined* in homeassistant.const, so
    # guard against HA merely relocating one (still exposed via a re-export): if
    # HA still has the name, don't guess — fail so a human updates the tool.
    for node in source_file.tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name.startswith("UnitOf")):
            continue
        if node.name in ha_names:
            continue
        if hasattr(ha_const, node.name):
            raise LookupError(
                f"{node.name} is no longer defined in homeassistant.const but HA "
                f"still exposes it (it may have moved); update {Path(__file__).name}"
            )
        source_file.remove_node(node)
        changes.append(EnumChange(name=node.name, is_removed=True))

    return source_file, changes


def main(argv: list[str] | None = None) -> int:
    """Sync all mirrored files. Return 0, or (with --check) 1 if anything would change."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if any file would change",
    )
    args = parser.parse_args(argv)

    edits: list[tuple[SourceFile, list[EnumChange]]] = [
        build_device_class_edits(Path(zha_dir), qualnames)
        for zha_dir, qualnames in DEVICE_CLASS_ENUMS.items()
    ]
    edits.append(build_units_edits())

    if args.check:
        stale = [sf.path for sf, _ in edits if sf.render() != sf.original]
        for path in stale:
            print(f"{path}: would change")
        if stale:
            print(
                f"\n{len(stale)} file(s) out of sync — run without --check to update."
            )
            return 1
        print("All mirrored constants are in sync.")
        return 0

    changed = [(sf.path, changes) for sf, changes in edits if sf.flush()]
    if changed:
        print("Synced from Home Assistant:")
        for path, changes in changed:
            print(f"\n{path}:")
            for line in format_changes(changes) or ["  updated"]:
                print(line)
    else:
        print("All mirrored constants already in sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
