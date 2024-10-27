"""Constants for the Siren platform."""

from __future__ import annotations

from enum import IntFlag
from typing import Final

DEFAULT_DURATION = 5  # seconds

ATTR_AVAILABLE_TONES: Final[str] = "available_tones"
ATTR_DURATION: Final[str] = "duration"
ATTR_VOLUME_LEVEL: Final[str] = "volume_level"
ATTR_TONE: Final[str] = "tone"


class SirenEntityFeature(IntFlag):
    """Supported features of the siren entity."""

    TURN_ON = 1
    TURN_OFF = 2
    TONES = 4
    VOLUME_SET = 8
    DURATION = 16
