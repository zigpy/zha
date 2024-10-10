"""Constants for the Fan platform."""

# Additional speeds in zigbee's ZCL
# Spec is unclear as to what this value means. On King Of Fans HBUniversal
# receiver, this means Very High.
from enum import IntFlag
from typing import Final

DEFAULT_ON_PERCENTAGE: Final[int] = 50


class FanEntityFeature(IntFlag):
    """Supported features of the fan entity."""

    SET_SPEED = 1
    OSCILLATE = 2
    DIRECTION = 4
    PRESET_MODE = 8
    TURN_OFF = 16
    TURN_ON = 32


PRESET_MODE_ON: Final[str] = "on"
# The fan speed is self-regulated
PRESET_MODE_AUTO: Final[str] = "auto"
# When the heated/cooled space is occupied, the fan is always on
PRESET_MODE_SMART: Final[str] = "smart"

ATTR_PERCENTAGE: Final[str] = "percentage"
ATTR_PERCENTAGE_STEP: Final[str] = "percentage_step"
ATTR_OSCILLATING: Final[str] = "oscillating"
ATTR_DIRECTION: Final[str] = "direction"
ATTR_PRESET_MODE: Final[str] = "preset_mode"
ATTR_PRESET_MODES: Final[str] = "preset_modes"

SPEED_OFF: Final[str] = "off"
SPEED_LOW: Final[str] = "low"
SPEED_MEDIUM: Final[str] = "medium"
SPEED_HIGH: Final[str] = "high"
