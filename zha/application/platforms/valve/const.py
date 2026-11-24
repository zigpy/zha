"""Constants for the valve platform."""

from enum import IntFlag, StrEnum


class ValveDeviceClass(StrEnum):
    """Device class for valves."""

    WATER = "water"
    GAS = "gas"


class ValveEntityFeature(IntFlag):
    """Supported features of the valve entity."""

    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8
