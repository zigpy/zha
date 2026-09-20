"""Constants for the event platform."""

from enum import StrEnum

ATTR_MULTI_PRESS_COUNT = "multi_press_count"


class EventDeviceClass(StrEnum):
    """Device class for events."""

    DOORBELL = "doorbell"
    BUTTON = "button"
    MOTION = "motion"


class DoorbellEventType(StrEnum):
    """Standard event types for the doorbell device class."""

    RING = "ring"


class ButtonEventType(StrEnum):
    """Standard event types for the button device class."""

    PRESS_START = "press_start"
    PRESS_END = "press_end"
    LONG_PRESS_START = "long_press_start"
    LONG_PRESS_END = "long_press_end"
    MULTI_PRESS_ONGOING = "multi_press_ongoing"
    MULTI_PRESS_END = "multi_press_end"
