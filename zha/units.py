"""Units of measure for Zigbee Home Automation."""

from enum import Enum, StrEnum
from typing import Final


class UnitOfTemperature(StrEnum):
    """Temperature units."""

    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class UnitOfMass(StrEnum):
    """Mass units."""

    GRAMS = "g"
    KILOGRAMS = "kg"
    MILLIGRAMS = "mg"
    MICROGRAMS = "µg"
    OUNCES = "oz"
    POUNDS = "lb"
    STONES = "st"


class UnitOfPressure(StrEnum):
    """Pressure units."""

    PA = "Pa"
    HPA = "hPa"
    KPA = "kPa"
    BAR = "bar"
    CBAR = "cbar"
    MBAR = "mbar"
    MMHG = "mmHg"
    INHG = "inHg"
    PSI = "psi"


class UnitOfPower(StrEnum):
    """Power units."""

    WATT = "W"
    KILO_WATT = "kW"
    BTU_PER_HOUR = "BTU/h"


class UnitOfApparentPower(StrEnum):
    """Apparent power units."""

    VOLT_AMPERE = "VA"


class UnitOfElectricCurrent(StrEnum):
    """Electric current units."""

    MILLIAMPERE = "mA"
    AMPERE = "A"


# Electric_potential units
class UnitOfElectricPotential(StrEnum):
    """Electric potential units."""

    MILLIVOLT = "mV"
    VOLT = "V"


class UnitOfFrequency(StrEnum):
    """Frequency units."""

    HERTZ = "Hz"
    KILOHERTZ = "kHz"
    MEGAHERTZ = "MHz"
    GIGAHERTZ = "GHz"


class UnitOfVolumeFlowRate(StrEnum):
    """Volume flow rate units."""

    CUBIC_METERS_PER_HOUR = "m³/h"
    CUBIC_FEET_PER_MINUTE = "ft³/min"
    LITERS_PER_MINUTE = "L/min"
    GALLONS_PER_MINUTE = "gal/min"


class UnitOfVolume(StrEnum):
    """Volume units."""

    CUBIC_FEET = "ft³"
    CENTUM_CUBIC_FEET = "CCF"
    CUBIC_METERS = "m³"
    LITERS = "L"
    MILLILITERS = "mL"
    GALLONS = "gal"
    """Assumed to be US gallons in conversion utilities.

    British/Imperial gallons are not yet supported"""
    FLUID_OUNCES = "fl. oz."
    """Assumed to be US fluid ounces in conversion utilities.

    British/Imperial fluid ounces are not yet supported"""


class UnitOfTime(StrEnum):
    """Time units."""

    MICROSECONDS = "μs"
    MILLISECONDS = "ms"
    SECONDS = "s"
    MINUTES = "min"
    HOURS = "h"
    DAYS = "d"
    WEEKS = "w"
    MONTHS = "m"
    YEARS = "y"


class UnitOfEnergy(StrEnum):
    """Energy units."""

    GIGA_JOULE = "GJ"
    KILO_WATT_HOUR = "kWh"
    MEGA_JOULE = "MJ"
    MEGA_WATT_HOUR = "MWh"
    WATT_HOUR = "Wh"


# Concentration units
CONCENTRATION_MICROGRAMS_PER_CUBIC_METER: Final = "µg/m³"
CONCENTRATION_MILLIGRAMS_PER_CUBIC_METER: Final = "mg/m³"
CONCENTRATION_MICROGRAMS_PER_CUBIC_FOOT: Final = "μg/ft³"
CONCENTRATION_PARTS_PER_CUBIC_METER: Final = "p/m³"
CONCENTRATION_PARTS_PER_MILLION: Final = "ppm"
CONCENTRATION_PARTS_PER_BILLION: Final = "ppb"

# Signal_strength units
SIGNAL_STRENGTH_DECIBELS: Final = "dB"
SIGNAL_STRENGTH_DECIBELS_MILLIWATT: Final = "dBm"

# Light units
LIGHT_LUX: Final = "lx"

# Percentage units
PERCENTAGE: Final[str] = "%"


UNITS_OF_MEASURE = {
    UnitOfApparentPower.__name__: UnitOfApparentPower,
    UnitOfPower.__name__: UnitOfPower,
    UnitOfEnergy.__name__: UnitOfEnergy,
    UnitOfElectricCurrent.__name__: UnitOfElectricCurrent,
    UnitOfElectricPotential.__name__: UnitOfElectricPotential,
    UnitOfTemperature.__name__: UnitOfTemperature,
    UnitOfTime.__name__: UnitOfTime,
    UnitOfFrequency.__name__: UnitOfFrequency,
    UnitOfPressure.__name__: UnitOfPressure,
    UnitOfVolume.__name__: UnitOfVolume,
    UnitOfVolumeFlowRate.__name__: UnitOfVolumeFlowRate,
    UnitOfMass.__name__: UnitOfMass,
}


def validate_unit(external_unit: Enum) -> Enum:
    """Validate and return a unit of measure."""
    return UNITS_OF_MEASURE[type(external_unit).__name__](external_unit.value)
