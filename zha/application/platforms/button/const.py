"""Constants for the button platform."""

from enum import StrEnum

DEFAULT_DURATION = 5  # seconds


class ButtonDeviceClass(StrEnum):
    """Device class for buttons."""

    IDENTIFY = "identify"
    RESTART = "restart"
    UPDATE = "update"
