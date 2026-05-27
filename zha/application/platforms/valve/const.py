"""Constants for the valve platform."""

from enum import IntFlag, StrEnum
from typing import Final

ATTR_CURRENT_POSITION: Final[str] = "current_position"
ATTR_POSITION: Final[str] = "position"


class ValveState(StrEnum):
    """State of Valve entities."""

    OPENING = "opening"
    CLOSING = "closing"
    CLOSED = "closed"
    OPEN = "open"


class ValveDeviceClass(StrEnum):
    """Device class for valve."""

    # Refer to the valve dev docs for device class descriptions
    WATER = "water"
    GAS = "gas"


class ValveEntityFeature(IntFlag):
    """Supported features of the valve entity."""

    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8
