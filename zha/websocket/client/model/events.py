"""Event models for zhawss.

Events are unprompted messages from the server -> client and they contain only the data that is necessary to
handle the event.
"""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic.fields import Field
from zigpy.types.named import EUI64

from zha.model import BaseEvent, BaseModel
from zha.websocket.client.model.types import (
    BaseDevice,
    BatteryState,
    BooleanState,
    CoverState,
    Device,
    DeviceSignature,
    DeviceTrackerState,
    ElectricalMeasurementState,
    FanState,
    GenericState,
    Group,
    LightState,
    LockState,
    ShadeState,
    SmareEnergyMeteringState,
    SwitchState,
    ThermostatState,
)


class MinimalPlatformEntity(BaseModel):
    """Platform entity model."""

    unique_id: str
    platform: str


class MinimalEndpoint(BaseModel):
    """Minimal endpoint model."""

    id: int
    unique_id: str


class MinimalDevice(BaseModel):
    """Minimal device model."""

    ieee: EUI64


class Attribute(BaseModel):
    """Attribute model."""

    id: int
    name: str
    value: Any = None


class MinimalCluster(BaseModel):
    """Minimal cluster model."""

    id: int
    endpoint_attribute: str
    name: str
    endpoint_id: int


class MinimalClusterHandler(BaseModel):
    """Minimal cluster handler model."""

    unique_id: str
    cluster: MinimalCluster


class MinimalGroup(BaseModel):
    """Minimal group model."""

    id: int


class PlatformEntityStateChangedEvent(BaseEvent):
    """Platform entity event."""

    event_type: Literal["platform_entity_event"] = "platform_entity_event"
    event: Literal["platform_entity_state_changed"] = "platform_entity_state_changed"
    platform_entity: MinimalPlatformEntity
    endpoint: Optional[MinimalEndpoint] = None
    device: Optional[MinimalDevice] = None
    group: Optional[MinimalGroup] = None
    state: Annotated[
        Optional[
            Union[
                DeviceTrackerState,
                CoverState,
                ShadeState,
                FanState,
                LockState,
                BatteryState,
                ElectricalMeasurementState,
                LightState,
                SwitchState,
                SmareEnergyMeteringState,
                GenericState,
                BooleanState,
                ThermostatState,
            ]
        ],
        Field(discriminator="class_name"),  # noqa: F821
    ]


class ZCLAttributeUpdatedEvent(BaseEvent):
    """ZCL attribute updated event."""

    event_type: Literal["raw_zcl_event"] = "raw_zcl_event"
    event: Literal["attribute_updated"] = "attribute_updated"
    device: MinimalDevice
    cluster_handler: MinimalClusterHandler
    attribute: Attribute
    endpoint: MinimalEndpoint


class ControllerEvent(BaseEvent):
    """Controller event."""

    event_type: Literal["controller_event"] = "controller_event"


class DevicePairingEvent(ControllerEvent):
    """Device pairing event."""

    pairing_status: str


class DeviceJoinedEvent(DevicePairingEvent):
    """Device joined event."""

    event: Literal["device_joined"] = "device_joined"
    ieee: EUI64
    nwk: str


class RawDeviceInitializedEvent(DevicePairingEvent):
    """Raw device initialized event."""

    event: Literal["raw_device_initialized"] = "raw_device_initialized"
    ieee: EUI64
    nwk: str
    manufacturer: str
    model: str
    signature: DeviceSignature


class DeviceFullyInitializedEvent(DevicePairingEvent):
    """Device fully initialized event."""

    event: Literal["device_fully_initialized"] = "device_fully_initialized"
    device: Device
    new_join: bool


class DeviceConfiguredEvent(DevicePairingEvent):
    """Device configured event."""

    event: Literal["device_configured"] = "device_configured"
    device: BaseDevice


class DeviceLeftEvent(ControllerEvent):
    """Device left event."""

    event: Literal["device_left"] = "device_left"
    ieee: EUI64
    nwk: str


class DeviceRemovedEvent(ControllerEvent):
    """Device removed event."""

    event: Literal["device_removed"] = "device_removed"
    device: Device


class DeviceOfflineEvent(BaseEvent):
    """Device offline event."""

    event: Literal["device_offline"] = "device_offline"
    event_type: Literal["device_event"] = "device_event"
    device: MinimalDevice


class DeviceOnlineEvent(BaseEvent):
    """Device online event."""

    event: Literal["device_online"] = "device_online"
    event_type: Literal["device_event"] = "device_event"
    device: MinimalDevice


class ZHAEvent(BaseEvent):
    """ZHA event."""

    event: Literal["zha_event"] = "zha_event"
    event_type: Literal["device_event"] = "device_event"
    device: MinimalDevice
    cluster_handler: MinimalClusterHandler
    endpoint: MinimalEndpoint
    command: str
    args: Union[list, dict]
    params: dict[str, Any]


class GroupRemovedEvent(ControllerEvent):
    """Group removed event."""

    event: Literal["group_removed"] = "group_removed"
    group: Group


class GroupAddedEvent(ControllerEvent):
    """Group added event."""

    event: Literal["group_added"] = "group_added"
    group: Group


class GroupMemberAddedEvent(ControllerEvent):
    """Group member added event."""

    event: Literal["group_member_added"] = "group_member_added"
    group: Group


class GroupMemberRemovedEvent(ControllerEvent):
    """Group member removed event."""

    event: Literal["group_member_removed"] = "group_member_removed"
    group: Group


Events = Annotated[
    Union[
        PlatformEntityStateChangedEvent,
        ZCLAttributeUpdatedEvent,
        DeviceJoinedEvent,
        RawDeviceInitializedEvent,
        DeviceFullyInitializedEvent,
        DeviceConfiguredEvent,
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
    Field(discriminator="event"),  # noqa: F821
]
