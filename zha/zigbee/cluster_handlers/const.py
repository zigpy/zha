"""Constants for the cluster_handlers module."""

from typing import Final

REPORT_CONFIG_ATTR_PER_REQ: Final[int] = 3
REPORT_CONFIG_MAX_INT: Final[int] = 900
REPORT_CONFIG_MAX_INT_BATTERY_SAVE: Final[int] = 10800
REPORT_CONFIG_MIN_INT: Final[int] = 30
REPORT_CONFIG_MIN_INT_ASAP: Final[int] = 1
REPORT_CONFIG_MIN_INT_IMMEDIATE: Final[int] = 0
REPORT_CONFIG_MIN_INT_OP: Final[int] = 5
REPORT_CONFIG_MIN_INT_BATTERY_SAVE: Final[int] = 3600
REPORT_CONFIG_RPT_CHANGE: Final[int] = 1
REPORT_CONFIG_DEFAULT: tuple[int, int, int] = (
    REPORT_CONFIG_MIN_INT,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_RPT_CHANGE,
)
REPORT_CONFIG_ASAP: tuple[int, int, int] = (
    REPORT_CONFIG_MIN_INT_ASAP,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_RPT_CHANGE,
)
REPORT_CONFIG_BATTERY_SAVE: tuple[int, int, int] = (
    REPORT_CONFIG_MIN_INT_BATTERY_SAVE,
    REPORT_CONFIG_MAX_INT_BATTERY_SAVE,
    REPORT_CONFIG_RPT_CHANGE,
)
REPORT_CONFIG_IMMEDIATE: tuple[int, int, int] = (
    REPORT_CONFIG_MIN_INT_IMMEDIATE,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_RPT_CHANGE,
)
REPORT_CONFIG_OP: tuple[int, int, int] = (
    REPORT_CONFIG_MIN_INT_OP,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_RPT_CHANGE,
)
CLUSTER_READS_PER_REQ: Final[int] = 5

CLUSTER_HANDLER_ACCELEROMETER: Final[str] = "accelerometer"
CLUSTER_HANDLER_BINARY_INPUT: Final[str] = "binary_input"
CLUSTER_HANDLER_ANALOG_INPUT: Final[str] = "analog_input"
CLUSTER_HANDLER_ANALOG_OUTPUT: Final[str] = "analog_output"
CLUSTER_HANDLER_ATTRIBUTE: Final[str] = "attribute"
CLUSTER_HANDLER_BASIC: Final[str] = "basic"
CLUSTER_HANDLER_COLOR: Final[str] = "light_color"
CLUSTER_HANDLER_COVER: Final[str] = "window_covering"
CLUSTER_HANDLER_DIAGNOSTIC: Final[str] = "diagnostic"
CLUSTER_HANDLER_DEVICE_TEMPERATURE: Final[str] = "device_temperature"
CLUSTER_HANDLER_DOORLOCK: Final[str] = "door_lock"
CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT: Final[str] = "electrical_measurement"
CLUSTER_HANDLER_EVENT_RELAY: Final[str] = "event_relay"
CLUSTER_HANDLER_FAN: Final[str] = "fan"
CLUSTER_HANDLER_HUMIDITY: Final[str] = "humidity"
CLUSTER_HANDLER_HUE_OCCUPANCY: Final[str] = "philips_occupancy"
CLUSTER_HANDLER_SOIL_MOISTURE: Final[str] = "soil_moisture"
CLUSTER_HANDLER_LEAF_WETNESS: Final[str] = "leaf_wetness"
CLUSTER_HANDLER_IAS_ACE: Final[str] = "ias_ace"
CLUSTER_HANDLER_IAS_WD: Final[str] = "ias_wd"
CLUSTER_HANDLER_IDENTIFY: Final[str] = "identify"
CLUSTER_HANDLER_ILLUMINANCE: Final[str] = "illuminance"
CLUSTER_HANDLER_LEVEL: Final[str] = "level"
CLUSTER_HANDLER_MULTISTATE_INPUT: Final[str] = "multistate_input"
CLUSTER_HANDLER_OCCUPANCY: Final[str] = "occupancy"
CLUSTER_HANDLER_ON_OFF: Final[str] = "on_off"
CLUSTER_HANDLER_OTA: Final[str] = "ota"
CLUSTER_HANDLER_POWER_CONFIGURATION: Final[str] = "power"
CLUSTER_HANDLER_PRESSURE: Final[str] = "pressure"
CLUSTER_HANDLER_SHADE: Final[str] = "shade"
CLUSTER_HANDLER_SMARTENERGY_METERING: Final[str] = "smartenergy_metering"
CLUSTER_HANDLER_TEMPERATURE: Final[str] = "temperature"
CLUSTER_HANDLER_THERMOSTAT: Final[str] = "thermostat"
CLUSTER_HANDLER_ZDO: Final[str] = "zdo"
CLUSTER_HANDLER_ZONE: Final[str] = "ias_zone"
ZONE: Final[str] = CLUSTER_HANDLER_ZONE
CLUSTER_HANDLER_INOVELLI = "inovelli_vzm31sn_cluster"

AQARA_OPPLE_CLUSTER: Final[int] = 0xFCC0
IKEA_AIR_PURIFIER_CLUSTER: Final[int] = 0xFC7D
IKEA_REMOTE_CLUSTER: Final[int] = 0xFC80
INOVELLI_CLUSTER: Final[int] = 0xFC31
OSRAM_BUTTON_CLUSTER: Final[int] = 0xFD00
PHILLIPS_REMOTE_CLUSTER: Final[int] = 0xFC00
SMARTTHINGS_ACCELERATION_CLUSTER: Final[int] = 0xFC02
SMARTTHINGS_HUMIDITY_CLUSTER: Final[int] = 0xFC45
SONOFF_CLUSTER: Final[int] = 0xFC11
TUYA_MANUFACTURER_CLUSTER: Final[int] = 0xEF00
VOC_LEVEL_CLUSTER: Final[int] = 0x042E

CLUSTER_HANDLER_EVENT: Final[str] = "cluster_handler_event"
CLUSTER_HANDLER_ATTRIBUTE_UPDATED: Final[str] = "cluster_handler_attribute_updated"
CLUSTER_HANDLER_STATE_CHANGED: Final[str] = "cluster_handler_state_changed"
CLUSTER_HANDLER_LEVEL_CHANGED: Final[str] = "cluster_handler_level_changed"

ATTRIBUTE_ID: Final[str] = "attribute_id"
ATTRIBUTE_NAME: Final[str] = "attribute_name"
ATTRIBUTE_VALUE: Final[str] = "attribute_value"

UNIQUE_ID: Final[str] = "unique_id"
CLUSTER_ID: Final[str] = "cluster_id"
COMMAND: Final[str] = "command"
ARGS: Final[str] = "args"
PARAMS: Final[str] = "params"

SIGNAL_ATTR_UPDATED: Final[str] = "attribute_updated"
SIGNAL_MOVE_LEVEL: Final[str] = "move_level"
SIGNAL_REMOVE: Final[str] = "remove"
SIGNAL_SET_LEVEL: Final[str] = "set_level"
SIGNAL_STATE_ATTR: Final[str] = "update_state_attribute"
UNKNOWN: Final[str] = "unknown"
