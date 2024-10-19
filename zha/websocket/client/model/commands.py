"""Models that represent commands and command responses."""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import field_validator
from pydantic.fields import Field
from zigpy.types.named import EUI64

from zha.model import BaseModel
from zha.websocket.client.model.events import MinimalCluster, MinimalDevice
from zha.websocket.client.model.types import Device, Group


class CommandResponse(BaseModel):
    """Command response model."""

    message_type: Literal["result"] = "result"
    message_id: int
    success: bool


class ErrorResponse(CommandResponse):
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


class DefaultResponse(CommandResponse):
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


class PermitJoiningResponse(CommandResponse):
    """Get devices response."""

    command: Literal["permit_joining"] = "permit_joining"
    duration: int


class GetDevicesResponse(CommandResponse):
    """Get devices response."""

    command: Literal["get_devices"] = "get_devices"
    devices: dict[EUI64, Device]

    @field_validator("devices", mode="before", check_fields=False)
    @classmethod
    def convert_devices_device_ieee(
        cls, devices: dict[str, dict]
    ) -> dict[EUI64, Device]:
        """Convert device ieee to EUI64."""
        return {EUI64.convert(k): Device(**v) for k, v in devices.items()}


class ReadClusterAttributesResponse(CommandResponse):
    """Read cluster attributes response."""

    command: Literal["read_cluster_attributes"] = "read_cluster_attributes"
    device: MinimalDevice
    cluster: MinimalCluster
    manufacturer_code: Optional[int]
    succeeded: dict[str, Any]
    failed: dict[str, Any]


class AttributeStatus(BaseModel):
    """Attribute status."""

    attribute: str
    status: str


class WriteClusterAttributeResponse(CommandResponse):
    """Write cluster attribute response."""

    command: Literal["write_cluster_attribute"] = "write_cluster_attribute"
    device: MinimalDevice
    cluster: MinimalCluster
    manufacturer_code: Optional[int]
    response: AttributeStatus


class GroupsResponse(CommandResponse):
    """Get groups response."""

    command: Literal["get_groups", "remove_groups"]
    groups: dict[int, Group]


class UpdateGroupResponse(CommandResponse):
    """Update group response."""

    command: Literal["create_group", "add_group_members", "remove_group_members"]
    group: Group


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
    Field(discriminator="command"),  # noqa: F821
]
