"""Constants for the Number platform."""

from enum import StrEnum

UNITS = {
    0: "Square-meters",
    1: "Square-feet",
    2: "Milliamperes",
    3: "Amperes",
    4: "Ohms",
    5: "Volts",
    6: "Kilo-volts",
    7: "Mega-volts",
    8: "Volt-amperes",
    9: "Kilo-volt-amperes",
    10: "Mega-volt-amperes",
    11: "Volt-amperes-reactive",
    12: "Kilo-volt-amperes-reactive",
    13: "Mega-volt-amperes-reactive",
    14: "Degrees-phase",
    15: "Power-factor",
    16: "Joules",
    17: "Kilojoules",
    18: "Watt-hours",
    19: "Kilowatt-hours",
    20: "BTUs",
    21: "Therms",
    22: "Ton-hours",
    23: "Joules-per-kilogram-dry-air",
    24: "BTUs-per-pound-dry-air",
    25: "Cycles-per-hour",
    26: "Cycles-per-minute",
    27: "Hertz",
    28: "Grams-of-water-per-kilogram-dry-air",
    29: "Percent-relative-humidity",
    30: "Millimeters",
    31: "Meters",
    32: "Inches",
    33: "Feet",
    34: "Watts-per-square-foot",
    35: "Watts-per-square-meter",
    36: "Lumens",
    37: "Luxes",
    38: "Foot-candles",
    39: "Kilograms",
    40: "Pounds-mass",
    41: "Tons",
    42: "Kilograms-per-second",
    43: "Kilograms-per-minute",
    44: "Kilograms-per-hour",
    45: "Pounds-mass-per-minute",
    46: "Pounds-mass-per-hour",
    47: "Watts",
    48: "Kilowatts",
    49: "Megawatts",
    50: "BTUs-per-hour",
    51: "Horsepower",
    52: "Tons-refrigeration",
    53: "Pascals",
    54: "Kilopascals",
    55: "Bars",
    56: "Pounds-force-per-square-inch",
    57: "Centimeters-of-water",
    58: "Inches-of-water",
    59: "Millimeters-of-mercury",
    60: "Centimeters-of-mercury",
    61: "Inches-of-mercury",
    62: "°C",
    63: "°K",
    64: "°F",
    65: "Degree-days-Celsius",
    66: "Degree-days-Fahrenheit",
    67: "Years",
    68: "Months",
    69: "Weeks",
    70: "Days",
    71: "Hours",
    72: "Minutes",
    73: "Seconds",
    74: "Meters-per-second",
    75: "Kilometers-per-hour",
    76: "Feet-per-second",
    77: "Feet-per-minute",
    78: "Miles-per-hour",
    79: "Cubic-feet",
    80: "Cubic-meters",
    81: "Imperial-gallons",
    82: "Liters",
    83: "Us-gallons",
    84: "Cubic-feet-per-minute",
    85: "Cubic-meters-per-second",
    86: "Imperial-gallons-per-minute",
    87: "Liters-per-second",
    88: "Liters-per-minute",
    89: "Us-gallons-per-minute",
    90: "Degrees-angular",
    91: "Degrees-Celsius-per-hour",
    92: "Degrees-Celsius-per-minute",
    93: "Degrees-Fahrenheit-per-hour",
    94: "Degrees-Fahrenheit-per-minute",
    95: None,
    96: "Parts-per-million",
    97: "Parts-per-billion",
    98: "%",
    99: "Percent-per-second",
    100: "Per-minute",
    101: "Per-second",
    102: "Psi-per-Degree-Fahrenheit",
    103: "Radians",
    104: "Revolutions-per-minute",
    105: "Currency1",
    106: "Currency2",
    107: "Currency3",
    108: "Currency4",
    109: "Currency5",
    110: "Currency6",
    111: "Currency7",
    112: "Currency8",
    113: "Currency9",
    114: "Currency10",
    115: "Square-inches",
    116: "Square-centimeters",
    117: "BTUs-per-pound",
    118: "Centimeters",
    119: "Pounds-mass-per-second",
    120: "Delta-Degrees-Fahrenheit",
    121: "Delta-Degrees-Kelvin",
    122: "Kilohms",
    123: "Megohms",
    124: "Millivolts",
    125: "Kilojoules-per-kilogram",
    126: "Megajoules",
    127: "Joules-per-degree-Kelvin",
    128: "Joules-per-kilogram-degree-Kelvin",
    129: "Kilohertz",
    130: "Megahertz",
    131: "Per-hour",
    132: "Milliwatts",
    133: "Hectopascals",
    134: "Millibars",
    135: "Cubic-meters-per-hour",
    136: "Liters-per-hour",
    137: "Kilowatt-hours-per-square-meter",
    138: "Kilowatt-hours-per-square-foot",
    139: "Megajoules-per-square-meter",
    140: "Megajoules-per-square-foot",
    141: "Watts-per-square-meter-Degree-Kelvin",
    142: "Cubic-feet-per-second",
    143: "Percent-obscuration-per-foot",
    144: "Percent-obscuration-per-meter",
    145: "Milliohms",
    146: "Megawatt-hours",
    147: "Kilo-BTUs",
    148: "Mega-BTUs",
    149: "Kilojoules-per-kilogram-dry-air",
    150: "Megajoules-per-kilogram-dry-air",
    151: "Kilojoules-per-degree-Kelvin",
    152: "Megajoules-per-degree-Kelvin",
    153: "Newton",
    154: "Grams-per-second",
    155: "Grams-per-minute",
    156: "Tons-per-hour",
    157: "Kilo-BTUs-per-hour",
    158: "Hundredths-seconds",
    159: "Milliseconds",
    160: "Newton-meters",
    161: "Millimeters-per-second",
    162: "Millimeters-per-minute",
    163: "Meters-per-minute",
    164: "Meters-per-hour",
    165: "Cubic-meters-per-minute",
    166: "Meters-per-second-per-second",
    167: "Amperes-per-meter",
    168: "Amperes-per-square-meter",
    169: "Ampere-square-meters",
    170: "Farads",
    171: "Henrys",
    172: "Ohm-meters",
    173: "Siemens",
    174: "Siemens-per-meter",
    175: "Teslas",
    176: "Volts-per-degree-Kelvin",
    177: "Volts-per-meter",
    178: "Webers",
    179: "Candelas",
    180: "Candelas-per-square-meter",
    181: "Kelvins-per-hour",
    182: "Kelvins-per-minute",
    183: "Joule-seconds",
    185: "Square-meters-per-Newton",
    186: "Kilogram-per-cubic-meter",
    187: "Newton-seconds",
    188: "Newtons-per-meter",
    189: "Watts-per-meter-per-degree-Kelvin",
}

ICONS = {
    0: "mdi:temperature-celsius",
    1: "mdi:water-percent",
    2: "mdi:gauge",
    3: "mdi:speedometer",
    4: "mdi:percent",
    5: "mdi:air-filter",
    6: "mdi:fan",
    7: "mdi:flash",
    8: "mdi:current-ac",
    9: "mdi:flash",
    10: "mdi:flash",
    11: "mdi:flash",
    12: "mdi:counter",
    13: "mdi:thermometer-lines",
    14: "mdi:timer",
    15: "mdi:palette",
    16: "mdi:brightness-percent",
}


class NumberMode(StrEnum):
    """Modes for number entities."""

    AUTO = "auto"
    BOX = "box"
    SLIDER = "slider"


class NumberDeviceClass(StrEnum):
    """Device class for numbers."""

    # NumberDeviceClass should be aligned with SensorDeviceClass

    APPARENT_POWER = "apparent_power"
    """Apparent power.

    Unit of measurement: `VA`
    """

    AQI = "aqi"
    """Air Quality Index.

    Unit of measurement: `None`
    """

    ATMOSPHERIC_PRESSURE = "atmospheric_pressure"
    """Atmospheric pressure.

    Unit of measurement: `UnitOfPressure` units
    """

    BATTERY = "battery"
    """Percentage of battery that is left.

    Unit of measurement: `%`
    """

    CO = "carbon_monoxide"
    """Carbon Monoxide gas concentration.

    Unit of measurement: `ppm` (parts per million)
    """

    CO2 = "carbon_dioxide"
    """Carbon Dioxide gas concentration.

    Unit of measurement: `ppm` (parts per million)
    """

    CURRENT = "current"
    """Current.

    Unit of measurement: `A`,  `mA`
    """

    DATA_RATE = "data_rate"
    """Data rate.

    Unit of measurement: UnitOfDataRate
    """

    DATA_SIZE = "data_size"
    """Data size.

    Unit of measurement: UnitOfInformation
    """

    DISTANCE = "distance"
    """Generic distance.

    Unit of measurement: `LENGTH_*` units
    - SI /metric: `mm`, `cm`, `m`, `km`
    - USCS / imperial: `in`, `ft`, `yd`, `mi`
    """

    DURATION = "duration"
    """Fixed duration.

    Unit of measurement: `d`, `h`, `min`, `s`, `ms`
    """

    ENERGY = "energy"
    """Energy.

    Unit of measurement: `Wh`, `kWh`, `MWh`, `MJ`, `GJ`
    """

    ENERGY_STORAGE = "energy_storage"
    """Stored energy.

    Use this device class for sensors measuring stored energy, for example the amount
    of electric energy currently stored in a battery or the capacity of a battery.

    Unit of measurement: `Wh`, `kWh`, `MWh`, `MJ`, `GJ`
    """

    FREQUENCY = "frequency"
    """Frequency.

    Unit of measurement: `Hz`, `kHz`, `MHz`, `GHz`
    """

    GAS = "gas"
    """Gas.

    Unit of measurement:
    - SI / metric: `m³`
    - USCS / imperial: `ft³`, `CCF`
    """

    HUMIDITY = "humidity"
    """Relative humidity.

    Unit of measurement: `%`
    """

    ILLUMINANCE = "illuminance"
    """Illuminance.

    Unit of measurement: `lx`
    """

    IRRADIANCE = "irradiance"
    """Irradiance.

    Unit of measurement:
    - SI / metric: `W/m²`
    - USCS / imperial: `BTU/(h⋅ft²)`
    """

    MOISTURE = "moisture"
    """Moisture.

    Unit of measurement: `%`
    """

    MONETARY = "monetary"
    """Amount of money.

    Unit of measurement: ISO4217 currency code

    See https://en.wikipedia.org/wiki/ISO_4217#Active_codes for active codes
    """

    NITROGEN_DIOXIDE = "nitrogen_dioxide"
    """Amount of NO2.

    Unit of measurement: `µg/m³`
    """

    NITROGEN_MONOXIDE = "nitrogen_monoxide"
    """Amount of NO.

    Unit of measurement: `µg/m³`
    """

    NITROUS_OXIDE = "nitrous_oxide"
    """Amount of N2O.

    Unit of measurement: `µg/m³`
    """

    OZONE = "ozone"
    """Amount of O3.

    Unit of measurement: `µg/m³`
    """

    PH = "ph"
    """Potential hydrogen (acidity/alkalinity).

    Unit of measurement: Unitless
    """

    PM1 = "pm1"
    """Particulate matter <= 1 μm.

    Unit of measurement: `µg/m³`
    """

    PM10 = "pm10"
    """Particulate matter <= 10 μm.

    Unit of measurement: `µg/m³`
    """

    PM25 = "pm25"
    """Particulate matter <= 2.5 μm.

    Unit of measurement: `µg/m³`
    """

    POWER_FACTOR = "power_factor"
    """Power factor.

    Unit of measurement: `%`, `None`
    """

    POWER = "power"
    """Power.

    Unit of measurement: `W`, `kW`
    """

    PRECIPITATION = "precipitation"
    """Accumulated precipitation.

    Unit of measurement: UnitOfPrecipitationDepth
    - SI / metric: `cm`, `mm`
    - USCS / imperial: `in`
    """

    PRECIPITATION_INTENSITY = "precipitation_intensity"
    """Precipitation intensity.

    Unit of measurement: UnitOfVolumetricFlux
    - SI /metric: `mm/d`, `mm/h`
    - USCS / imperial: `in/d`, `in/h`
    """

    PRESSURE = "pressure"
    """Pressure.

    Unit of measurement:
    - `mbar`, `cbar`, `bar`
    - `Pa`, `hPa`, `kPa`
    - `inHg`
    - `psi`
    """

    REACTIVE_POWER = "reactive_power"
    """Reactive power.

    Unit of measurement: `var`
    """

    SIGNAL_STRENGTH = "signal_strength"
    """Signal strength.

    Unit of measurement: `dB`, `dBm`
    """

    SOUND_PRESSURE = "sound_pressure"
    """Sound pressure.

    Unit of measurement: `dB`, `dBA`
    """

    SPEED = "speed"
    """Generic speed.

    Unit of measurement: `SPEED_*` units or `UnitOfVolumetricFlux`
    - SI /metric: `mm/d`, `mm/h`, `m/s`, `km/h`
    - USCS / imperial: `in/d`, `in/h`, `ft/s`, `mph`
    - Nautical: `kn`
    """

    SULPHUR_DIOXIDE = "sulphur_dioxide"
    """Amount of SO2.

    Unit of measurement: `µg/m³`
    """

    TEMPERATURE = "temperature"
    """Temperature.

    Unit of measurement: `°C`, `°F`, `K`
    """

    VOLATILE_ORGANIC_COMPOUNDS = "volatile_organic_compounds"
    """Amount of VOC.

    Unit of measurement: `µg/m³`
    """

    VOLATILE_ORGANIC_COMPOUNDS_PARTS = "volatile_organic_compounds_parts"
    """Ratio of VOC.

    Unit of measurement: `ppm`, `ppb`
    """

    VOLTAGE = "voltage"
    """Voltage.

    Unit of measurement: `V`, `mV`
    """

    VOLUME = "volume"
    """Generic volume.

    Unit of measurement: `VOLUME_*` units
    - SI / metric: `mL`, `L`, `m³`
    - USCS / imperial: `ft³`, `CCF`, `fl. oz.`, `gal` (warning: volumes expressed in
    USCS/imperial units are currently assumed to be US volumes)
    """

    VOLUME_STORAGE = "volume_storage"
    """Generic stored volume.

    Use this device class for sensors measuring stored volume, for example the amount
    of fuel in a fuel tank.

    Unit of measurement: `VOLUME_*` units
    - SI / metric: `mL`, `L`, `m³`
    - USCS / imperial: `ft³`, `CCF`, `fl. oz.`, `gal` (warning: volumes expressed in
    USCS/imperial units are currently assumed to be US volumes)
    """

    VOLUME_FLOW_RATE = "volume_flow_rate"
    """Generic flow rate

    Unit of measurement: UnitOfVolumeFlowRate
    - SI / metric: `m³/h`, `L/min`
    - USCS / imperial: `ft³/min`, `gal/min`
    """

    WATER = "water"
    """Water.

    Unit of measurement:
    - SI / metric: `m³`, `L`
    - USCS / imperial: `ft³`, `CCF`, `gal` (warning: volumes expressed in
    USCS/imperial units are currently assumed to be US volumes)
    """

    WEIGHT = "weight"
    """Generic weight, represents a measurement of an object's mass.

    Weight is used instead of mass to fit with every day language.

    Unit of measurement: `MASS_*` units
    - SI / metric: `µg`, `mg`, `g`, `kg`
    - USCS / imperial: `oz`, `lb`
    """

    WIND_SPEED = "wind_speed"
    """Wind speed.

    Unit of measurement: `SPEED_*` units
    - SI /metric: `m/s`, `km/h`
    - USCS / imperial: `ft/s`, `mph`
    - Nautical: `kn`
    """
