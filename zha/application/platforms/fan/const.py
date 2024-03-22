"""Constants for the Fan platform."""

# Additional speeds in zigbee's ZCL
# Spec is unclear as to what this value means. On King Of Fans HBUniversal
# receiver, this means Very High.
from enum import IntFlag
from typing import Final

PRESET_MODE_ON: Final[str] = "on"
# The fan speed is self-regulated
PRESET_MODE_AUTO: Final[str] = "auto"
# When the heated/cooled space is occupied, the fan is always on
PRESET_MODE_SMART: Final[str] = "smart"

SPEED_RANGE: Final = (1, 3)  # off is not included
PRESET_MODES_TO_NAME: Final[dict[int, str]] = {
    4: PRESET_MODE_ON,
    5: PRESET_MODE_AUTO,
    6: PRESET_MODE_SMART,
}

NAME_TO_PRESET_MODE = {v: k for k, v in PRESET_MODES_TO_NAME.items()}
PRESET_MODES = list(NAME_TO_PRESET_MODE)

DEFAULT_ON_PERCENTAGE: Final[int] = 50

ATTR_PERCENTAGE: Final[str] = "percentage"
ATTR_PERCENTAGE_STEP: Final[str] = "percentage_step"
ATTR_OSCILLATING: Final[str] = "oscillating"
ATTR_DIRECTION: Final[str] = "direction"
ATTR_PRESET_MODE: Final[str] = "preset_mode"
ATTR_PRESET_MODES: Final[str] = "preset_modes"

SUPPORT_SET_SPEED: Final[int] = 1

SPEED_OFF: Final[str] = "off"
SPEED_LOW: Final[str] = "low"
SPEED_MEDIUM: Final[str] = "medium"
SPEED_HIGH: Final[str] = "high"

OFF_SPEED_VALUES: list[str | None] = [SPEED_OFF, None]
LEGACY_SPEED_LIST: list[str] = [SPEED_LOW, SPEED_MEDIUM, SPEED_HIGH]


class FanEntityFeature(IntFlag):
    """Supported features of the fan entity."""

    SET_SPEED = 1
    OSCILLATE = 2
    DIRECTION = 4
    PRESET_MODE = 8
