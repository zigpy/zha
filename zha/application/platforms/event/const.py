"""Constants for the event platform."""

from enum import StrEnum

ATTR_PRESS_COUNT = "press_count"


class EventDeviceClass(StrEnum):
    """Device class for events."""

    DOORBELL = "doorbell"
    BUTTON = "button"
    MOTION = "motion"


class DoorbellEventType(StrEnum):
    """Standard event types for the doorbell device class."""

    RING = "ring"


class ButtonEventType(StrEnum):
    """Standard event types for the button device class.

    None of these are mandatory: an entity declares only the types whose meaning
    holds for every event the device sends under that name.
    """

    # Physical: the edges of the button
    PRESS_START = "press_start"
    PRESS_END = "press_end"

    # Gesture: what the device concluded
    LONG_PRESS_START = "long_press_start"
    LONG_PRESS_END = "long_press_end"
    SINGLE_PRESS = "single_press"
    MULTI_PRESS = "multi_press"
