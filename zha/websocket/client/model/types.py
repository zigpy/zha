"""Models that represent types for the zhaws.client.

Types are representations of the objects that exist in zhawss.
"""

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import ValidationInfo, field_serializer, field_validator
from pydantic.fields import Field
from zigpy.types.named import EUI64, NWK
from zigpy.zdo.types import NodeDescriptor as ZigpyNodeDescriptor

from zha.event import EventBase
from zha.model import BaseModel


class BaseEventedModel(EventBase, BaseModel):
    """Base evented model."""


class Cluster(BaseModel):
    """Cluster model."""

    id: int
    endpoint_attribute: str
    name: str
    endpoint_id: int
    type: str
    commands: list[str]


class ClusterHandler(BaseModel):
    """Cluster handler model."""

    unique_id: str
    cluster: Cluster
    class_name: str
    generic_id: str
    endpoint_id: int
    id: str
    status: str


class Endpoint(BaseModel):
    """Endpoint model."""

    id: int
    unique_id: str


class GenericState(BaseModel):
    """Default state model."""

    class_name: Literal[
        "ZHAAlarmControlPanel",
        "Number",
        "DefaultToneSelectEntity",
        "DefaultSirenLevelSelectEntity",
        "DefaultStrobeLevelSelectEntity",
        "DefaultStrobeSelectEntity",
        "AnalogInput",
        "Humidity",
        "SoilMoisture",
        "LeafWetness",
        "Illuminance",
        "Pressure",
        "Temperature",
        "CarbonDioxideConcentration",
        "CarbonMonoxideConcentration",
        "VOCLevel",
        "PPBVOCLevel",
        "FormaldehydeConcentration",
        "ThermostatHVACAction",
        "SinopeHVACAction",
        "RSSISensor",
        "LQISensor",
        "LastSeenSensor",
    ]
    state: Union[str, bool, int, float, None] = None


class DeviceCounterSensorState(BaseModel):
    """Device counter sensor state model."""

    class_name: Literal["DeviceCounterSensor"] = "DeviceCounterSensor"
    state: int


class DeviceTrackerState(BaseModel):
    """Device tracker state model."""

    class_name: Literal["DeviceTracker"] = "DeviceTracker"
    connected: bool
    battery_level: Optional[float] = None


class BooleanState(BaseModel):
    """Boolean value state model."""

    class_name: Literal[
        "Accelerometer",
        "Occupancy",
        "Opening",
        "BinaryInput",
        "Motion",
        "IASZone",
        "Siren",
    ]
    state: bool


class CoverState(BaseModel):
    """Cover state model."""

    class_name: Literal["Cover"] = "Cover"
    current_position: int
    state: Optional[str] = None
    is_opening: bool
    is_closing: bool
    is_closed: bool


class ShadeState(BaseModel):
    """Cover state model."""

    class_name: Literal["Shade", "KeenVent"]
    current_position: Optional[int] = (
        None  # TODO: how should we represent this when it is None?
    )
    is_closed: bool
    state: Optional[str] = None


class FanState(BaseModel):
    """Fan state model."""

    class_name: Literal["Fan", "FanGroup"]
    preset_mode: Optional[str] = (
        None  # TODO: how should we represent these when they are None?
    )
    percentage: Optional[int] = (
        None  # TODO: how should we represent these when they are None?
    )
    is_on: bool
    speed: Optional[str] = None


class LockState(BaseModel):
    """Lock state model."""

    class_name: Literal["Lock"] = "Lock"
    is_locked: bool


class BatteryState(BaseModel):
    """Battery state model."""

    class_name: Literal["Battery"] = "Battery"
    state: Optional[Union[str, float, int]] = None
    battery_size: Optional[str] = None
    battery_quantity: Optional[int] = None
    battery_voltage: Optional[float] = None


class ElectricalMeasurementState(BaseModel):
    """Electrical measurement state model."""

    class_name: Literal[
        "ElectricalMeasurement",
        "ElectricalMeasurementApparentPower",
        "ElectricalMeasurementRMSCurrent",
        "ElectricalMeasurementRMSVoltage",
    ]
    state: Optional[Union[str, float, int]] = None
    measurement_type: Optional[str] = None
    active_power_max: Optional[str] = None
    rms_current_max: Optional[str] = None
    rms_voltage_max: Optional[str] = None


class LightState(BaseModel):
    """Light state model."""

    class_name: Literal["Light", "HueLight", "ForceOnLight", "LightGroup"]
    on: bool
    brightness: Optional[int] = None
    hs_color: Optional[tuple[float, float]] = None
    color_temp: Optional[int] = None
    effect: Optional[str] = None
    off_brightness: Optional[int] = None


class ThermostatState(BaseModel):
    """Thermostat state model."""

    class_name: Literal[
        "Thermostat",
        "SinopeTechnologiesThermostat",
        "ZenWithinThermostat",
        "MoesThermostat",
        "BecaThermostat",
    ]
    current_temperature: Optional[float] = None
    target_temperature: Optional[float] = None
    target_temperature_low: Optional[float] = None
    target_temperature_high: Optional[float] = None
    hvac_action: Optional[str] = None
    hvac_mode: Optional[str] = None
    preset_mode: Optional[str] = None
    fan_mode: Optional[str] = None


class SwitchState(BaseModel):
    """Switch state model."""

    class_name: Literal["Switch", "SwitchGroup"]
    state: bool


class SmareEnergyMeteringState(BaseModel):
    """Smare energy metering state model."""

    class_name: Literal["SmartEnergyMetering", "SmartEnergySummation"]
    state: Optional[Union[str, float, int]] = None
    device_type: Optional[str] = None
    status: Optional[str] = None


class BaseEntity(BaseEventedModel):
    """Base platform entity model."""

    unique_id: str
    platform: str
    class_name: str
    fallback_name: str | None = None
    translation_key: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    entity_category: str | None = None
    entity_registry_enabled_default: bool
    enabled: bool


class BasePlatformEntity(BaseEntity):
    """Base platform entity model."""

    device_ieee: EUI64
    endpoint_id: int


class LockEntity(BasePlatformEntity):
    """Lock entity model."""

    class_name: Literal["Lock"]
    state: LockState


class DeviceTrackerEntity(BasePlatformEntity):
    """Device tracker entity model."""

    class_name: Literal["DeviceTracker"]
    state: DeviceTrackerState


class CoverEntity(BasePlatformEntity):
    """Cover entity model."""

    class_name: Literal["Cover"]
    state: CoverState


class ShadeEntity(BasePlatformEntity):
    """Shade entity model."""

    class_name: Literal["Shade", "KeenVent"]
    state: ShadeState


class BinarySensorEntity(BasePlatformEntity):
    """Binary sensor model."""

    class_name: Literal[
        "Accelerometer", "Occupancy", "Opening", "BinaryInput", "Motion", "IASZone"
    ]
    attribute_name: str
    state: BooleanState


class BaseSensorEntity(BasePlatformEntity):
    """Sensor model."""

    attribute: Optional[str]
    decimals: int
    divisor: int
    multiplier: Union[int, float]
    unit: Optional[int | str]


class SensorEntity(BaseSensorEntity):
    """Sensor entity model."""

    class_name: Literal[
        "AnalogInput",
        "Humidity",
        "SoilMoisture",
        "LeafWetness",
        "Illuminance",
        "Pressure",
        "Temperature",
        "CarbonDioxideConcentration",
        "CarbonMonoxideConcentration",
        "VOCLevel",
        "PPBVOCLevel",
        "FormaldehydeConcentration",
        "ThermostatHVACAction",
        "SinopeHVACAction",
        "RSSISensor",
        "LQISensor",
        "LastSeenSensor",
    ]
    state: GenericState


class DeviceCounterSensorEntity(BaseEntity):
    """Device counter sensor model."""

    class_name: Literal["DeviceCounterSensor"]
    counter: str
    counter_value: int
    counter_groups: str
    counter_group: str
    state: DeviceCounterSensorState

    @field_validator("state", mode="before", check_fields=False)
    @classmethod
    def convert_state(
        cls, state: dict | int | None, validation_info: ValidationInfo
    ) -> DeviceCounterSensorState:
        """Convert counter value to counter_value."""
        if state is not None:
            if isinstance(state, int):
                return DeviceCounterSensorState(state=state)
            if isinstance(state, dict):
                if "state" in state:
                    return DeviceCounterSensorState(state=state["state"])
                else:
                    return DeviceCounterSensorState(
                        state=validation_info.data["counter_value"]
                    )
        return DeviceCounterSensorState(state=validation_info.data["counter_value"])


class BatteryEntity(BaseSensorEntity):
    """Battery entity model."""

    class_name: Literal["Battery"]
    state: BatteryState


class ElectricalMeasurementEntity(BaseSensorEntity):
    """Electrical measurement entity model."""

    class_name: Literal[
        "ElectricalMeasurement",
        "ElectricalMeasurementApparentPower",
        "ElectricalMeasurementRMSCurrent",
        "ElectricalMeasurementRMSVoltage",
    ]
    state: ElectricalMeasurementState


class SmartEnergyMeteringEntity(BaseSensorEntity):
    """Smare energy metering entity model."""

    class_name: Literal["SmartEnergyMetering", "SmartEnergySummation"]
    state: SmareEnergyMeteringState


class AlarmControlPanelEntity(BasePlatformEntity):
    """Alarm control panel model."""

    class_name: Literal["ZHAAlarmControlPanel"]
    supported_features: int
    code_required_arm_actions: bool
    max_invalid_tries: int
    state: GenericState


class ButtonEntity(BasePlatformEntity):
    """Button model."""

    class_name: Literal["IdentifyButton"]
    command: str


class FanEntity(BasePlatformEntity):
    """Fan model."""

    class_name: Literal["Fan"]
    preset_modes: list[str]
    supported_features: int
    speed_count: int
    speed_list: list[str]
    percentage_step: float
    state: FanState


class LightEntity(BasePlatformEntity):
    """Light model."""

    class_name: Literal["Light", "HueLight", "ForceOnLight"]
    supported_features: int
    min_mireds: int
    max_mireds: int
    effect_list: Optional[list[str]]
    state: LightState


class NumberEntity(BasePlatformEntity):
    """Number entity model."""

    class_name: Literal["Number"]
    engineering_units: Optional[
        int
    ]  # TODO: how should we represent this when it is None?
    application_type: Optional[
        int
    ]  # TODO: how should we represent this when it is None?
    step: Optional[float]  # TODO: how should we represent this when it is None?
    min_value: float
    max_value: float
    state: GenericState


class SelectEntity(BasePlatformEntity):
    """Select entity model."""

    class_name: Literal[
        "DefaultToneSelectEntity",
        "DefaultSirenLevelSelectEntity",
        "DefaultStrobeLevelSelectEntity",
        "DefaultStrobeSelectEntity",
    ]
    enum: str
    options: list[str]
    state: GenericState


class ThermostatEntity(BasePlatformEntity):
    """Thermostat entity model."""

    class_name: Literal[
        "Thermostat",
        "SinopeTechnologiesThermostat",
        "ZenWithinThermostat",
        "MoesThermostat",
        "BecaThermostat",
    ]
    state: ThermostatState
    hvac_modes: tuple[str, ...]
    fan_modes: Optional[list[str]]
    preset_modes: Optional[list[str]]


class SirenEntity(BasePlatformEntity):
    """Siren entity model."""

    class_name: Literal["Siren"]
    available_tones: Optional[Union[list[Union[int, str]], dict[int, str]]]
    supported_features: int
    state: BooleanState


class SwitchEntity(BasePlatformEntity):
    """Switch entity model."""

    class_name: Literal["Switch"]
    state: SwitchState


class DeviceSignatureEndpoint(BaseModel):
    """Device signature endpoint model."""

    profile_id: Optional[str] = None
    device_type: Optional[str] = None
    input_clusters: list[str]
    output_clusters: list[str]

    @field_validator("profile_id", mode="before", check_fields=False)
    @classmethod
    def convert_profile_id(cls, profile_id: int | str) -> str:
        """Convert profile_id."""
        if isinstance(profile_id, int):
            return f"0x{profile_id:04x}"
        return profile_id

    @field_validator("device_type", mode="before", check_fields=False)
    @classmethod
    def convert_device_type(cls, device_type: int | str) -> str:
        """Convert device_type."""
        if isinstance(device_type, int):
            return f"0x{device_type:04x}"
        return device_type

    @field_validator("input_clusters", mode="before", check_fields=False)
    @classmethod
    def convert_input_clusters(cls, input_clusters: list[int | str]) -> list[str]:
        """Convert input_clusters."""
        clusters = []
        for cluster_id in input_clusters:
            if isinstance(cluster_id, int):
                clusters.append(f"0x{cluster_id:04x}")
            else:
                clusters.append(cluster_id)
        return clusters

    @field_validator("output_clusters", mode="before", check_fields=False)
    @classmethod
    def convert_output_clusters(cls, output_clusters: list[int | str]) -> list[str]:
        """Convert output_clusters."""
        clusters = []
        for cluster_id in output_clusters:
            if isinstance(cluster_id, int):
                clusters.append(f"0x{cluster_id:04x}")
            else:
                clusters.append(cluster_id)
        return clusters


class NodeDescriptor(BaseModel):
    """Node descriptor model."""

    logical_type: int
    complex_descriptor_available: bool
    user_descriptor_available: bool
    reserved: int
    aps_flags: int
    frequency_band: int
    mac_capability_flags: int
    manufacturer_code: int
    maximum_buffer_size: int
    maximum_incoming_transfer_size: int
    server_mask: int
    maximum_outgoing_transfer_size: int
    descriptor_capability_field: int


class DeviceSignature(BaseModel):
    """Device signature model."""

    node_descriptor: Optional[NodeDescriptor] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    endpoints: dict[int, DeviceSignatureEndpoint]

    @field_validator("node_descriptor", mode="before", check_fields=False)
    @classmethod
    def convert_node_descriptor(
        cls, node_descriptor: ZigpyNodeDescriptor
    ) -> NodeDescriptor:
        """Convert node descriptor."""
        if isinstance(node_descriptor, ZigpyNodeDescriptor):
            return node_descriptor.as_dict()
        return node_descriptor


class BaseDevice(BaseModel):
    """Base device model."""

    ieee: EUI64
    nwk: str
    manufacturer: str
    model: str
    name: str
    quirk_applied: bool
    quirk_class: Union[str, None] = None
    manufacturer_code: int
    power_source: str
    lqi: Union[int, None] = None
    rssi: Union[int, None] = None
    last_seen: str
    available: bool
    device_type: Literal["Coordinator", "Router", "EndDevice"]
    signature: DeviceSignature

    @field_validator("nwk", mode="before", check_fields=False)
    @classmethod
    def convert_nwk(cls, nwk: NWK) -> str:
        """Convert nwk to hex."""
        if isinstance(nwk, NWK):
            return repr(nwk)
        return nwk

    @field_serializer("ieee")
    def serialize_ieee(self, ieee):
        """Customize how ieee is serialized."""
        if isinstance(ieee, EUI64):
            return str(ieee)
        return ieee


class Device(BaseDevice):
    """Device model."""

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
            Field(discriminator="class_name"),  # noqa: F821
        ],
    ]
    neighbors: list[Any]
    device_automation_triggers: dict[str, dict[str, Any]]

    @field_validator("entities", mode="before", check_fields=False)
    @classmethod
    def convert_entities(cls, entities: dict) -> dict:
        """Convert entities keys from tuple to string."""
        if all(isinstance(k, tuple) for k in entities):
            return {f"{k[0]}.{k[1]}": v for k, v in entities.items()}
        assert all(isinstance(k, str) for k in entities)
        return entities

    @field_validator("device_automation_triggers", mode="before", check_fields=False)
    @classmethod
    def convert_device_automation_triggers(cls, triggers: dict) -> dict:
        """Convert device automation triggers keys from tuple to string."""
        if all(isinstance(k, tuple) for k in triggers):
            return {f"{k[0]}~{k[1]}": v for k, v in triggers.items()}
        return triggers


class GroupEntity(BaseEntity):
    """Group entity model."""

    group_id: int
    state: Any


class LightGroupEntity(GroupEntity):
    """Group entity model."""

    class_name: Literal["LightGroup"]
    state: LightState


class FanGroupEntity(GroupEntity):
    """Group entity model."""

    class_name: Literal["FanGroup"]
    state: FanState


class SwitchGroupEntity(GroupEntity):
    """Group entity model."""

    class_name: Literal["SwitchGroup"]
    state: SwitchState


class GroupMember(BaseModel):
    """Group member model."""

    ieee: EUI64
    endpoint_id: int
    device: Device = Field(alias="device_info")
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
            Field(discriminator="class_name"),  # noqa: F821
        ],
    ]


class Group(BaseModel):
    """Group model."""

    name: str
    id: int
    members: dict[EUI64, GroupMember]
    entities: dict[
        str,
        Annotated[
            Union[LightGroupEntity, FanGroupEntity, SwitchGroupEntity],
            Field(discriminator="class_name"),  # noqa: F821
        ],
    ]

    @field_validator("members", mode="before", check_fields=False)
    @classmethod
    def convert_members(cls, members: dict | list[dict]) -> dict:
        """Convert members."""

        converted_members = {}
        if isinstance(members, dict):
            return {EUI64.convert(k): v for k, v in members.items()}
        for member in members:
            if "device" in member:
                ieee = member["device"]["ieee"]
            else:
                ieee = member["device_info"]["ieee"]
            if isinstance(ieee, str):
                ieee = EUI64.convert(ieee)
            elif isinstance(ieee, list) and not isinstance(ieee, EUI64):
                ieee = EUI64.deserialize(ieee)[0]
            converted_members[ieee] = member
        return converted_members

    @field_serializer("members")
    def serialize_members(self, members):
        """Customize how members are serialized."""
        data = {str(k): v.model_dump(by_alias=True) for k, v in members.items()}
        return data


class GroupMemberReference(BaseModel):
    """Group member reference model."""

    ieee: EUI64
    endpoint_id: int
