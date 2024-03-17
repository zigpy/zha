"""Constants for Zigbee Home Automation."""

from enum import StrEnum
from typing import Final

STATE_CHANGED: Final[str] = "state_changed"
EVENT: Final[str] = "event"
EVENT_TYPE: Final[str] = "event_type"

MESSAGE_TYPE: Final[str] = "message_type"


class EventTypes(StrEnum):
    """WS event types."""

    CONTROLLER_EVENT = "controller_event"
    PLATFORM_ENTITY_EVENT = "platform_entity_event"
    RAW_ZCL_EVENT = "raw_zcl_event"
    DEVICE_EVENT = "device_event"
