"""Constants for the climate platform."""

from enum import IntFlag, StrEnum
from typing import Final

from zigpy.zcl.clusters.hvac import ControlSequenceOfOperation, RunningMode, SystemMode

ATTR_SYS_MODE: Final[str] = "system_mode"
ATTR_FAN_MODE: Final[str] = "fan_mode"
ATTR_RUNNING_MODE: Final[str] = "running_mode"
ATTR_SETPT_CHANGE_SRC: Final[str] = "setpoint_change_source"
ATTR_SETPT_CHANGE_AMT: Final[str] = "setpoint_change_amount"
ATTR_OCCUPANCY: Final[str] = "occupancy"
ATTR_PI_COOLING_DEMAND: Final[str] = "pi_cooling_demand"
ATTR_PI_HEATING_DEMAND: Final[str] = "pi_heating_demand"
ATTR_OCCP_COOL_SETPT: Final[str] = "occupied_cooling_setpoint"
ATTR_OCCP_HEAT_SETPT: Final[str] = "occupied_heating_setpoint"
ATTR_UNOCCP_HEAT_SETPT: Final[str] = "unoccupied_heating_setpoint"
ATTR_UNOCCP_COOL_SETPT: Final[str] = "unoccupied_cooling_setpoint"
ATTR_HVAC_MODE: Final[str] = "hvac_mode"
ATTR_TARGET_TEMP_HIGH: Final[str] = "target_temp_high"
ATTR_TARGET_TEMP_LOW: Final[str] = "target_temp_low"
ATTR_TEMPERATURE: Final[str] = "temperature"

PRECISION_TENTHS: Final[float] = 0.1

# Possible fan state
FAN_ON = "on"
FAN_OFF = "off"
FAN_AUTO = "auto"
FAN_LOW = "low"
FAN_MEDIUM = "medium"
FAN_HIGH = "high"
FAN_TOP = "top"
FAN_MIDDLE = "middle"
FAN_FOCUS = "focus"
FAN_DIFFUSE = "diffuse"

# Possible swing state
SWING_ON = "on"
SWING_OFF = "off"
SWING_BOTH = "both"
SWING_VERTICAL = "vertical"
SWING_HORIZONTAL = "horizontal"


class ClimateEntityFeature(IntFlag):
    """Supported features of the climate entity."""

    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    TARGET_HUMIDITY = 4
    FAN_MODE = 8
    PRESET_MODE = 16
    SWING_MODE = 32
    AUX_HEAT = 64
    TURN_OFF = 128
    TURN_ON = 256


class HVACMode(StrEnum):
    """HVAC mode."""

    OFF = "off"
    # Heating
    HEAT = "heat"
    # Cooling
    COOL = "cool"
    # The device supports heating/cooling to a range
    HEAT_COOL = "heat_cool"
    # The temperature is set based on a schedule, learned behavior, AI or some
    # other related mechanism. User is not able to adjust the temperature
    AUTO = "auto"
    # Device is in Dry/Humidity mode
    DRY = "dry"
    # Only the fan is on, not fan and another mode like cool
    FAN_ONLY = "fan_only"


class Preset(StrEnum):
    """Preset mode."""

    # No preset is active
    NONE = "none"
    # Device is running an energy-saving mode
    ECO = "eco"
    # Device is in away mode
    AWAY = "away"
    # Device turn all valve full up
    BOOST = "boost"
    # Device is in comfort mode
    COMFORT = "comfort"
    # Device is in home mode
    HOME = "home"
    # Device is prepared for sleep
    SLEEP = "sleep"
    # Device is reacting to activity (e.g. movement sensors)
    ACTIVITY = "activity"
    SCHEDULE = "Schedule"
    COMPLEX = "Complex"
    TEMP_MANUAL = "Temporary manual"


class FanState(StrEnum):
    """Fan state."""

    # Possible fan state
    ON = "on"
    OFF = "off"
    AUTO = "auto"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TOP = "top"
    MIDDLE = "middle"
    FOCUS = "focus"
    DIFFUSE = "diffuse"


class CurrentHVAC(StrEnum):
    """Current HVAC state."""

    OFF = "off"
    HEAT = "heating"
    COOL = "cooling"
    DRY = "drying"
    IDLE = "idle"
    FAN = "fan"


class HVACAction(StrEnum):
    """HVAC action for climate devices."""

    COOLING = "cooling"
    DEFROSTING = "defrosting"
    DRYING = "drying"
    FAN = "fan"
    HEATING = "heating"
    IDLE = "idle"
    OFF = "off"
    PREHEATING = "preheating"


RUNNING_MODE = {
    RunningMode.Off: HVACMode.OFF,
    RunningMode.Cool: HVACMode.COOL,
    RunningMode.Heat: HVACMode.HEAT,
}

SEQ_OF_OPERATION = {
    ControlSequenceOfOperation.Cooling_Only: [HVACMode.OFF, HVACMode.COOL],
    ControlSequenceOfOperation.Cooling_With_Reheat: [HVACMode.OFF, HVACMode.COOL],
    ControlSequenceOfOperation.Heating_Only: [HVACMode.OFF, HVACMode.HEAT],
    ControlSequenceOfOperation.Heating_With_Reheat: [HVACMode.OFF, HVACMode.HEAT],
    ControlSequenceOfOperation.Cooling_and_Heating: [
        HVACMode.OFF,
        HVACMode.HEAT_COOL,
        HVACMode.COOL,
        HVACMode.HEAT,
    ],
    ControlSequenceOfOperation.Cooling_and_Heating_with_Reheat: [
        HVACMode.OFF,
        HVACMode.HEAT_COOL,
        HVACMode.COOL,
        HVACMode.HEAT,
    ],
    0x06: [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],  # centralite specific
    0x07: [HVACMode.HEAT_COOL, HVACMode.OFF],  # centralite specific
}

HVAC_MODE_2_SYSTEM = {
    HVACMode.OFF: SystemMode.Off,
    HVACMode.HEAT_COOL: SystemMode.Auto,
    HVACMode.COOL: SystemMode.Cool,
    HVACMode.HEAT: SystemMode.Heat,
    HVACMode.FAN_ONLY: SystemMode.Fan_only,
    HVACMode.DRY: SystemMode.Dry,
}

SYSTEM_MODE_2_HVAC = {
    SystemMode.Off: HVACMode.OFF,
    SystemMode.Auto: HVACMode.HEAT_COOL,
    SystemMode.Cool: HVACMode.COOL,
    SystemMode.Heat: HVACMode.HEAT,
    SystemMode.Emergency_Heating: HVACMode.HEAT,
    SystemMode.Pre_cooling: HVACMode.COOL,  # this is 'precooling'. is it the same?
    SystemMode.Fan_only: HVACMode.FAN_ONLY,
    SystemMode.Dry: HVACMode.DRY,
    SystemMode.Sleep: HVACMode.OFF,
}

ZCL_TEMP = 100
