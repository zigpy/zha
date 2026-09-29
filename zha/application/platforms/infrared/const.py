"""Constants for the infrared platform."""

from enum import StrEnum


class InfraredDeviceClass(StrEnum):
    """Device class for infrared entities."""

    EMITTER = "emitter"
    RECEIVER = "receiver"
