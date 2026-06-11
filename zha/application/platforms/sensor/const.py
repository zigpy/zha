"""Constants for the sensor platform."""

from datetime import UTC, datetime
import enum

from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
from zigpy.zcl.clusters.general_const import AnalogInputType
from zigpy.zcl.clusters.homeautomation import MeasurementType
from zigpy.zcl.clusters.smartenergy import MeteringDeviceType

from zha.units import (
    CONCENTRATION_PARTS_PER_MILLION,
    COUNT,
    KILOJOULES_PER_KG,
    PERCENTAGE,
    REVOLUTIONS_PER_MINUTE,
    UnitOfElectricCurrent,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)

# Re-exported from zigpy for use throughout ZHA
__all__ = [
    "SensorDeviceClass",
    "SensorStateClass",
]

NON_NUMERIC_DEVICE_CLASSES = {
    SensorDeviceClass.DATE,
    SensorDeviceClass.ENUM,
    SensorDeviceClass.TIMESTAMP,
}

ANALOG_INPUT_APPTYPE_DEV_CLASS = {
    AnalogInputType.Temp_Degrees_C: SensorDeviceClass.TEMPERATURE,
    AnalogInputType.Relative_Humidity_Percent: SensorDeviceClass.HUMIDITY,
    AnalogInputType.Pressure_Pascal: SensorDeviceClass.PRESSURE,
    AnalogInputType.Flow_Liters_Per_Sec: SensorDeviceClass.VOLUME_FLOW_RATE,
    AnalogInputType.Percentage: None,
    AnalogInputType.Parts_Per_Million: None,  # It can be one of many
    AnalogInputType.Rotational_Speed_RPM: None,  # No device class for RPM
    AnalogInputType.Current_Amps: SensorDeviceClass.CURRENT,
    AnalogInputType.Frequency_Hz: SensorDeviceClass.FREQUENCY,
    AnalogInputType.Power_Watts: SensorDeviceClass.POWER,
    AnalogInputType.Power_Kilo_Watts: SensorDeviceClass.POWER,
    AnalogInputType.Energy_Kilo_Watt_Hours: SensorDeviceClass.ENERGY,
    AnalogInputType.Count: None,
    AnalogInputType.Enthalpy_KJoules_Per_Kg: None,
    AnalogInputType.Time_Seconds: SensorDeviceClass.DURATION,
}

ANALOG_INPUT_APPTYPE_UNITS = {
    AnalogInputType.Temp_Degrees_C: UnitOfTemperature.CELSIUS,
    AnalogInputType.Relative_Humidity_Percent: PERCENTAGE,
    AnalogInputType.Pressure_Pascal: UnitOfPressure.PA,
    AnalogInputType.Flow_Liters_Per_Sec: "L/s",
    AnalogInputType.Percentage: PERCENTAGE,
    AnalogInputType.Parts_Per_Million: CONCENTRATION_PARTS_PER_MILLION,
    AnalogInputType.Rotational_Speed_RPM: REVOLUTIONS_PER_MINUTE,
    AnalogInputType.Current_Amps: UnitOfElectricCurrent.AMPERE,
    AnalogInputType.Frequency_Hz: UnitOfFrequency.HERTZ,
    AnalogInputType.Power_Watts: UnitOfPower.WATT,
    AnalogInputType.Power_Kilo_Watts: UnitOfPower.KILO_WATT,
    AnalogInputType.Energy_Kilo_Watt_Hours: UnitOfEnergy.KILO_WATT_HOUR,
    AnalogInputType.Count: COUNT,
    AnalogInputType.Enthalpy_KJoules_Per_Kg: KILOJOULES_PER_KG,
    AnalogInputType.Time_Seconds: UnitOfTime.SECONDS,
}

ZCL_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)

# Remapping of `MeasurementType` members to legacy names, for extra state attributes.
# TODO: deprecate this.
LEGACY_MEASUREMENT_TYPE_REMAPPING = {
    MeasurementType.Active_measurement_AC: "ACTIVE_MEASUREMENT",
    MeasurementType.Reactive_measurement_AC: "REACTIVE_MEASUREMENT",
    MeasurementType.Apparent_measurement_AC: "APPARENT_MEASUREMENT",
    MeasurementType.Phase_A_measurement: "PHASE_A_MEASUREMENT",
    MeasurementType.Phase_B_measurement: "PHASE_B_MEASUREMENT",
    MeasurementType.Phase_C_measurement: "PHASE_C_MEASUREMENT",
    MeasurementType.DC_measurement: "DC_MEASUREMENT",
    MeasurementType.Harmonics_measurement: "HARMONICS_MEASUREMENT",
    MeasurementType.Power_quality_measurement: "POWER_QUALITY_MEASUREMENT",
}

# SmartEnergy Metering device-type categorization. zigpy's `MeteringDeviceType`
# defines the values; ZHA groups them by physical metering type to pick the
# right device-status flag interpretation below.
METERING_DEVICE_TYPES_ELECTRIC: frozenset[int] = frozenset(
    {
        MeteringDeviceType.Electric_Metering,
        MeteringDeviceType.EUMD_for_metering_electric_vehicle_charging,
        MeteringDeviceType.PV_Generation_Metering,
        MeteringDeviceType.Wind_Turbine_Generation_Metering,
        MeteringDeviceType.Water_Turbine_Generation_Metering,
        MeteringDeviceType.Micro_Generation_Metering,
        MeteringDeviceType.Electric_Metering_Element_Phase_1,
        MeteringDeviceType.Electric_Metering_Element_Phase_2,
        MeteringDeviceType.Electric_Metering_Element_Phase_3,
        MeteringDeviceType.Mirrored_Electric_Metering,
        MeteringDeviceType.Mirrored_EUMD_for_metering_electric_vehicle_charging,
        MeteringDeviceType.Mirrored_PV_Generation_Metering,
        MeteringDeviceType.Mirrored_Wind_Turbine_Generation_Metering,
        MeteringDeviceType.Mirrored_Water_Turbine_Generation_Metering,
        MeteringDeviceType.Mirrored_Micro_Generation_Metering,
        MeteringDeviceType.Mirrored_Electric_Metering_Element_Phase_1,
        MeteringDeviceType.Mirrored_Electric_Metering_Element_Phase_2,
        MeteringDeviceType.Mirrored_Electric_Metering_Element_Phase_3,
    }
)
METERING_DEVICE_TYPES_GAS: frozenset[int] = frozenset(
    {MeteringDeviceType.Gas_Metering, MeteringDeviceType.Mirrored_Gas_Metering}
)
METERING_DEVICE_TYPES_WATER: frozenset[int] = frozenset(
    {MeteringDeviceType.Water_Metering, MeteringDeviceType.Mirrored_Water_Metering}
)
METERING_DEVICE_TYPES_HEATING_COOLING: frozenset[int] = frozenset(
    {
        MeteringDeviceType.Thermal_Metering,
        MeteringDeviceType.Heat_Metering,
        MeteringDeviceType.Cooling_Metering,
        MeteringDeviceType.Mirrored_Thermal_Metering,
        MeteringDeviceType.Mirrored_Heat_Metering,
        MeteringDeviceType.Mirrored_Cooling_Metering,
    }
)


def metering_device_type_name(dev_type: int) -> str | int:
    """Return a human-readable label for a `MeteringDeviceType` value."""
    member = MeteringDeviceType._value2member_map_.get(dev_type)
    return member.name.replace("_", " ") if member is not None else dev_type


# Per-metering-type interpretations of the `status` attribute. The ZCL spec
# reuses the same 8 status bits with different meanings depending on
# `metering_device_type`; zigpy's `MeteringStatus` covers only the Electric
# variant, so the rest are defined here.
class DeviceStatusElectric(enum.IntFlag):
    """Electric Metering Device Status."""

    NO_ALARMS = 0
    CHECK_METER = 1
    LOW_BATTERY = 2
    TAMPER_DETECT = 4
    POWER_FAILURE = 8
    POWER_QUALITY = 16
    LEAK_DETECT = 32  # Really?
    SERVICE_DISCONNECT = 64
    RESERVED = 128


class DeviceStatusGas(enum.IntFlag):
    """Gas Metering Device Status."""

    NO_ALARMS = 0
    CHECK_METER = 1
    LOW_BATTERY = 2
    TAMPER_DETECT = 4
    NOT_DEFINED = 8
    LOW_PRESSURE = 16
    LEAK_DETECT = 32
    SERVICE_DISCONNECT = 64
    REVERSE_FLOW = 128


class DeviceStatusWater(enum.IntFlag):
    """Water Metering Device Status."""

    NO_ALARMS = 0
    CHECK_METER = 1
    LOW_BATTERY = 2
    TAMPER_DETECT = 4
    PIPE_EMPTY = 8
    LOW_PRESSURE = 16
    LEAK_DETECT = 32
    SERVICE_DISCONNECT = 64
    REVERSE_FLOW = 128


class DeviceStatusHeatingCooling(enum.IntFlag):
    """Heating and Cooling Metering Device Status."""

    NO_ALARMS = 0
    CHECK_METER = 1
    LOW_BATTERY = 2
    TAMPER_DETECT = 4
    TEMPERATURE_SENSOR = 8
    BURST_DETECT = 16
    LEAK_DETECT = 32
    SERVICE_DISCONNECT = 64
    REVERSE_FLOW = 128


class DeviceStatusDefault(enum.IntFlag):
    """Metering Device Status."""

    NO_ALARMS = 0
