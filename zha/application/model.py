"""Models for the ZHA application module."""

from enum import Enum
from typing import Any, Literal

from zigpy.types.named import EUI64, NWK

from zha.model import BaseEvent, BaseModel
from zha.zigbee.model import DeviceInfo, ExtendedDeviceInfo, GroupInfo


class DevicePairingStatus(Enum):
    """Status of a device."""

    PAIRED = 1
    INTERVIEW_COMPLETE = 2
    CONFIGURED = 3
    INITIALIZED = 4


class DeviceInfoWithPairingStatus(DeviceInfo):
    """Information about a device with pairing status."""

    pairing_status: DevicePairingStatus


class ExtendedDeviceInfoWithPairingStatus(ExtendedDeviceInfo):
    """Information about a device with pairing status."""

    pairing_status: DevicePairingStatus


class DeviceJoinedDeviceInfo(BaseModel):
    """Information about a device."""

    ieee: EUI64
    nwk: NWK
    pairing_status: DevicePairingStatus


class ConnectionLostEvent(BaseEvent):
    """Event to signal that the connection to the radio has been lost."""

    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["connection_lost"] = "connection_lost"
    exception: Exception | None = None


class DeviceJoinedEvent(BaseEvent):
    """Event to signal that a device has joined the network."""

    device_info: DeviceJoinedDeviceInfo
    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["device_joined"] = "device_joined"


class DeviceLeftEvent(BaseEvent):
    """Event to signal that a device has left the network."""

    ieee: EUI64
    nwk: NWK
    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["device_left"] = "device_left"


class RawDeviceInitializedDeviceInfo(DeviceJoinedDeviceInfo):
    """Information about a device that has been initialized without quirks loaded."""

    model: str
    manufacturer: str
    signature: dict[str, Any]


class RawDeviceInitializedEvent(BaseEvent):
    """Event to signal that a device has been initialized without quirks loaded."""

    device_info: RawDeviceInitializedDeviceInfo
    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["raw_device_initialized"] = "raw_device_initialized"


class DeviceFullyInitializedEvent(BaseEvent):
    """Event to signal that a device has been fully initialized."""

    device_info: ExtendedDeviceInfoWithPairingStatus
    new_join: bool = False
    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["device_fully_initialized"] = "device_fully_initialized"


class GroupRemovedEvent(BaseEvent):
    """Group removed event."""

    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["group_removed"] = "group_removed"
    group_info: GroupInfo


class GroupAddedEvent(BaseEvent):
    """Group added event."""

    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["group_added"] = "group_added"
    group_info: GroupInfo


class GroupMemberAddedEvent(BaseEvent):
    """Group member added event."""

    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["group_member_added"] = "group_member_added"
    group_info: GroupInfo


class GroupMemberRemovedEvent(BaseEvent):
    """Group member removed event."""

    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["group_member_removed"] = "group_member_removed"
    group_info: GroupInfo


class DeviceRemovedEvent(BaseEvent):
    """Event to signal that a device has been removed."""

    device_info: ExtendedDeviceInfo
    event_type: Literal["zha_gateway_message"] = "zha_gateway_message"
    event: Literal["device_removed"] = "device_removed"


class DeviceOfflineEvent(BaseEvent):
    """Device offline event."""

    event: Literal["device_offline"] = "device_offline"
    event_type: Literal["device_event"] = "device_event"
    device: ExtendedDeviceInfo


class DeviceOnlineEvent(BaseEvent):
    """Device online event."""

    event: Literal["device_online"] = "device_online"
    event_type: Literal["device_event"] = "device_event"
    device: ExtendedDeviceInfo
