"""Constants for the Light platform."""

from enum import IntFlag, StrEnum
from typing import Final

from zigpy.zcl.clusters.general import Identify

DEFAULT_ON_OFF_TRANSITION = 1  # most bulbs default to a 1-second turn on/off transition
DEFAULT_EXTRA_TRANSITION_DELAY_SHORT = 0.25
DEFAULT_EXTRA_TRANSITION_DELAY_LONG = 2.0
DEFAULT_LONG_TRANSITION_TIME = 10
DEFAULT_MIN_BRIGHTNESS = 2
ASSUME_UPDATE_GROUP_FROM_CHILD_DELAY = 0.05

DEFAULT_MIN_TRANSITION_MANUFACTURERS = {"sengled"}

STATE_UNAVAILABLE: Final[str] = "unavailable"


class LightEntityFeature(IntFlag):
    """Supported features of the light entity."""

    EFFECT = 4
    FLASH = 8
    TRANSITION = 32


class ColorMode(StrEnum):
    """Possible light color modes."""

    UNKNOWN = "unknown"
    ONOFF = "onoff"
    BRIGHTNESS = "brightness"
    COLOR_TEMP = "color_temp"
    XY = "xy"


# Float that represents transition time in seconds to make change.
ATTR_TRANSITION: Final[str] = "transition"

# Lists holding color values
ATTR_XY_COLOR: Final[str] = "xy_color"
ATTR_COLOR_TEMP: Final[str] = "color_temp"
ATTR_MIN_MIREDS: Final[str] = "min_mireds"
ATTR_MAX_MIREDS: Final[str] = "max_mireds"

# Brightness of the light, 0..255 or percentage
ATTR_BRIGHTNESS: Final[str] = "brightness"

ATTR_COLOR_MODE = "color_mode"
ATTR_SUPPORTED_COLOR_MODES = "supported_color_modes"

# If the light should flash, can be FLASH_SHORT or FLASH_LONG.
ATTR_FLASH: Final[str] = "flash"
FLASH_SHORT: Final[str] = "short"
FLASH_LONG: Final[str] = "long"

# List of possible effects
ATTR_EFFECT_LIST: Final[str] = "effect_list"

# Apply an effect to the light, can be EFFECT_COLORLOOP.
ATTR_EFFECT: Final[str] = "effect"
EFFECT_COLORLOOP: Final[str] = "colorloop"
EFFECT_RANDOM: Final[str] = "random"
EFFECT_WHITE: Final[str] = "white"
EFFECT_OFF: Final[str] = "off"

ATTR_SUPPORTED_FEATURES: Final[str] = "supported_features"

EFFECT_OKAY: Final[int] = 0x02
EFFECT_DEFAULT_VARIANT: Final[int] = 0x00

FLASH_EFFECTS: Final[dict[str, int]] = {
    FLASH_SHORT: Identify.EffectIdentifier.Blink,
    FLASH_LONG: Identify.EffectIdentifier.Breathe,
}

VALID_COLOR_MODES = {
    ColorMode.ONOFF,
    ColorMode.BRIGHTNESS,
    ColorMode.COLOR_TEMP,
    ColorMode.XY,
}
COLOR_MODES_BRIGHTNESS = VALID_COLOR_MODES - {ColorMode.ONOFF}
COLOR_MODES_COLOR = {ColorMode.XY}
