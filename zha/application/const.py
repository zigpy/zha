"""Constants for ZHA."""

from __future__ import annotations

import enum
from typing import Final

ATTR_ACTIVE_COORDINATOR = "active_coordinator"
ATTR_ARGS = "args"
ATTR_ATTRIBUTE = "attribute"
ATTR_ATTRIBUTE_ID = "attribute_id"
ATTR_ATTRIBUTE_NAME = "attribute_name"
ATTR_AVAILABLE = "available"
ATTR_CLUSTER_ID = "cluster_id"
ATTR_CLUSTER_TYPE = "cluster_type"
ATTR_COMMAND: Final = "command"
ATTR_COMMAND_TYPE = "command_type"
ATTR_DEVICE_IEEE = "device_ieee"
ATTR_DEVICE_TYPE = "device_type"
ATTR_ENDPOINTS = "endpoints"
ATTR_ENDPOINT_NAMES = "endpoint_names"
ATTR_ENDPOINT_ID = "endpoint_id"
ATTR_IEEE = "ieee"
ATTR_IN_CLUSTERS = "in_clusters"
ATTR_LAST_SEEN = "last_seen"
ATTR_LEVEL = "level"
ATTR_LQI = "lqi"
ATTR_MANUFACTURER = "manufacturer"
ATTR_MANUFACTURER_CODE = "manufacturer_code"
ATTR_MEMBERS = "members"
ATTR_MODEL = "model"
ATTR_NAME = "name"
ATTR_NEIGHBORS = "neighbors"
ATTR_NODE_DESCRIPTOR = "node_descriptor"
ATTR_NWK = "nwk"
ATTR_OUT_CLUSTERS = "out_clusters"
ATTR_PARAMS = "params"
ATTR_POWER_SOURCE = "power_source"
ATTR_PROFILE_ID = "profile_id"
ATTR_QUIRK_APPLIED = "quirk_applied"
ATTR_QUIRK_CLASS = "quirk_class"
ATTR_QUIRK_ID = "quirk_id"
ATTR_ROUTES = "routes"
ATTR_RSSI = "rssi"
ATTR_SIGNATURE = "signature"
ATTR_TYPE = "type"
ATTR_UNIQUE_ID = "unique_id"
ATTR_VALUE = "value"
ATTR_WARNING_DEVICE_DURATION = "duration"
ATTR_WARNING_DEVICE_MODE = "mode"
ATTR_WARNING_DEVICE_STROBE = "strobe"
ATTR_WARNING_DEVICE_STROBE_DUTY_CYCLE = "duty_cycle"
ATTR_WARNING_DEVICE_STROBE_INTENSITY = "intensity"

# Class of device within its domain
ATTR_DEVICE_CLASS: Final = "device_class"

BAUD_RATES = [2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200, 128000, 256000]

CLUSTER_DETAILS = "cluster_details"

CLUSTER_COMMAND_SERVER = "server"
CLUSTER_COMMANDS_CLIENT = "client_commands"
CLUSTER_COMMANDS_SERVER = "server_commands"
CLUSTER_TYPE_IN = "in"
CLUSTER_TYPE_OUT = "out"

CONF_USE_THREAD = "use_thread"

CONF_DEFAULT_CONSIDER_UNAVAILABLE_MAINS = 60 * 60 * 2  # 2 hours
CONF_DEFAULT_CONSIDER_UNAVAILABLE_BATTERY = 60 * 60 * 6  # 6 hours

POWER_MAINS_POWERED = "Mains"
POWER_BATTERY_OR_UNKNOWN = "Battery or Unknown"

# Device is in away mode
PRESET_AWAY = "away"
PRESET_SCHEDULE = "Schedule"
PRESET_COMPLEX = "Complex"
PRESET_TEMP_MANUAL = "Temporary manual"
# Device turn all valve full up
PRESET_BOOST = "boost"
# No preset is active
PRESET_NONE = "none"

ENTITY_METADATA = "entity_metadata"


UNKNOWN = "unknown"
UNKNOWN_MANUFACTURER = "unk_manufacturer"
UNKNOWN_MODEL = "unk_model"

ZHA_CLUSTER_BIND_EVENT = "zha_cluster_bind"
ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT = "zha_cluster_configure_reporting"
ZHA_DEVICE_CONFIGURED_EVENT = "zha_device_configured"
ZHA_EVENT = "zha_event"
ZHA_DEVICE_UPDATED_EVENT = "zha_device_updated_event"
ZHA_DEVICE_ENTITY_ADDED_EVENT = "zha_device_entity_added_event"
ZHA_DEVICE_ENTITY_REMOVED_EVENT = "zha_device_entity_removed_event"
ZHA_GW_MSG = "zha_gateway_message"
ZHA_GW_MSG_DEVICE_FULL_INIT = "device_fully_initialized"
ZHA_GW_MSG_DEVICE_INFO = "device_info"
ZHA_GW_MSG_DEVICE_JOINED = "device_joined"
ZHA_GW_MSG_DEVICE_LEFT = "device_left"
ZHA_GW_MSG_DEVICE_REMOVED = "device_removed"
ZHA_GW_MSG_GROUP_ADDED = "group_added"
ZHA_GW_MSG_GROUP_INFO = "group_info"
ZHA_GW_MSG_GROUP_MEMBER_ADDED = "group_member_added"
ZHA_GW_MSG_GROUP_MEMBER_REMOVED = "group_member_removed"
ZHA_GW_MSG_GROUP_REMOVED = "group_removed"
ZHA_GW_MSG_LOG_ENTRY = "log_entry"
ZHA_GW_MSG_LOG_OUTPUT = "log_output"
ZHA_GW_MSG_RAW_INIT = "raw_device_initialized"
ZHA_GW_MSG_CONNECTION_LOST = "connection_lost"


class UniqueIdMigration(enum.Enum):
    """Migrateion root for unique ID."""

    LEGACY_CLUSTER = "legacy_cluster"
    LEGACY_ENDPOINT = "legacy_endpoint"

    DEVICE = "device"
    CLUSTER = "cluster"
    ENDPOINT = "endpoint"
