"""Constants for Zigbee Home Automation."""

from enum import Enum, StrEnum
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


class UndefinedType(Enum):
    """Singleton type for use with not set sentinel values."""

    _singleton = 0


UNDEFINED = UndefinedType._singleton  # noqa: SLF001
