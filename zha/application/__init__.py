"""Application module for Zigbee Home Automation."""

from enum import StrEnum


class Platform(StrEnum):
    """Available entity platforms."""

    ALARM_CONTROL_PANEL = "alarm_control_panel"
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    CLIMATE = "climate"
    COVER = "cover"
    DEVICE_TRACKER = "device_tracker"
    EVENT = "event"
    FAN = "fan"
    LIGHT = "light"
    LOCK = "lock"
    NUMBER = "number"
    SELECT = "select"
    SENSOR = "sensor"
    SIREN = "siren"
    SWITCH = "switch"
    VALVE = "valve"
    UNKNOWN = "unknown"
    UPDATE = "update"
