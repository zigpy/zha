"""Constants."""

from enum import StrEnum
from typing import Final


class APICommands(StrEnum):
    """WS API commands."""

    # Device commands
    GET_DEVICES = "get_devices"
    REMOVE_DEVICE = "remove_device"
    RECONFIGURE_DEVICE = "reconfigure_device"
    READ_CLUSTER_ATTRIBUTES = "read_cluster_attributes"
    WRITE_CLUSTER_ATTRIBUTE = "write_cluster_attribute"

    # Zigbee API commands
    PERMIT_JOINING = "permit_joining"
    START_NETWORK = "start_network"
    STOP_NETWORK = "stop_network"
    UPDATE_NETWORK_TOPOLOGY = "update_network_topology"

    # Group commands
    GET_GROUPS = "get_groups"
    CREATE_GROUP = "create_group"
    REMOVE_GROUPS = "remove_groups"
    ADD_GROUP_MEMBERS = "add_group_members"
    REMOVE_GROUP_MEMBERS = "remove_group_members"

    # Server API commands
    STOP_SERVER = "stop_server"

    # Light API commands
    LIGHT_TURN_ON = "light_turn_on"
    LIGHT_TURN_OFF = "light_turn_off"

    # Switch API commands
    SWITCH_TURN_ON = "switch_turn_on"
    SWITCH_TURN_OFF = "switch_turn_off"

    SIREN_TURN_ON = "siren_turn_on"
    SIREN_TURN_OFF = "siren_turn_off"

    LOCK_UNLOCK = "lock_unlock"
    LOCK_LOCK = "lock_lock"
    LOCK_SET_USER_CODE = "lock_set_user_lock_code"
    LOCK_ENAABLE_USER_CODE = "lock_enable_user_lock_code"
    LOCK_DISABLE_USER_CODE = "lock_disable_user_lock_code"
    LOCK_CLEAR_USER_CODE = "lock_clear_user_lock_code"

    CLIMATE_SET_TEMPERATURE = "climate_set_temperature"
    CLIMATE_SET_HVAC_MODE = "climate_set_hvac_mode"
    CLIMATE_SET_FAN_MODE = "climate_set_fan_mode"
    CLIMATE_SET_PRESET_MODE = "climate_set_preset_mode"

    COVER_OPEN = "cover_open"
    COVER_CLOSE = "cover_close"
    COVER_STOP = "cover_stop"
    COVER_SET_POSITION = "cover_set_position"

    FAN_TURN_ON = "fan_turn_on"
    FAN_TURN_OFF = "fan_turn_off"
    FAN_SET_PERCENTAGE = "fan_set_percentage"
    FAN_SET_PRESET_MODE = "fan_set_preset_mode"

    BUTTON_PRESS = "button_press"

    ALARM_CONTROL_PANEL_DISARM = "alarm_control_panel_disarm"
    ALARM_CONTROL_PANEL_ARM_HOME = "alarm_control_panel_arm_home"
    ALARM_CONTROL_PANEL_ARM_AWAY = "alarm_control_panel_arm_away"
    ALARM_CONTROL_PANEL_ARM_NIGHT = "alarm_control_panel_arm_night"
    ALARM_CONTROL_PANEL_TRIGGER = "alarm_control_panel_trigger"

    SELECT_SELECT_OPTION = "select_select_option"

    NUMBER_SET_VALUE = "number_set_value"

    PLATFORM_ENTITY_REFRESH_STATE = "platform_entity_refresh_state"

    CLIENT_LISTEN = "client_listen"
    CLIENT_LISTEN_RAW_ZCL = "client_listen_raw_zcl"
    CLIENT_DISCONNECT = "client_disconnect"


class MessageTypes(StrEnum):
    """WS message types."""

    EVENT = "event"
    RESULT = "result"


class EventTypes(StrEnum):
    """WS event types."""

    CONTROLLER_EVENT = "zha_gateway_message"
    PLATFORM_ENTITY_EVENT = "platform_entity_event"
    RAW_ZCL_EVENT = "raw_zcl_event"
    DEVICE_EVENT = "device_event"


class ControllerEvents(StrEnum):
    """WS controller events."""

    DEVICE_JOINED = "device_joined"
    RAW_DEVICE_INITIALIZED = "raw_device_initialized"
    DEVICE_REMOVED = "device_removed"
    DEVICE_LEFT = "device_left"
    DEVICE_FULLY_INITIALIZED = "device_fully_initialized"
    DEVICE_CONFIGURED = "device_configured"
    GROUP_MEMBER_ADDED = "group_member_added"
    GROUP_MEMBER_REMOVED = "group_member_removed"
    GROUP_ADDED = "group_added"
    GROUP_REMOVED = "group_removed"


class PlatformEntityEvents(StrEnum):
    """WS platform entity events."""

    PLATFORM_ENTITY_STATE_CHANGED = "platform_entity_state_changed"


class RawZCLEvents(StrEnum):
    """WS raw ZCL events."""

    ATTRIBUTE_UPDATED = "attribute_updated"


class DeviceEvents(StrEnum):
    """Events that devices can broadcast."""

    DEVICE_OFFLINE = "device_offline"
    DEVICE_ONLINE = "device_online"
    ZHA_EVENT = "zha_event"


ATTR_UNIQUE_ID: Final[str] = "unique_id"
COMMAND: Final[str] = "command"
CONF_BAUDRATE: Final[str] = "baudrate"
CONF_CUSTOM_QUIRKS_PATH: Final[str] = "custom_quirks_path"
CONF_DATABASE: Final[str] = "database_path"
CONF_DEFAULT_LIGHT_TRANSITION: Final[str] = "default_light_transition"
CONF_DEVICE_CONFIG: Final[str] = "device_config"
CONF_ENABLE_IDENTIFY_ON_JOIN: Final[str] = "enable_identify_on_join"
CONF_ENABLE_QUIRKS: Final[str] = "enable_quirks"
CONF_FLOWCONTROL: Final[str] = "flow_control"
CONF_RADIO_TYPE: Final[str] = "radio_type"
CONF_USB_PATH: Final[str] = "usb_path"
CONF_ZIGPY: Final[str] = "zigpy_config"

DEVICE: Final[str] = "device"

EVENT: Final[str] = "event"
EVENT_TYPE: Final[str] = "event_type"

MESSAGE_TYPE: Final[str] = "message_type"

IEEE: Final[str] = "ieee"
NWK: Final[str] = "nwk"
PAIRING_STATUS: Final[str] = "pairing_status"


DEVICES: Final[str] = "devices"
GROUPS: Final[str] = "groups"
DURATION: Final[str] = "duration"
ERROR_CODE: Final[str] = "error_code"
ERROR_MESSAGE: Final[str] = "error_message"
MESSAGE_ID: Final[str] = "message_id"
SUCCESS: Final[str] = "success"
WEBSOCKET_API: Final[str] = "websocket_api"
ZIGBEE_ERROR_CODE: Final[str] = "zigbee_error_code"
