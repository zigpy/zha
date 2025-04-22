"""Constants for ZHA."""

from __future__ import annotations

import enum
from typing import Final

import bellows.zigbee.application
import zigpy.application
import zigpy.types as t
import zigpy_deconz.zigbee.application
import zigpy_xbee.zigbee.application
import zigpy_zigate.zigbee.application
import zigpy_znp.zigbee.application

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

ZCL_INIT_ATTRS = "ZCL_INIT_ATTRS"
REPORT_CONFIG = "REPORT_CONFIG"

_ControllerClsType = type[zigpy.application.ControllerApplication]


class RadioType(enum.Enum):
    """Possible options for radio type."""

    ezsp = (
        "EZSP = Silicon Labs EmberZNet protocol: Elelabs, HUSBZB-1, Telegesis",
        bellows.zigbee.application.ControllerApplication,
    )
    znp = (
        "ZNP = Texas Instruments Z-Stack ZNP protocol: CC253x, CC26x2, CC13x2",
        zigpy_znp.zigbee.application.ControllerApplication,
    )
    deconz = (
        "deCONZ = dresden elektronik deCONZ protocol: ConBee I/II, RaspBee I/II",
        zigpy_deconz.zigbee.application.ControllerApplication,
    )
    zigate = (
        "ZiGate = ZiGate Zigbee radios: PiZiGate, ZiGate USB-TTL, ZiGate WiFi",
        zigpy_zigate.zigbee.application.ControllerApplication,
    )
    xbee = (
        "XBee = Digi XBee Zigbee radios: Digi XBee Series 2, 2C, 3",
        zigpy_xbee.zigbee.application.ControllerApplication,
    )

    @classmethod
    def list(cls) -> list[str]:
        """Return a list of descriptions."""
        return [e.description for e in RadioType]

    @classmethod
    def get_by_description(cls, description: str) -> RadioType:
        """Get radio by description."""
        for radio in cls:
            if radio.description == description:
                return radio
        raise ValueError

    def __init__(self, description: str, controller_cls: _ControllerClsType) -> None:
        """Init instance."""
        self._desc = description
        self._ctrl_cls = controller_cls

    @property
    def controller(self) -> _ControllerClsType:
        """Return controller class."""
        return self._ctrl_cls

    @property
    def description(self) -> str:
        """Return radio type description."""
        return self._desc

    @property
    def pretty_name(self) -> str:
        """Return radio type name."""
        return self.description.split(" = ", 1)[0]


UNKNOWN = "unknown"
UNKNOWN_MANUFACTURER = "unk_manufacturer"
UNKNOWN_MODEL = "unk_model"

WARNING_DEVICE_MODE_STOP = 0
WARNING_DEVICE_MODE_BURGLAR = 1
WARNING_DEVICE_MODE_FIRE = 2
WARNING_DEVICE_MODE_EMERGENCY = 3
WARNING_DEVICE_MODE_POLICE_PANIC = 4
WARNING_DEVICE_MODE_FIRE_PANIC = 5
WARNING_DEVICE_MODE_EMERGENCY_PANIC = 6

WARNING_DEVICE_STROBE_NO = 0
WARNING_DEVICE_STROBE_YES = 1

WARNING_DEVICE_SOUND_LOW = 0
WARNING_DEVICE_SOUND_MEDIUM = 1
WARNING_DEVICE_SOUND_HIGH = 2
WARNING_DEVICE_SOUND_VERY_HIGH = 3

WARNING_DEVICE_STROBE_LOW = 0x00
WARNING_DEVICE_STROBE_MEDIUM = 0x01
WARNING_DEVICE_STROBE_HIGH = 0x02
WARNING_DEVICE_STROBE_VERY_HIGH = 0x03

WARNING_DEVICE_SQUAWK_MODE_ARMED = 0
WARNING_DEVICE_SQUAWK_MODE_DISARMED = 1

ZHA_CLUSTER_HANDLER_MSG = "zha_channel_message"
ZHA_CLUSTER_HANDLER_MSG_BIND = "zha_channel_bind"
ZHA_CLUSTER_HANDLER_MSG_CFG_RPT = "zha_channel_configure_reporting"
ZHA_CLUSTER_HANDLER_MSG_DATA = "zha_channel_msg_data"
ZHA_CLUSTER_HANDLER_CFG_DONE = "zha_channel_cfg_done"
ZHA_CLUSTER_HANDLER_READS_PER_REQ = 5
ZHA_EVENT = "zha_event"
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


class Strobe(t.enum8):
    """Strobe enum."""

    No_Strobe = 0x00
    Strobe = 0x01


class UniqueIdMigration(enum.Enum):
    """Migrateion root for unique ID."""

    LEGACY_CLUSTER = "legacy_cluster"
    LEGACY_ENDPOINT = "legacy_endpoint"

    DEVICE = "device"
    CLUSTER = "cluster"
    ENDPOINT = "endpoint"
