"""Constants for the ZHA device tracker platform."""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """Source type for device trackers."""

    GPS = "gps"
    ROUTER = "router"
    BLUETOOTH = "bluetooth"
    BLUETOOTH_LE = "bluetooth_le"
