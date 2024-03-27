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

STATE_UNAVAILABLE: Final = "unavailable"


class LightEntityFeature(IntFlag):
    """Supported features of the light entity."""

    EFFECT = 4
    FLASH = 8
    TRANSITION = 32


class ColorMode(StrEnum):
    """Possible light color modes."""

    UNKNOWN = "unknown"
    """Ambiguous color mode"""
    ONOFF = "onoff"
    """Must be the only supported mode"""
    BRIGHTNESS = "brightness"
    """Must be the only supported mode"""
    COLOR_TEMP = "color_temp"
    HS = "hs"
    XY = "xy"
    RGB = "rgb"
    RGBW = "rgbw"
    RGBWW = "rgbww"
    WHITE = "white"
    """Must *NOT* be the only supported mode"""


COLOR_MODES_GROUP_LIGHT = {ColorMode.COLOR_TEMP, ColorMode.XY}
SUPPORT_GROUP_LIGHT = (
    LightEntityFeature.EFFECT | LightEntityFeature.FLASH | LightEntityFeature.TRANSITION
)

# Float that represents transition time in seconds to make change.
ATTR_TRANSITION: Final[str] = "transition"

# Lists holding color values
ATTR_RGB_COLOR: Final[str] = "rgb_color"
ATTR_RGBW_COLOR: Final[str] = "rgbw_color"
ATTR_RGBWW_COLOR: Final[str] = "rgbww_color"
ATTR_XY_COLOR: Final[str] = "xy_color"
ATTR_HS_COLOR: Final[str] = "hs_color"
ATTR_COLOR_TEMP: Final[str] = "color_temp"
ATTR_KELVIN: Final[str] = "kelvin"
ATTR_MIN_MIREDS: Final[str] = "min_mireds"
ATTR_MAX_MIREDS: Final[str] = "max_mireds"
ATTR_COLOR_NAME: Final[str] = "color_name"
ATTR_WHITE_VALUE: Final[str] = "white_value"
ATTR_WHITE: Final[str] = "white"

# Brightness of the light, 0..255 or percentage
ATTR_BRIGHTNESS: Final[str] = "brightness"
ATTR_BRIGHTNESS_PCT: Final[str] = "brightness_pct"
ATTR_BRIGHTNESS_STEP: Final[str] = "brightness_step"
ATTR_BRIGHTNESS_STEP_PCT: Final[str] = "brightness_step_pct"

ATTR_COLOR_MODE = "color_mode"
ATTR_SUPPORTED_COLOR_MODES = "supported_color_modes"

# String representing a profile (built-in ones or external defined).
ATTR_PROFILE: Final[str] = "profile"

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

ATTR_SUPPORTED_FEATURES: Final[str] = "supported_features"

# Bitfield of features supported by the light entity
SUPPORT_BRIGHTNESS: Final[int] = 1  # Deprecated, replaced by color modes
SUPPORT_COLOR_TEMP: Final[int] = 2  # Deprecated, replaced by color modes
SUPPORT_EFFECT: Final[int] = 4
SUPPORT_FLASH: Final[int] = 8
SUPPORT_COLOR: Final[int] = 16  # Deprecated, replaced by color modes
SUPPORT_TRANSITION: Final[int] = 32
SUPPORT_WHITE_VALUE: Final[int] = 128  # Deprecated, replaced by color modes

EFFECT_BLINK: Final[int] = 0x00
EFFECT_BREATHE: Final[int] = 0x01
EFFECT_OKAY: Final[int] = 0x02
EFFECT_DEFAULT_VARIANT: Final[int] = 0x00

FLASH_EFFECTS: Final[dict[str, int]] = {
    FLASH_SHORT: EFFECT_BLINK,
    FLASH_LONG: EFFECT_BREATHE,
}

SUPPORT_GROUP_LIGHT = (
    SUPPORT_BRIGHTNESS
    | SUPPORT_COLOR_TEMP
    | SUPPORT_EFFECT
    | SUPPORT_FLASH
    | SUPPORT_COLOR
    | SUPPORT_TRANSITION
)

FLASH_EFFECTS = {
    FLASH_SHORT: Identify.EffectIdentifier.Blink,
    FLASH_LONG: Identify.EffectIdentifier.Breathe,
}

VALID_COLOR_MODES = {
    ColorMode.ONOFF,
    ColorMode.BRIGHTNESS,
    ColorMode.COLOR_TEMP,
    ColorMode.HS,
    ColorMode.XY,
    ColorMode.RGB,
    ColorMode.RGBW,
    ColorMode.RGBWW,
    ColorMode.WHITE,
}
COLOR_MODES_BRIGHTNESS = VALID_COLOR_MODES - {ColorMode.ONOFF}
COLOR_MODES_COLOR = {
    ColorMode.HS,
    ColorMode.RGB,
    ColorMode.RGBW,
    ColorMode.RGBWW,
    ColorMode.XY,
}
