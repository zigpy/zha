"""Support for ZHA AnalogOutput cluster."""  # pylint: disable=too-many-lines

from __future__ import annotations

from enum import StrEnum
import functools
import logging
from typing import TYPE_CHECKING, Any, Self

from zigpy.quirks.v2 import EntityMetadata, NumberMetadata
from zigpy.zcl.clusters.hvac import Thermostat

from zha.application import Platform
from zha.application.const import QUIRK_METADATA
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ANALOG_OUTPUT,
    CLUSTER_HANDLER_BASIC,
    CLUSTER_HANDLER_COLOR,
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_INOVELLI,
    CLUSTER_HANDLER_LEVEL,
    CLUSTER_HANDLER_OCCUPANCY,
    CLUSTER_HANDLER_THERMOSTAT,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.NUMBER)
CONFIG_DIAGNOSTIC_MATCH = functools.partial(
    PLATFORM_ENTITIES.config_diagnostic_match, Platform.NUMBER
)


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


class UnitOfMass(StrEnum):
    """Mass units."""

    GRAMS = "g"
    KILOGRAMS = "kg"
    MILLIGRAMS = "mg"
    MICROGRAMS = "µg"
    OUNCES = "oz"
    POUNDS = "lb"
    STONES = "st"


class UnitOfTemperature(StrEnum):
    """Temperature units."""

    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_ANALOG_OUTPUT)
class ZhaNumber(PlatformEntity):
    """Representation of a ZHA Number entity."""

    PLATFORM = Platform.NUMBER
    _attr_translation_key: str = "number"

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
    ):
        """Initialize the number."""
        super().__init__(unique_id, cluster_handlers, endpoint, device)
        self._analog_output_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_ANALOG_OUTPUT
        ]
        self._analog_output_cluster_handler.on_event(
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self._analog_output_cluster_handler.present_value

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        min_present_value = self._analog_output_cluster_handler.min_present_value
        if min_present_value is not None:
            return min_present_value
        return 0

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        max_present_value = self._analog_output_cluster_handler.max_present_value
        if max_present_value is not None:
            return max_present_value
        return 1023

    @property
    def native_step(self) -> float | None:
        """Return the value step."""
        return self._analog_output_cluster_handler.resolution

    @property
    def name(self) -> str | None:
        """Return the name of the number entity."""
        description = self._analog_output_cluster_handler.description
        if description is not None and len(description) > 0:
            return f"{super().name} {description}"
        return super().name

    @property
    def icon(self) -> str | None:
        """Return the icon to be used for this entity."""
        application_type = self._analog_output_cluster_handler.application_type
        if application_type is not None:
            return ICONS.get(application_type >> 16, None)
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is expressed in."""
        engineering_units = self._analog_output_cluster_handler.engineering_units
        return UNITS.get(engineering_units)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value from HA."""
        await self._analog_output_cluster_handler.async_set_present_value(float(value))
        self.maybe_send_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve the state of the entity."""
        await super().async_update()
        _LOGGER.debug("polling current state")
        if self._analog_output_cluster_handler:
            value = await self._analog_output_cluster_handler.get_attribute_value(
                "present_value", from_cache=False
            )
            _LOGGER.debug("read value=%s", value)

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle value update from cluster handler."""
        self.maybe_send_state_changed_event()

    async def async_set_value(self, value: Any, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Update the current value from service."""
        num_value = float(value)
        if await self._analog_output_cluster_handler.async_set_present_value(num_value):
            self.maybe_send_state_changed_event()

    def to_json(self) -> dict:
        """Return the JSON representation of the number entity."""
        json = super().to_json()
        json["engineer_units"] = self._analog_output_cluster_handler.engineering_units
        json["application_type"] = self._analog_output_cluster_handler.application_type
        json["step"] = self.native_step
        json["min_value"] = self.native_min_value
        json["max_value"] = self.native_max_value
        json["name"] = self.name
        return json

    def get_state(self) -> dict:
        """Return the state of the entity."""
        response = super().get_state()
        response["state"] = self.native_value
        return response


class ZHANumberConfigurationEntity(PlatformEntity):
    """Representation of a ZHA number configuration entity."""

    PLATFORM = Platform.NUMBER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_step: float = 1.0
    _attr_multiplier: float = 1
    _attribute_name: str

    @classmethod
    def create_platform_entity(
        cls: type[Self],
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """
        cluster_handler = cluster_handlers[0]
        if QUIRK_METADATA not in kwargs and (
            cls._attribute_name in cluster_handler.cluster.unsupported_attributes
            or cls._attribute_name not in cluster_handler.cluster.attributes_by_name
            or cluster_handler.cluster.get(cls._attribute_name) is None
        ):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                cls._attribute_name,
                cls.__name__,
            )
            return None

        return cls(unique_id, cluster_handlers, endpoint, device, **kwargs)

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs: Any,
    ) -> None:
        """Init this number configuration entity."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        if QUIRK_METADATA in kwargs:
            self._init_from_quirks_metadata(kwargs[QUIRK_METADATA])
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)

    def _init_from_quirks_metadata(self, entity_metadata: EntityMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        number_metadata: NumberMetadata = entity_metadata.entity_metadata
        self._attribute_name = number_metadata.attribute_name

        if number_metadata.min is not None:
            self._attr_native_min_value = number_metadata.min
        if number_metadata.max is not None:
            self._attr_native_max_value = number_metadata.max
        if number_metadata.step is not None:
            self._attr_native_step = number_metadata.step
        if number_metadata.unit is not None:
            self._attr_native_unit_of_measurement = number_metadata.unit
        if number_metadata.multiplier is not None:
            self._attr_multiplier = number_metadata.multiplier

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return (
            self._cluster_handler.cluster.get(self._attribute_name)
            * self._attr_multiplier
        )

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value from HA."""
        await self._cluster_handler.write_attributes_safe(
            {self._attribute_name: int(value / self._attr_multiplier)}
        )
        self.maybe_send_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve the state of the entity."""
        await super().async_update()
        _LOGGER.debug("polling current state")
        if self._cluster_handler:
            value = await self._cluster_handler.get_attribute_value(
                self._attribute_name, from_cache=False
            )
            _LOGGER.debug("read value=%s", value)


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster",
    models={"lumi.motion.ac02", "lumi.motion.agl04"},
)
class AqaraMotionDetectionInterval(ZHANumberConfigurationEntity):
    """Representation of a ZHA motion detection interval configuration entity."""

    _unique_id_suffix = "detection_interval"
    _attr_native_min_value: float = 2
    _attr_native_max_value: float = 65535
    _attribute_name = "detection_interval"
    _attr_translation_key: str = "detection_interval"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEVEL)
class OnOffTransitionTimeConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA on off transition time configuration entity."""

    _unique_id_suffix = "on_off_transition_time"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFF
    _attribute_name = "on_off_transition_time"
    _attr_translation_key: str = "on_off_transition_time"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEVEL)
class OnLevelConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA on level configuration entity."""

    _unique_id_suffix = "on_level"
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFF
    _attribute_name = "on_level"
    _attr_translation_key: str = "on_level"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEVEL)
class OnTransitionTimeConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA on transition time configuration entity."""

    _unique_id_suffix = "on_transition_time"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFE
    _attribute_name = "on_transition_time"
    _attr_translation_key: str = "on_transition_time"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEVEL)
class OffTransitionTimeConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA off transition time configuration entity."""

    _unique_id_suffix = "off_transition_time"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFE
    _attribute_name = "off_transition_time"
    _attr_translation_key: str = "off_transition_time"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEVEL)
class DefaultMoveRateConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA default move rate configuration entity."""

    _unique_id_suffix = "default_move_rate"
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFE
    _attribute_name = "default_move_rate"
    _attr_translation_key: str = "default_move_rate"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEVEL)
class StartUpCurrentLevelConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA startup current level configuration entity."""

    _unique_id_suffix = "start_up_current_level"
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFF
    _attribute_name = "start_up_current_level"
    _attr_translation_key: str = "start_up_current_level"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_COLOR)
class StartUpColorTemperatureConfigurationEntity(ZHANumberConfigurationEntity):
    """Representation of a ZHA startup color temperature configuration entity."""

    _unique_id_suffix = "start_up_color_temperature"
    _attr_native_min_value: float = 153
    _attr_native_max_value: float = 500
    _attribute_name = "start_up_color_temperature"
    _attr_translation_key: str = "start_up_color_temperature"

    def __init__(
        self,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> None:
        """Init this ZHA startup color temperature entity."""
        super().__init__(unique_id, zha_device, cluster_handlers, **kwargs)
        if self._cluster_handler:
            self._attr_native_min_value: float = self._cluster_handler.min_mireds
            self._attr_native_max_value: float = self._cluster_handler.max_mireds


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="tuya_manufacturer",
    manufacturers={
        "_TZE200_htnnfasr",
    },
)
class TimerDurationMinutes(ZHANumberConfigurationEntity):
    """Representation of a ZHA timer duration configuration entity."""

    _unique_id_suffix = "timer_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[14]
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0x257
    _attr_native_unit_of_measurement: str | None = UNITS[72]
    _attribute_name = "timer_duration"
    _attr_translation_key: str = "timer_duration"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names="ikea_airpurifier")
class FilterLifeTime(ZHANumberConfigurationEntity):
    """Representation of a ZHA filter lifetime configuration entity."""

    _unique_id_suffix = "filter_life_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[14]
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFFFFFFFF
    _attr_native_unit_of_measurement: str | None = UNITS[72]
    _attribute_name = "filter_life_time"
    _attr_translation_key: str = "filter_life_time"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_BASIC,
    manufacturers={"TexasInstruments"},
    models={"ti.router"},
)
class TiRouterTransmitPower(ZHANumberConfigurationEntity):
    """Representation of a ZHA TI transmit power configuration entity."""

    _unique_id_suffix = "transmit_power"
    _attr_native_min_value: float = -20
    _attr_native_max_value: float = 20
    _attribute_name = "transmit_power"
    _attr_translation_key: str = "transmit_power"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliRemoteDimmingUpSpeed(ZHANumberConfigurationEntity):
    """Inovelli remote dimming up speed configuration entity."""

    _unique_id_suffix = "dimming_speed_up_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 126
    _attribute_name = "dimming_speed_up_remote"
    _attr_translation_key: str = "dimming_speed_up_remote"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliButtonDelay(ZHANumberConfigurationEntity):
    """Inovelli button delay configuration entity."""

    _unique_id_suffix = "button_delay"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 9
    _attribute_name = "button_delay"
    _attr_translation_key: str = "button_delay"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliLocalDimmingUpSpeed(ZHANumberConfigurationEntity):
    """Inovelli local dimming up speed configuration entity."""

    _unique_id_suffix = "dimming_speed_up_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "dimming_speed_up_local"
    _attr_translation_key: str = "dimming_speed_up_local"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliLocalRampRateOffToOn(ZHANumberConfigurationEntity):
    """Inovelli off to on local ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_off_to_on_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_off_to_on_local"
    _attr_translation_key: str = "ramp_rate_off_to_on_local"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliRemoteDimmingSpeedOffToOn(ZHANumberConfigurationEntity):
    """Inovelli off to on remote ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_off_to_on_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_off_to_on_remote"
    _attr_translation_key: str = "ramp_rate_off_to_on_remote"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliRemoteDimmingDownSpeed(ZHANumberConfigurationEntity):
    """Inovelli remote dimming down speed configuration entity."""

    _unique_id_suffix = "dimming_speed_down_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "dimming_speed_down_remote"
    _attr_translation_key: str = "dimming_speed_down_remote"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliLocalDimmingDownSpeed(ZHANumberConfigurationEntity):
    """Inovelli local dimming down speed configuration entity."""

    _unique_id_suffix = "dimming_speed_down_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "dimming_speed_down_local"
    _attr_translation_key: str = "dimming_speed_down_local"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliLocalRampRateOnToOff(ZHANumberConfigurationEntity):
    """Inovelli local on to off ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_on_to_off_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_on_to_off_local"
    _attr_translation_key: str = "ramp_rate_on_to_off_local"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliRemoteDimmingSpeedOnToOff(ZHANumberConfigurationEntity):
    """Inovelli remote on to off ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_on_to_off_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_on_to_off_remote"
    _attr_translation_key: str = "ramp_rate_on_to_off_remote"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliMinimumLoadDimmingLevel(ZHANumberConfigurationEntity):
    """Inovelli minimum load dimming level configuration entity."""

    _unique_id_suffix = "minimum_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[16]
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 254
    _attribute_name = "minimum_level"
    _attr_translation_key: str = "minimum_level"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliMaximumLoadDimmingLevel(ZHANumberConfigurationEntity):
    """Inovelli maximum load dimming level configuration entity."""

    _unique_id_suffix = "maximum_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[16]
    _attr_native_min_value: float = 2
    _attr_native_max_value: float = 255
    _attribute_name = "maximum_level"
    _attr_translation_key: str = "maximum_level"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliAutoShutoffTimer(ZHANumberConfigurationEntity):
    """Inovelli automatic switch shutoff timer configuration entity."""

    _unique_id_suffix = "auto_off_timer"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[14]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 32767
    _attribute_name = "auto_off_timer"
    _attr_translation_key: str = "auto_off_timer"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI, models={"VZM35-SN"}
)
class InovelliQuickStartTime(ZHANumberConfigurationEntity):
    """Inovelli fan quick start time configuration entity."""

    _unique_id_suffix = "quick_start_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[3]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 10
    _attribute_name = "quick_start_time"
    _attr_translation_key: str = "quick_start_time"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliLoadLevelIndicatorTimeout(ZHANumberConfigurationEntity):
    """Inovelli load level indicator timeout configuration entity."""

    _unique_id_suffix = "load_level_indicator_timeout"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[14]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 11
    _attribute_name = "load_level_indicator_timeout"
    _attr_translation_key: str = "load_level_indicator_timeout"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliDefaultAllLEDOnColor(ZHANumberConfigurationEntity):
    """Inovelli default all led color when on configuration entity."""

    _unique_id_suffix = "led_color_when_on"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[15]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "led_color_when_on"
    _attr_translation_key: str = "led_color_when_on"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliDefaultAllLEDOffColor(ZHANumberConfigurationEntity):
    """Inovelli default all led color when off configuration entity."""

    _unique_id_suffix = "led_color_when_off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[15]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "led_color_when_off"
    _attr_translation_key: str = "led_color_when_off"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliDefaultAllLEDOnIntensity(ZHANumberConfigurationEntity):
    """Inovelli default all led intensity when on configuration entity."""

    _unique_id_suffix = "led_intensity_when_on"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[16]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 100
    _attribute_name = "led_intensity_when_on"
    _attr_translation_key: str = "led_intensity_when_on"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliDefaultAllLEDOffIntensity(ZHANumberConfigurationEntity):
    """Inovelli default all led intensity when off configuration entity."""

    _unique_id_suffix = "led_intensity_when_off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[16]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 100
    _attribute_name = "led_intensity_when_off"
    _attr_translation_key: str = "led_intensity_when_off"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliDoubleTapUpLevel(ZHANumberConfigurationEntity):
    """Inovelli double tap up level configuration entity."""

    _unique_id_suffix = "double_tap_up_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[16]
    _attr_native_min_value: float = 2
    _attr_native_max_value: float = 254
    _attribute_name = "double_tap_up_level"
    _attr_translation_key: str = "double_tap_up_level"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_INOVELLI)
class InovelliDoubleTapDownLevel(ZHANumberConfigurationEntity):
    """Inovelli double tap down level configuration entity."""

    _unique_id_suffix = "double_tap_down_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon: str = ICONS[16]
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 254
    _attribute_name = "double_tap_down_level"
    _attr_translation_key: str = "double_tap_down_level"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"}
)
class AqaraPetFeederServingSize(ZHANumberConfigurationEntity):
    """Aqara pet feeder serving size configuration entity."""

    _unique_id_suffix = "serving_size"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 10
    _attribute_name = "serving_size"
    _attr_translation_key: str = "serving_size"

    _attr_mode: NumberMode = NumberMode.BOX
    _attr_icon: str = "mdi:counter"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"}
)
class AqaraPetFeederPortionWeight(ZHANumberConfigurationEntity):
    """Aqara pet feeder portion weight configuration entity."""

    _unique_id_suffix = "portion_weight"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 100
    _attribute_name = "portion_weight"
    _attr_translation_key: str = "portion_weight"

    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_unit_of_measurement: str = UnitOfMass.GRAMS
    _attr_icon: str = "mdi:weight-gram"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"}
)
class AqaraThermostatAwayTemp(ZHANumberConfigurationEntity):
    """Aqara away preset temperature configuration entity."""

    _unique_id_suffix = "away_preset_temperature"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 5
    _attr_native_max_value: float = 30
    _attr_multiplier: float = 0.01
    _attribute_name = "away_preset_temperature"
    _attr_translation_key: str = "away_preset_temperature"

    _attr_mode: NumberMode = NumberMode.SLIDER
    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS
    _attr_icon: str = ICONS[0]


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class ThermostatLocalTempCalibration(ZHANumberConfigurationEntity):
    """Local temperature calibration."""

    _unique_id_suffix = "local_temperature_calibration"
    _attr_native_min_value: float = -2.5
    _attr_native_max_value: float = 2.5
    _attr_native_step: float = 0.1
    _attr_multiplier: float = 0.1
    _attribute_name = "local_temperature_calibration"
    _attr_translation_key: str = "local_temperature_calibration"

    _attr_mode: NumberMode = NumberMode.SLIDER
    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS
    _attr_icon: str = ICONS[0]


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    models={"TRVZB"},
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class SonoffThermostatLocalTempCalibration(ThermostatLocalTempCalibration):
    """Local temperature calibration for the Sonoff TRVZB."""

    _attr_native_min_value: float = -7
    _attr_native_max_value: float = 7
    _attr_native_step: float = 0.2


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_OCCUPANCY, models={"SNZB-06P"}
)
class SonoffPresenceSenorTimeout(ZHANumberConfigurationEntity):
    """Configuration of Sonoff sensor presence detection timeout."""

    _unique_id_suffix = "presence_detection_timeout"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: int = 15
    _attr_native_max_value: int = 60
    _attribute_name = "ultrasonic_o_to_u_delay"
    _attr_translation_key: str = "presence_detection_timeout"

    _attr_mode: NumberMode = NumberMode.BOX
    _attr_icon: str = "mdi:timer-edit"


class ZCLTemperatureEntity(ZHANumberConfigurationEntity):
    """Common entity class for ZCL temperature input."""

    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS
    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_step: float = 0.01
    _attr_multiplier: float = 0.01


class ZCLHeatSetpointLimitEntity(ZCLTemperatureEntity):
    """Min or max heat setpoint setting on thermostats."""

    _attr_icon: str = "mdi:thermostat"
    _attr_native_step: float = 0.5

    _min_source = Thermostat.AttributeDefs.abs_min_heat_setpoint_limit.name
    _max_source = Thermostat.AttributeDefs.abs_max_heat_setpoint_limit.name

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        # The spec says 0x954D, which is a signed integer, therefore the value is in decimals
        min_present_value = self._cluster_handler.cluster.get(self._min_source, -27315)
        return min_present_value * self._attr_multiplier

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        max_present_value = self._cluster_handler.cluster.get(self._max_source, 0x7FFF)
        return max_present_value * self._attr_multiplier


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT)
class MaxHeatSetpointLimit(ZCLHeatSetpointLimitEntity):
    """Max heat setpoint setting on thermostats.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "max_heat_setpoint_limit"
    _attribute_name: str = "max_heat_setpoint_limit"
    _attr_translation_key: str = "max_heat_setpoint_limit"
    _attr_entity_category = EntityCategory.CONFIG

    _min_source = Thermostat.AttributeDefs.min_heat_setpoint_limit.name


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT)
class MinHeatSetpointLimit(ZCLHeatSetpointLimitEntity):
    """Min heat setpoint setting on thermostats.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "min_heat_setpoint_limit"
    _attribute_name: str = "min_heat_setpoint_limit"
    _attr_translation_key: str = "min_heat_setpoint_limit"
    _attr_entity_category = EntityCategory.CONFIG

    _max_source = Thermostat.AttributeDefs.max_heat_setpoint_limit.name
