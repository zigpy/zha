"""Constants for the sensor platform."""

from datetime import UTC, datetime

from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
from zigpy.zcl.clusters.general_const import AnalogInputType

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
