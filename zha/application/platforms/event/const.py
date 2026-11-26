"""Constants for the event platform."""

from enum import StrEnum

ATTR_PRESS_COUNT = "press_count"

# Event data of the rotary event types
ATTR_DIRECTION = "direction"
ATTR_STEPS = "steps"
ATTR_DEGREES = "degrees"
ATTR_PRESSED = "pressed"


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


class RotaryEventType(StrEnum):
    """Event types for rotary controls: dials, knobs, rings and scroll wheels.

    Proposed in zigpy/backlog#84 for ZHA and Matter, as the rotary counterpart of
    the button event types. Home Assistant has no rotary device class yet, so
    rotary event entities have no device class until it does. As with buttons, an
    entity declares only the types whose meaning holds for every event the device
    sends under that name.
    """

    # The control turned: one event per report of movement from the device
    ROTATION = "rotation"
    # The device reported that a turn started, without reporting movement
    ROTATION_START = "rotation_start"
    # The device reported that a turn stopped
    ROTATION_END = "rotation_end"


class RotaryDirection(StrEnum):
    """Direction of a turn, in the `direction` event data of rotary event types.

    For controls that aren't round, clockwise is the direction the device labels
    as increase, up or right.
    """

    CLOCKWISE = "clockwise"
    COUNTER_CLOCKWISE = "counter_clockwise"
