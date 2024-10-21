"""Models for the websocket API."""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import Field, field_serializer, field_validator
from zigpy.types.named import EUI64

from zha.application.model import (
    DeviceFullyInitializedEvent,
    DeviceJoinedEvent,
    DeviceLeftEvent,
    DeviceOfflineEvent,
    DeviceOnlineEvent,
    DeviceRemovedEvent,
    GroupAddedEvent,
    GroupMemberAddedEvent,
    GroupMemberRemovedEvent,
    GroupRemovedEvent,
    RawDeviceInitializedEvent,
)
from zha.application.platforms.model import EntityStateChangedEvent
from zha.model import BaseModel
from zha.websocket.const import APICommands
from zha.zigbee.cluster_handlers.model import ClusterInfo
from zha.zigbee.model import ExtendedDeviceInfo, GroupInfo, ZHAEvent


class WebSocketCommand(BaseModel):
    """Command for the websocket API."""

    message_id: int = 1
    command: Literal[
        APICommands.STOP_SERVER,
        APICommands.CLIENT_LISTEN_RAW_ZCL,
        APICommands.CLIENT_DISCONNECT,
        APICommands.CLIENT_LISTEN,
        APICommands.BUTTON_PRESS,
        APICommands.PLATFORM_ENTITY_REFRESH_STATE,
        APICommands.ALARM_CONTROL_PANEL_DISARM,
        APICommands.ALARM_CONTROL_PANEL_ARM_HOME,
        APICommands.ALARM_CONTROL_PANEL_ARM_AWAY,
        APICommands.ALARM_CONTROL_PANEL_ARM_NIGHT,
        APICommands.ALARM_CONTROL_PANEL_TRIGGER,
        APICommands.START_NETWORK,
        APICommands.STOP_NETWORK,
        APICommands.UPDATE_NETWORK_TOPOLOGY,
        APICommands.RECONFIGURE_DEVICE,
        APICommands.GET_DEVICES,
        APICommands.GET_GROUPS,
        APICommands.PERMIT_JOINING,
        APICommands.ADD_GROUP_MEMBERS,
        APICommands.REMOVE_GROUP_MEMBERS,
        APICommands.CREATE_GROUP,
        APICommands.REMOVE_GROUPS,
        APICommands.REMOVE_DEVICE,
        APICommands.READ_CLUSTER_ATTRIBUTES,
        APICommands.WRITE_CLUSTER_ATTRIBUTE,
        APICommands.SIREN_TURN_ON,
        APICommands.SIREN_TURN_OFF,
        APICommands.SELECT_SELECT_OPTION,
        APICommands.NUMBER_SET_VALUE,
        APICommands.LOCK_CLEAR_USER_CODE,
        APICommands.LOCK_SET_USER_CODE,
        APICommands.LOCK_ENAABLE_USER_CODE,
        APICommands.LOCK_DISABLE_USER_CODE,
        APICommands.LOCK_LOCK,
        APICommands.LOCK_UNLOCK,
        APICommands.LIGHT_TURN_OFF,
        APICommands.LIGHT_TURN_ON,
        APICommands.FAN_SET_PERCENTAGE,
        APICommands.FAN_SET_PRESET_MODE,
        APICommands.FAN_TURN_ON,
        APICommands.FAN_TURN_OFF,
        APICommands.COVER_STOP,
        APICommands.COVER_SET_POSITION,
        APICommands.COVER_OPEN,
        APICommands.COVER_CLOSE,
        APICommands.CLIMATE_SET_TEMPERATURE,
        APICommands.CLIMATE_SET_HVAC_MODE,
        APICommands.CLIMATE_SET_FAN_MODE,
        APICommands.CLIMATE_SET_PRESET_MODE,
        APICommands.SWITCH_TURN_ON,
        APICommands.SWITCH_TURN_OFF,
    ]


class WebSocketCommandResponse(WebSocketCommand):
    """Websocket command response."""

    message_type: Literal["result"] = "result"
    success: bool


class ErrorResponse(WebSocketCommandResponse):
    """Error response model."""

    success: bool = False
    error_code: str
    error_message: str
    zigbee_error_code: Optional[str]
    command: Literal[
        "error.start_network",
        "error.stop_network",
        "error.remove_device",
        "error.stop_server",
        "error.light_turn_on",
        "error.light_turn_off",
        "error.switch_turn_on",
        "error.switch_turn_off",
        "error.lock_lock",
        "error.lock_unlock",
        "error.lock_set_user_lock_code",
        "error.lock_clear_user_lock_code",
        "error.lock_disable_user_lock_code",
        "error.lock_enable_user_lock_code",
        "error.fan_turn_on",
        "error.fan_turn_off",
        "error.fan_set_percentage",
        "error.fan_set_preset_mode",
        "error.cover_open",
        "error.cover_close",
        "error.cover_set_position",
        "error.cover_stop",
        "error.climate_set_fan_mode",
        "error.climate_set_hvac_mode",
        "error.climate_set_preset_mode",
        "error.climate_set_temperature",
        "error.button_press",
        "error.alarm_control_panel_disarm",
        "error.alarm_control_panel_arm_home",
        "error.alarm_control_panel_arm_away",
        "error.alarm_control_panel_arm_night",
        "error.alarm_control_panel_trigger",
        "error.select_select_option",
        "error.siren_turn_on",
        "error.siren_turn_off",
        "error.number_set_value",
        "error.platform_entity_refresh_state",
        "error.client_listen",
        "error.client_listen_raw_zcl",
        "error.client_disconnect",
        "error.reconfigure_device",
        "error.UpdateNetworkTopologyCommand",
    ]


class DefaultResponse(WebSocketCommandResponse):
    """Default command response."""

    command: Literal[
        "start_network",
        "stop_network",
        "remove_device",
        "stop_server",
        "light_turn_on",
        "light_turn_off",
        "switch_turn_on",
        "switch_turn_off",
        "lock_lock",
        "lock_unlock",
        "lock_set_user_lock_code",
        "lock_clear_user_lock_code",
        "lock_disable_user_lock_code",
        "lock_enable_user_lock_code",
        "fan_turn_on",
        "fan_turn_off",
        "fan_set_percentage",
        "fan_set_preset_mode",
        "cover_open",
        "cover_close",
        "cover_set_position",
        "cover_stop",
        "climate_set_fan_mode",
        "climate_set_hvac_mode",
        "climate_set_preset_mode",
        "climate_set_temperature",
        "button_press",
        "alarm_control_panel_disarm",
        "alarm_control_panel_arm_home",
        "alarm_control_panel_arm_away",
        "alarm_control_panel_arm_night",
        "alarm_control_panel_trigger",
        "select_select_option",
        "siren_turn_on",
        "siren_turn_off",
        "number_set_value",
        "platform_entity_refresh_state",
        "client_listen",
        "client_listen_raw_zcl",
        "client_disconnect",
        "reconfigure_device",
        "UpdateNetworkTopologyCommand",
    ]


class PermitJoiningResponse(WebSocketCommandResponse):
    """Get devices response."""

    command: Literal["permit_joining"] = "permit_joining"
    duration: int


class GetDevicesResponse(WebSocketCommandResponse):
    """Get devices response."""

    command: Literal["get_devices"] = "get_devices"
    devices: dict[EUI64, ExtendedDeviceInfo]

    @field_serializer("devices", check_fields=False)
    def serialize_devices(self, devices: dict[EUI64, ExtendedDeviceInfo]) -> dict:
        """Serialize devices."""
        return {str(ieee): device for ieee, device in devices.items()}

    @field_validator("devices", mode="before", check_fields=False)
    @classmethod
    def convert_devices(
        cls, devices: dict[str, ExtendedDeviceInfo]
    ) -> dict[EUI64, ExtendedDeviceInfo]:
        """Convert devices."""
        if all(isinstance(ieee, str) for ieee in devices):
            return {EUI64.convert(ieee): device for ieee, device in devices.items()}
        return devices


class ReadClusterAttributesResponse(WebSocketCommandResponse):
    """Read cluster attributes response."""

    command: Literal["read_cluster_attributes"] = "read_cluster_attributes"
    device: ExtendedDeviceInfo
    cluster: ClusterInfo
    manufacturer_code: Optional[int]
    succeeded: dict[str, Any]
    failed: dict[str, Any]


class AttributeStatus(BaseModel):
    """Attribute status."""

    attribute: str
    status: str


class WriteClusterAttributeResponse(WebSocketCommandResponse):
    """Write cluster attribute response."""

    command: Literal["write_cluster_attribute"] = "write_cluster_attribute"
    device: ExtendedDeviceInfo
    cluster: ClusterInfo
    manufacturer_code: Optional[int]
    response: AttributeStatus


class GroupsResponse(WebSocketCommandResponse):
    """Get groups response."""

    command: Literal["get_groups", "remove_groups"]
    groups: dict[int, GroupInfo]


class UpdateGroupResponse(WebSocketCommandResponse):
    """Update group response."""

    command: Literal["create_group", "add_group_members", "remove_group_members"]
    group: GroupInfo


CommandResponses = Annotated[
    Union[
        DefaultResponse,
        ErrorResponse,
        GetDevicesResponse,
        GroupsResponse,
        PermitJoiningResponse,
        UpdateGroupResponse,
        ReadClusterAttributesResponse,
        WriteClusterAttributeResponse,
    ],
    Field(discriminator="command"),
]


Events = Annotated[
    Union[
        EntityStateChangedEvent,
        DeviceJoinedEvent,
        RawDeviceInitializedEvent,
        DeviceFullyInitializedEvent,
        DeviceLeftEvent,
        DeviceRemovedEvent,
        GroupRemovedEvent,
        GroupAddedEvent,
        GroupMemberAddedEvent,
        GroupMemberRemovedEvent,
        DeviceOfflineEvent,
        DeviceOnlineEvent,
        ZHAEvent,
    ],
    Field(discriminator="event"),
]
