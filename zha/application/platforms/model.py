"""Models for the ZHA platforms module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, TypeVar

from zigpy.types.named import EUI64

from zha.application.discovery import Platform
from zha.event import EventBase
from zha.model import BaseModel
from zha.zigbee.cluster_handlers.model import ClusterHandlerInfo


class BaseEntityInfo(BaseModel):
    """Information about a base entity."""

    platform: Platform
    unique_id: str
    class_name: str
    translation_key: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    entity_category: str | None = None
    entity_registry_enabled_default: bool
    enabled: bool = True
    fallback_name: str | None = None
    state: dict[str, Any]

    # For platform entities
    cluster_handlers: list[ClusterHandlerInfo]
    device_ieee: EUI64 | None = None
    endpoint_id: int | None = None
    available: bool | None = None

    # For group entities
    group_id: int | None = None


T = TypeVar("T", bound=BaseEntityInfo)


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
    available: bool | None = None
    state: str | bool | int | float | datetime | None = None


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


class BasePlatformEntityInfo(EventBase, BaseEntityInfo):
    """Base platform entity model."""
