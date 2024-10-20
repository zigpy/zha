"""Models for the ZHA zigbee module."""

from enum import Enum, StrEnum
from typing import Annotated, Any, Literal, Union

from pydantic import Field, field_serializer, field_validator
from zigpy.types import uint1_t, uint8_t
from zigpy.types.named import EUI64, NWK, ExtendedPanId
from zigpy.zdo.types import RouteStatus, _NeighborEnums

from zha.application import Platform
from zha.application.platforms.model import (
    AlarmControlPanelEntity,
    BatteryEntity,
    BinarySensorEntity,
    ButtonEntity,
    CoverEntity,
    DeviceCounterSensorEntity,
    DeviceTrackerEntity,
    ElectricalMeasurementEntity,
    FanEntity,
    FanGroupEntity,
    FirmwareUpdateEntity,
    LightEntity,
    LightGroupEntity,
    LockEntity,
    NumberEntity,
    SelectEntity,
    SensorEntity,
    ShadeEntity,
    SirenEntity,
    SmartEnergyMeteringEntity,
    SwitchEntity,
    SwitchGroupEntity,
    ThermostatEntity,
)
from zha.model import BaseEvent, BaseModel, convert_enum, convert_int


class DeviceStatus(StrEnum):
    """Status of a device."""

    CREATED = "created"
    INITIALIZED = "initialized"


class ZHAEvent(BaseEvent):
    """Event generated when a device wishes to send an arbitrary event."""

    device_ieee: EUI64
    unique_id: str
    data: dict[str, Any]
    event_type: Literal["device_event"] = "device_event"
    event: Literal["zha_event"] = "zha_event"


class ClusterHandlerConfigurationComplete(BaseEvent):
    """Event generated when all cluster handlers are configured."""

    device_ieee: EUI64
    unique_id: str
    event_type: Literal["zha_channel_message"] = "zha_channel_message"
    event: Literal["zha_channel_cfg_done"] = "zha_channel_cfg_done"


class ClusterBinding(BaseModel):
    """Describes a cluster binding."""

    name: str
    type: str
    id: int
    endpoint_id: int


class DeviceInfo(BaseModel):
    """Describes a device."""

    ieee: EUI64
    nwk: NWK
    manufacturer: str
    model: str
    name: str
    quirk_applied: bool
    quirk_class: str
    quirk_id: str | None
    manufacturer_code: int | None
    power_source: str
    lqi: int | None
    rssi: int | None
    last_seen: str
    available: bool
    device_type: str
    signature: dict[str, Any]

    @field_serializer("signature", check_fields=False)
    def serialize_signature(self, signature: dict[str, Any]):
        """Serialize signature."""
        if "node_descriptor" in signature and not isinstance(
            signature["node_descriptor"], dict
        ):
            signature["node_descriptor"] = signature["node_descriptor"].as_dict()
        return signature


class NeighborInfo(BaseModel):
    """Describes a neighbor."""

    device_type: _NeighborEnums.DeviceType
    rx_on_when_idle: _NeighborEnums.RxOnWhenIdle
    relationship: _NeighborEnums.Relationship
    extended_pan_id: ExtendedPanId
    ieee: EUI64
    nwk: NWK
    permit_joining: _NeighborEnums.PermitJoins
    depth: uint8_t
    lqi: uint8_t

    _convert_device_type = field_validator(
        "device_type", mode="before", check_fields=False
    )(convert_enum(_NeighborEnums.DeviceType))

    _convert_rx_on_when_idle = field_validator(
        "rx_on_when_idle", mode="before", check_fields=False
    )(convert_enum(_NeighborEnums.RxOnWhenIdle))

    _convert_relationship = field_validator(
        "relationship", mode="before", check_fields=False
    )(convert_enum(_NeighborEnums.Relationship))

    _convert_permit_joining = field_validator(
        "permit_joining", mode="before", check_fields=False
    )(convert_enum(_NeighborEnums.PermitJoins))

    _convert_depth = field_validator("depth", mode="before", check_fields=False)(
        convert_int(uint8_t)
    )
    _convert_lqi = field_validator("lqi", mode="before", check_fields=False)(
        convert_int(uint8_t)
    )

    @field_validator("extended_pan_id", mode="before", check_fields=False)
    @classmethod
    def convert_extended_pan_id(
        cls, extended_pan_id: Union[str, ExtendedPanId]
    ) -> ExtendedPanId:
        """Convert extended_pan_id to ExtendedPanId."""
        if isinstance(extended_pan_id, str):
            return ExtendedPanId.convert(extended_pan_id)
        return extended_pan_id

    @field_serializer("extended_pan_id", check_fields=False)
    def serialize_extended_pan_id(self, extended_pan_id: ExtendedPanId):
        """Customize how extended_pan_id is serialized."""
        return str(extended_pan_id)

    @field_serializer(
        "device_type",
        "rx_on_when_idle",
        "relationship",
        "permit_joining",
        check_fields=False,
    )
    def serialize_enums(self, enum_value: Enum):
        """Serialize enums by name."""
        return enum_value.name


class RouteInfo(BaseModel):
    """Describes a route."""

    dest_nwk: NWK
    route_status: RouteStatus
    memory_constrained: uint1_t
    many_to_one: uint1_t
    route_record_required: uint1_t
    next_hop: NWK

    _convert_route_status = field_validator(
        "route_status", mode="before", check_fields=False
    )(convert_enum(RouteStatus))

    _convert_memory_constrained = field_validator(
        "memory_constrained", mode="before", check_fields=False
    )(convert_int(uint1_t))

    _convert_many_to_one = field_validator(
        "many_to_one", mode="before", check_fields=False
    )(convert_int(uint1_t))

    _convert_route_record_required = field_validator(
        "route_record_required", mode="before", check_fields=False
    )(convert_int(uint1_t))

    @field_serializer(
        "route_status",
        check_fields=False,
    )
    def serialize_route_status(self, route_status: RouteStatus):
        """Serialize route_status as name."""
        return route_status.name


class EndpointNameInfo(BaseModel):
    """Describes an endpoint name."""

    name: str


class ExtendedDeviceInfo(DeviceInfo):
    """Describes a ZHA device."""

    active_coordinator: bool
    entities: dict[
        tuple[Platform, str],
        Annotated[
            Union[
                SirenEntity,
                SelectEntity,
                NumberEntity,
                LightEntity,
                FanEntity,
                FirmwareUpdateEntity,
                ButtonEntity,
                AlarmControlPanelEntity,
                SensorEntity,
                BinarySensorEntity,
                DeviceTrackerEntity,
                ShadeEntity,
                CoverEntity,
                LockEntity,
                SwitchEntity,
                BatteryEntity,
                ElectricalMeasurementEntity,
                SmartEnergyMeteringEntity,
                ThermostatEntity,
                DeviceCounterSensorEntity,
            ],
            Field(discriminator="class_name"),
        ],
    ]
    neighbors: list[NeighborInfo]
    routes: list[RouteInfo]
    endpoint_names: list[EndpointNameInfo]
    device_automation_triggers: dict[tuple[str, str], dict[str, Any]]

    @field_validator(
        "device_automation_triggers", "entities", mode="before", check_fields=False
    )
    @classmethod
    def validate_tuple_keyed_dicts(
        cls,
        tuple_keyed_dict: dict[tuple[str, str], Any] | dict[str, dict[str, Any]],
    ) -> dict[tuple[str, str], Any] | dict[str, dict[str, Any]]:
        """Validate device_automation_triggers."""
        if all(isinstance(key, str) for key in tuple_keyed_dict):
            return {
                tuple(key.split(",")): item for key, item in tuple_keyed_dict.items()
            }
        return tuple_keyed_dict


class GroupMemberReference(BaseModel):
    """Describes a group member."""

    ieee: EUI64
    endpoint_id: int


class GroupEntityReference(BaseModel):
    """Reference to a group entity."""

    entity_id: str
    name: str | None = None
    original_name: str | None = None


class GroupMemberInfo(BaseModel):
    """Describes a group member."""

    ieee: EUI64
    endpoint_id: int
    device_info: ExtendedDeviceInfo
    entities: dict[
        str,
        Annotated[
            Union[
                SirenEntity,
                SelectEntity,
                NumberEntity,
                LightEntity,
                FanEntity,
                ButtonEntity,
                AlarmControlPanelEntity,
                FirmwareUpdateEntity,
                SensorEntity,
                BinarySensorEntity,
                DeviceTrackerEntity,
                ShadeEntity,
                CoverEntity,
                LockEntity,
                SwitchEntity,
                BatteryEntity,
                ElectricalMeasurementEntity,
                SmartEnergyMeteringEntity,
                ThermostatEntity,
            ],
            Field(discriminator="class_name"),
        ],
    ]


class GroupInfo(BaseModel):
    """Describes a group."""

    group_id: int
    name: str
    members: list[GroupMemberInfo]
    entities: dict[
        str,
        Annotated[
            Union[LightGroupEntity, FanGroupEntity, SwitchGroupEntity],
            Field(discriminator="class_name"),
        ],
    ]

    @property
    def members_by_ieee(self) -> dict[EUI64, GroupMemberInfo]:
        """Return members by ieee."""
        return {member.ieee: member for member in self.members}
