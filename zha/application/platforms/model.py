"""Models for the ZHA platforms module."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import Field, ValidationInfo, field_validator
from zigpy.types.named import EUI64

from zha.application.discovery import Platform
from zha.event import EventBase
from zha.model import BaseEvent, BaseEventedModel, BaseModel
from zha.zigbee.cluster_handlers.model import ClusterHandlerInfo


class EntityCategory(StrEnum):
    """Category of an entity."""

    # Config: An entity which allows changing the configuration of a device.
    CONFIG = "config"

    # Diagnostic: An entity exposing some configuration parameter,
    # or diagnostics of a device.
    DIAGNOSTIC = "diagnostic"


class BaseEntityInfo(BaseModel):
    """Information about a base entity."""

    platform: Platform
    unique_id: str
    class_name: str
    translation_key: str | None
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    entity_registry_enabled_default: bool
    enabled: bool = True
    fallback_name: str | None
    state: dict[str, Any]

    # For platform entities
    cluster_handlers: list[ClusterHandlerInfo]
    device_ieee: EUI64 | None
    endpoint_id: int | None
    available: bool | None

    # For group entities
    group_id: int | None


class BaseIdentifiers(BaseModel):
    """Identifiers for the base entity."""

    unique_id: str
    platform: Platform


class PlatformEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the platform entity."""

    device_ieee: EUI64
    endpoint_id: int


class GroupEntityIdentifiers(BaseIdentifiers):
    """Identifiers for the group entity."""

    group_id: int


class GenericState(BaseModel):
    """Default state model."""

    class_name: Literal[
        "AlarmControlPanel",
        "Number",
        "MaxHeatSetpointLimit",
        "MinHeatSetpointLimit",
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
        "ElectricalMeasurementFrequency",
        "ElectricalMeasurementPowerFactor",
        "PolledElectricalMeasurement",
        "PiHeatingDemand",
        "SetpointChangeSource",
        "SetpointChangeSourceTimestamp",
        "TimeLeft",
        "DeviceTemperature",
        "WindowCoveringTypeSensor",
        "StartUpCurrentLevelConfigurationEntity",
        "StartUpColorTemperatureConfigurationEntity",
        "StartupOnOffSelectEntity",
        "PM25",
        "Sensor",
        "OnOffTransitionTimeConfigurationEntity",
        "OnLevelConfigurationEntity",
        "NumberConfigurationEntity",
        "OnTransitionTimeConfigurationEntity",
        "OffTransitionTimeConfigurationEntity",
        "DefaultMoveRateConfigurationEntity",
        "FilterLifeTime",
        "IkeaDeviceRunTime",
        "IkeaFilterRunTime",
        "AqaraSmokeDensityDbm",
        "HueV1MotionSensitivity",
        "EnumSensor",
        "AqaraMonitoringMode",
        "AqaraApproachDistance",
        "AqaraMotionSensitivity",
        "AqaraCurtainMotorPowerSourceSensor",
        "AqaraCurtainHookStateSensor",
        "AqaraMagnetAC01DetectionDistance",
        "AqaraMotionDetectionInterval",
        "HueV2MotionSensitivity",
        "TiRouterTransmitPower",
        "ZCLEnumSelectEntity",
        "SmartEnergySummationReceived",
        "IdentifyButton",
        "FrostLockResetButton",
        "Button",
        "WriteAttributeButton",
        "AqaraSelfTestButton",
        "NoPresenceStatusResetButton",
        "TimestampSensor",
        "DanfossOpenWindowDetection",
        "DanfossLoadEstimate",
        "DanfossAdaptationRunStatus",
        "DanfossPreheatTime",
        "DanfossSoftwareErrorCode",
        "DanfossMotorStepCounter",
    ]
    available: Optional[bool] = None
    state: Union[str, bool, int, float, datetime, None] = None


class DeviceCounterSensorState(BaseModel):
    """Device counter sensor state model."""

    class_name: Literal["DeviceCounterSensor"] = "DeviceCounterSensor"
    state: int


class DeviceTrackerState(BaseModel):
    """Device tracker state model."""

    class_name: Literal["DeviceScannerEntity"] = "DeviceScannerEntity"
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
        "FrostLock",
        "BinarySensor",
        "ReplaceFilter",
        "AqaraLinkageAlarmState",
        "HueOccupancy",
        "AqaraE1CurtainMotorOpenedByHandBinarySensor",
        "DanfossHeatRequired",
        "DanfossMountingModeActive",
        "DanfossPreheatStatus",
    ]
    state: bool


class CoverState(BaseModel):
    """Cover state model."""

    class_name: Literal["Cover"] = "Cover"
    current_position: int | None = None
    state: Optional[str] = None
    is_opening: bool | None = None
    is_closing: bool | None = None
    is_closed: bool | None = None


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

    class_name: Literal["Fan", "FanGroup", "IkeaFan", "KofFan"]
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

    class_name: Literal["Lock", "DoorLock"] = "Lock"
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
    rms_voltage_max: Optional[int] = None


class LightState(BaseModel):
    """Light state model."""

    class_name: Literal[
        "Light", "HueLight", "ForceOnLight", "LightGroup", "MinTransitionLight"
    ]
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
        "ZONNSMARTThermostat",
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

    class_name: Literal[
        "Switch",
        "SwitchGroup",
        "WindowCoveringInversionSwitch",
        "ChildLock",
        "DisableLed",
        "AqaraHeartbeatIndicator",
        "AqaraLinkageAlarm",
        "AqaraBuzzerManualMute",
        "AqaraBuzzerManualAlarm",
        "HueMotionTriggerIndicatorSwitch",
        "AqaraE1CurtainMotorHooksLockedSwitch",
        "P1MotionTriggerIndicatorSwitch",
        "ConfigurableAttributeSwitch",
        "OnOffWindowDetectionFunctionConfigurationEntity",
    ]
    state: bool


class SmareEnergyMeteringState(BaseModel):
    """Smare energy metering state model."""

    class_name: Literal["SmartEnergyMetering", "SmartEnergySummation"]
    state: Optional[Union[str, float, int]] = None
    device_type: Optional[str] = None
    status: Optional[str] = None


class FirmwareUpdateState(BaseModel):
    """Firmware update state model."""

    class_name: Literal["FirmwareUpdateEntity"]
    available: bool
    installed_version: str | None
    in_progress: bool | None
    progress: int | None
    latest_version: str | None
    release_summary: str | None
    release_notes: str | None
    release_url: str | None


class EntityStateChangedEvent(BaseEvent):
    """Event for when an entity state changes."""

    event_type: Literal["entity"] = "entity"
    event: Literal["state_changed"] = "state_changed"
    platform: Platform
    unique_id: str
    device_ieee: Optional[EUI64] = None
    endpoint_id: Optional[int] = None
    group_id: Optional[int] = None
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
                FirmwareUpdateState,
                DeviceCounterSensorState,
            ]
        ],
        Field(discriminator="class_name"),  # noqa: F821
    ]


class BasePlatformEntity(EventBase, BaseEntityInfo):
    """Base platform entity model."""


class FirmwareUpdateEntity(BasePlatformEntity):
    """Firmware update entity model."""

    class_name: Literal["FirmwareUpdateEntity"]
    state: FirmwareUpdateState


class LockEntity(BasePlatformEntity):
    """Lock entity model."""

    class_name: Literal["Lock", "DoorLock"]
    state: LockState


class DeviceTrackerEntity(BasePlatformEntity):
    """Device tracker entity model."""

    class_name: Literal["DeviceScannerEntity"]
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
        "Accelerometer",
        "Occupancy",
        "Opening",
        "BinaryInput",
        "Motion",
        "IASZone",
        "FrostLock",
        "BinarySensor",
        "ReplaceFilter",
        "AqaraLinkageAlarmState",
        "HueOccupancy",
        "AqaraE1CurtainMotorOpenedByHandBinarySensor",
        "DanfossHeatRequired",
        "DanfossMountingModeActive",
        "DanfossPreheatStatus",
    ]
    attribute_name: str | None = None
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
        "ElectricalMeasurementFrequency",
        "ElectricalMeasurementPowerFactor",
        "PolledElectricalMeasurement",
        "PiHeatingDemand",
        "SetpointChangeSource",
        "SetpointChangeSourceTimestamp",
        "TimeLeft",
        "DeviceTemperature",
        "WindowCoveringTypeSensor",
        "PM25",
        "Sensor",
        "IkeaDeviceRunTime",
        "IkeaFilterRunTime",
        "AqaraSmokeDensityDbm",
        "EnumSensor",
        "AqaraCurtainMotorPowerSourceSensor",
        "AqaraCurtainHookStateSensor",
        "SmartEnergySummationReceived",
        "TimestampSensor",
        "DanfossOpenWindowDetection",
        "DanfossLoadEstimate",
        "DanfossAdaptationRunStatus",
        "DanfossPreheatTime",
        "DanfossSoftwareErrorCode",
        "DanfossMotorStepCounter",
    ]
    state: GenericState


class DeviceCounterSensorEntity(BaseEventedModel, BaseEntityInfo):
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

    class_name: Literal["AlarmControlPanel"]
    supported_features: int
    code_arm_required: bool
    max_invalid_tries: int
    state: GenericState


class ButtonEntity(
    BasePlatformEntity
):  # TODO split into two models CommandButton and WriteAttributeButton
    """Button model."""

    class_name: Literal[
        "IdentifyButton",
        "FrostLockResetButton",
        "Button",
        "WriteAttributeButton",
        "AqaraSelfTestButton",
        "NoPresenceStatusResetButton",
    ]
    command: str | None = None
    attribute_name: str | None = None
    attribute_value: Any | None = None
    state: GenericState


class FanEntity(BasePlatformEntity):
    """Fan model."""

    class_name: Literal["Fan", "IkeaFan", "KofFan"]
    preset_modes: list[str]
    supported_features: int
    speed_count: int
    speed_list: list[str]
    percentage_step: float | None = None
    state: FanState


class LightEntity(BasePlatformEntity):
    """Light model."""

    class_name: Literal["Light", "HueLight", "ForceOnLight", "MinTransitionLight"]
    supported_features: int
    min_mireds: int
    max_mireds: int
    effect_list: Optional[list[str]]
    state: LightState


class NumberEntity(BasePlatformEntity):
    """Number entity model."""

    class_name: Literal[
        "Number",
        "MaxHeatSetpointLimit",
        "MinHeatSetpointLimit",
        "StartUpCurrentLevelConfigurationEntity",
        "StartUpColorTemperatureConfigurationEntity",
        "OnOffTransitionTimeConfigurationEntity",
        "OnLevelConfigurationEntity",
        "NumberConfigurationEntity",
        "OnTransitionTimeConfigurationEntity",
        "OffTransitionTimeConfigurationEntity",
        "DefaultMoveRateConfigurationEntity",
        "FilterLifeTime",
        "AqaraMotionDetectionInterval",
        "TiRouterTransmitPower",
    ]
    engineering_units: int | None = (
        None  # TODO: how should we represent this when it is None?
    )
    application_type: int | None = (
        None  # TODO: how should we represent this when it is None?
    )
    step: Optional[float] = None  # TODO: how should we represent this when it is None?
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
        "StartupOnOffSelectEntity",
        "HueV1MotionSensitivity",
        "AqaraMonitoringMode",
        "AqaraApproachDistance",
        "AqaraMotionSensitivity",
        "AqaraMagnetAC01DetectionDistance",
        "HueV2MotionSensitivity",
        "ZCLEnumSelectEntity",
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
        "ZONNSMARTThermostat",
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

    class_name: Literal[
        "Switch",
        "WindowCoveringInversionSwitch",
        "ChildLock",
        "DisableLed",
        "AqaraHeartbeatIndicator",
        "AqaraLinkageAlarm",
        "AqaraBuzzerManualMute",
        "AqaraBuzzerManualAlarm",
        "HueMotionTriggerIndicatorSwitch",
        "AqaraE1CurtainMotorHooksLockedSwitch",
        "P1MotionTriggerIndicatorSwitch",
        "ConfigurableAttributeSwitch",
        "OnOffWindowDetectionFunctionConfigurationEntity",
    ]
    state: SwitchState


class GroupEntity(EventBase, BaseEntityInfo):
    """Group entity model."""


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
