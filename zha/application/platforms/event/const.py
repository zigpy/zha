"""Constants for the ZHA event platform."""

from enum import StrEnum


class EventDeviceClass(StrEnum):
    """Device class for event entities."""

    DOORBELL = "doorbell"
    BUTTON = "button"
    MOTION = "motion"
