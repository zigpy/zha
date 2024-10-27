"""Models for the sensor platform."""

from __future__ import annotations

from typing import Literal

from pydantic import ValidationInfo, field_validator
from zigpy.types.named import EUI64

from zha.application.platforms.model import (
    BaseEntityInfo,
    BaseIdentifiers,
    BasePlatformEntityInfo,
    GenericState,
)
from zha.application.platforms.sensor.const import SensorDeviceClass, SensorStateClass
from zha.model import BaseEventedModel, BaseModel


class BatteryState(BaseModel):
    """Battery state model."""

    class_name: Literal["Battery"] = "Battery"
    state: str | float | int | None = None
    battery_size: str | None = None
    battery_quantity: int | None = None
    battery_voltage: float | None = None


class ElectricalMeasurementState(BaseModel):
    """Electrical measurement state model."""

    class_name: Literal[
        "ElectricalMeasurement",
        "ElectricalMeasurementApparentPower",
        "ElectricalMeasurementRMSCurrent",
        "ElectricalMeasurementRMSVoltage",
        "ElectricalMeasurementFrequency",
        "ElectricalMeasurementPowerFactor",
        "PolledElectricalMeasurement",
    ]
    state: str | float | int | None = None
    measurement_type: str | None = None
    active_power_max: str | None = None
    rms_current_max: str | None = None
    rms_voltage_max: int | None = None


class SmartEnergyMeteringState(BaseModel):
    """Smare energy metering state model."""

    class_name: Literal[
        "SmartEnergyMetering", "SmartEnergySummation", "SmartEnergySummationReceived"
    ]
    state: str | float | int | None = None
    device_type: str | None = None
    status: str | None = None


class DeviceCounterSensorState(BaseModel):
    """Device counter sensor state model."""

    class_name: Literal["DeviceCounterSensor"] = "DeviceCounterSensor"
    state: int


class BaseSensorEntityInfo(BasePlatformEntityInfo):
    """Sensor model."""

    attribute: str | None = None
    decimals: int
    divisor: int
    multiplier: int | float
    unit: int | str | None = None


class SensorEntityInfo(BaseSensorEntityInfo):
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
        "TimestampSensor",
        "DanfossOpenWindowDetection",
        "DanfossLoadEstimate",
        "DanfossAdaptationRunStatus",
        "DanfossPreheatTime",
        "DanfossSoftwareErrorCode",
        "DanfossMotorStepCounter",
    ]
    state: GenericState
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None


class DeviceCounterSensorEntityInfo(BaseEventedModel, BaseEntityInfo):
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


class BatteryEntityInfo(BaseSensorEntityInfo):
    """Battery entity model."""

    class_name: Literal["Battery"]
    state: BatteryState


class ElectricalMeasurementEntityInfo(BaseSensorEntityInfo):
    """Electrical measurement entity model."""

    class_name: Literal[
        "ElectricalMeasurement",
        "ElectricalMeasurementApparentPower",
        "ElectricalMeasurementRMSCurrent",
        "ElectricalMeasurementRMSVoltage",
        "ElectricalMeasurementFrequency",
        "ElectricalMeasurementPowerFactor",
        "PolledElectricalMeasurement",
    ]
    state: ElectricalMeasurementState


class SmartEnergyMeteringEntityInfo(BaseSensorEntityInfo):
    """Smare energy metering entity model."""

    class_name: Literal[
        "SmartEnergyMetering", "SmartEnergySummation", "SmartEnergySummationReceived"
    ]
    state: SmartEnergyMeteringState


class DeviceCounterEntityInfo(BaseEntityInfo):
    """Device counter entity info."""

    device_ieee: EUI64
    available: bool
    counter: str
    counter_value: int
    counter_groups: str
    counter_group: str


class DeviceCounterSensorIdentifiers(BaseIdentifiers):
    """Device counter sensor identifiers."""

    device_ieee: EUI64
