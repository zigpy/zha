"""Sensors on Zigbee Home Automation networks."""  # pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import enum
import functools
import logging
import numbers
from typing import TYPE_CHECKING, Any, Final, Self

from zigpy import types
from zigpy.quirks.v2 import EntityMetadata, ZCLEnumMetadata, ZCLSensorMetadata
from zigpy.state import Counter, State
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.clusters.general import Basic

from zha.application import Platform
from zha.application.const import DATA_ZHA, QUIRK_METADATA
from zha.application.platforms import BaseEntity, EntityCategory, PlatformEntity
from zha.application.platforms.climate import HVACAction
from zha.application.registries import PLATFORM_ENTITIES
from zha.decorators import periodic
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ANALOG_INPUT,
    CLUSTER_HANDLER_BASIC,
    CLUSTER_HANDLER_COVER,
    CLUSTER_HANDLER_DEVICE_TEMPERATURE,
    CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT,
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_HUMIDITY,
    CLUSTER_HANDLER_ILLUMINANCE,
    CLUSTER_HANDLER_LEAF_WETNESS,
    CLUSTER_HANDLER_POWER_CONFIGURATION,
    CLUSTER_HANDLER_PRESSURE,
    CLUSTER_HANDLER_SMARTENERGY_METERING,
    CLUSTER_HANDLER_SOIL_MOISTURE,
    CLUSTER_HANDLER_TEMPERATURE,
    CLUSTER_HANDLER_THERMOSTAT,
    SMARTTHINGS_HUMIDITY_CLUSTER,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint

BATTERY_SIZES = {
    0: "No battery",
    1: "Built in",
    2: "Other",
    3: "AA",
    4: "AAA",
    5: "C",
    6: "D",
    7: "CR2",
    8: "CR123A",
    9: "CR2450",
    10: "CR2032",
    11: "CR1632",
    255: "Unknown",
}

_LOGGER = logging.getLogger(__name__)

CLUSTER_HANDLER_ST_HUMIDITY_CLUSTER = (
    f"cluster_handler_0x{SMARTTHINGS_HUMIDITY_CLUSTER:04x}"
)
STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.SENSOR)
MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.SENSOR)
CONFIG_DIAGNOSTIC_MATCH = functools.partial(
    PLATFORM_ENTITIES.config_diagnostic_match, Platform.SENSOR
)


class SensorStateClass(enum.StrEnum):
    """State class for sensors."""

    MEASUREMENT = "measurement"
    """The state represents a measurement in present time."""

    TOTAL = "total"
    """The state represents a total amount.

    For example: net energy consumption"""

    TOTAL_INCREASING = "total_increasing"
    """The state represents a monotonically increasing total.

    For example: an amount of consumed gas"""


class SensorDeviceClass(enum.StrEnum):
    """Device class for sensors."""

    # Non-numerical device classes
    DATE = "date"
    """Date.

    Unit of measurement: `None`

    ISO8601 format: https://en.wikipedia.org/wiki/ISO_8601
    """

    ENUM = "enum"
    """Enumeration.

    Provides a fixed list of options the state of the sensor can be in.

    Unit of measurement: `None`
    """

    TIMESTAMP = "timestamp"
    """Timestamp.

    Unit of measurement: `None`

    ISO8601 format: https://en.wikipedia.org/wiki/ISO_8601
    """

    # Numerical device classes, these should be aligned with NumberDeviceClass
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

    Unit of measurement: `A`, `mA`
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

    Use this device class for sensors measuring energy consumption, for example
    electric energy consumption.
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
    - Beaufort: `Beaufort`
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
    - Beaufort: `Beaufort`
    """


NON_NUMERIC_DEVICE_CLASSES = {
    SensorDeviceClass.DATE,
    SensorDeviceClass.ENUM,
    SensorDeviceClass.TIMESTAMP,
}

# Percentage units
PERCENTAGE: Final[str] = "%"


class UnitOfTemperature(enum.StrEnum):
    """Temperature units."""

    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class UnitOfPressure(enum.StrEnum):
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


class UnitOfPower(enum.StrEnum):
    """Power units."""

    WATT = "W"
    KILO_WATT = "kW"
    BTU_PER_HOUR = "BTU/h"


class UnitOfApparentPower(enum.StrEnum):
    """Apparent power units."""

    VOLT_AMPERE = "VA"


class UnitOfElectricCurrent(enum.StrEnum):
    """Electric current units."""

    MILLIAMPERE = "mA"
    AMPERE = "A"


# Electric_potential units
class UnitOfElectricPotential(enum.StrEnum):
    """Electric potential units."""

    MILLIVOLT = "mV"
    VOLT = "V"


class UnitOfFrequency(enum.StrEnum):
    """Frequency units."""

    HERTZ = "Hz"
    KILOHERTZ = "kHz"
    MEGAHERTZ = "MHz"
    GIGAHERTZ = "GHz"


class UnitOfVolumeFlowRate(enum.StrEnum):
    """Volume flow rate units."""

    CUBIC_METERS_PER_HOUR = "m³/h"
    CUBIC_FEET_PER_MINUTE = "ft³/min"
    LITERS_PER_MINUTE = "L/min"
    GALLONS_PER_MINUTE = "gal/min"


class UnitOfVolume(enum.StrEnum):
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


class UnitOfTime(enum.StrEnum):
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


class UnitOfEnergy(enum.StrEnum):
    """Energy units."""

    GIGA_JOULE = "GJ"
    KILO_WATT_HOUR = "kWh"
    MEGA_JOULE = "MJ"
    MEGA_WATT_HOUR = "MWh"
    WATT_HOUR = "Wh"


class UnitOfMass(enum.StrEnum):
    """Mass units."""

    GRAMS = "g"
    KILOGRAMS = "kg"
    MILLIGRAMS = "mg"
    MICROGRAMS = "µg"
    OUNCES = "oz"
    POUNDS = "lb"
    STONES = "st"


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


class Sensor(PlatformEntity):
    """Base ZHA sensor."""

    PLATFORM = Platform.SENSOR
    _attribute_name: int | str | None = None
    _decimals: int = 1
    _divisor: int = 1
    _multiplier: int | float = 1
    _attr_native_unit_of_measurement: str | None = None
    _attr_device_class: SensorDeviceClass | None = None
    _attr_state_class: SensorStateClass | None = None

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """
        cluster_handler = cluster_handlers[0]
        if QUIRK_METADATA not in kwargs and (
            cls._attribute_name in cluster_handler.cluster.unsupported_attributes
            or cls._attribute_name not in cluster_handler.cluster.attributes_by_name
        ):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                cls._attribute_name,
                cls.__name__,
            )
            return None

        return cls(unique_id, zha_device, cluster_handlers, **kwargs)

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        if QUIRK_METADATA in kwargs:
            self._init_from_quirks_metadata(kwargs[QUIRK_METADATA])
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._cluster_handler.on_event(
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )

    def _init_from_quirks_metadata(self, entity_metadata: EntityMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        sensor_metadata: ZCLSensorMetadata = entity_metadata.entity_metadata
        self._attribute_name = sensor_metadata.attribute_name
        if sensor_metadata.divisor is not None:
            self._divisor = sensor_metadata.divisor
        if sensor_metadata.multiplier is not None:
            self._multiplier = sensor_metadata.multiplier
        if sensor_metadata.unit is not None:
            self._attr_native_unit_of_measurement = sensor_metadata.unit

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the entity."""
        assert self._attribute_name is not None
        raw_state = self._cluster_handler.cluster.get(self._attribute_name)
        if raw_state is None:
            return None
        return self.formatter(raw_state)

    def get_state(self) -> dict:
        """Return the state for this sensor."""
        assert self._attribute_name is not None
        raw_state = self._cluster_handler.cluster.get(self._attribute_name)
        if raw_state is None:
            return None
        response = super().get_state()
        raw_state = self.formatter(raw_state)
        response["state"] = raw_state
        return response

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle attribute updates from the cluster handler."""
        self.maybe_send_state_changed_event()

    def to_json(self) -> dict:
        """Return a JSON representation of the sensor."""
        json = super().to_json()
        json["attribute"] = self._attribute_name
        json["decimals"] = self._decimals
        json["divisor"] = self._divisor
        json["multiplier"] = self._multiplier
        json["unit"] = self._attr_native_unit_of_measurement
        json["device_class"] = self._attr_device_class
        json["state_class"] = self._attr_state_class
        return json

    def formatter(self, value: int | enum.IntEnum) -> int | float | str | None:
        """Numeric pass-through formatter."""
        if self._decimals > 0:
            return round(
                float(value * self._multiplier) / self._divisor, self._decimals
            )
        return round(float(value * self._multiplier) / self._divisor)


class PollableSensor(Sensor):
    """Base ZHA sensor that polls for state."""

    _REFRESH_INTERVAL = (30, 45)
    _use_custom_polling: bool = True

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._cancel_refresh_handle: Callable | None = None
        if self.should_poll:
            self._tracked_tasks.append(
                asyncio.create_task(
                    self._refresh(),
                    name=f"sensor_state_poller_{self.unique_id}_{self.__class__.__name__}",
                )
            )

    @property
    def should_poll(self) -> bool:
        """Return True if we need to poll for state changes."""
        return self._use_custom_polling

    @periodic(_REFRESH_INTERVAL)
    async def _refresh(self):
        """Call async_update at a constrained random interval."""
        if self.device.available and self.device.gateway.data[DATA_ZHA].allow_polling:
            self.debug("polling for updated state")
            await self.async_update()
            self.maybe_send_state_changed_event()
        else:
            self.debug(
                "skipping polling for updated state, available: %s, allow polled requests: %s",
                self.device.available,
                self.device.gateway.data[DATA_ZHA].allow_polling,
            )


class DeviceCounterSensor(BaseEntity):
    """Device counter sensor."""

    _REFRESH_INTERVAL = (30, 45)
    _use_custom_polling: bool = True
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        counter_groups: str,
        counter_group: str,
        counter: str,
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """
        return cls(
            unique_id, zha_device, counter_groups, counter_group, counter, **kwargs
        )

    def __init__(
        self,
        unique_id: str,
        zha_device: ZHADevice,
        counter_groups: str,
        counter_group: str,
        counter: str,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        super().__init__(unique_id, **kwargs)
        self._device: ZHADevice = zha_device
        state: State = self._device.gateway.application_controller.state
        self._zigpy_counter: Counter = (
            getattr(state, counter_groups).get(counter_group, {}).get(counter, None)
        )
        self._attr_name: str = self._zigpy_counter.name
        self._tracked_tasks.append(
            asyncio.create_task(
                self._refresh(),
                name=f"sensor_state_poller_{self.unique_id}_{self.__class__.__name__}",
            )
        )

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self._device.available

    async def async_update(self) -> None:
        """Retrieve latest state."""
        self.maybe_send_state_changed_event()

    @periodic(_REFRESH_INTERVAL)
    async def _refresh(self):
        """Call async_update at a constrained random interval."""
        if self._device.available and self._device.gateway.data[DATA_ZHA].allow_polling:
            self.debug("polling for updated state")
            await self.async_update()
            self.maybe_send_state_changed_event()
        else:
            self.debug(
                "skipping polling for updated state, available: %s, allow polled requests: %s",
                self._device.available,
                self._device.gateway.data[DATA_ZHA].allow_polling,
            )

    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""
        return {
            "unique_id": self.unique_id,
            "platform": self.PLATFORM,
            "device_ieee": self._device.ieee,
        }

    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this platform entity."""
        signal["platform_entity"] = {
            "name": self._attr_name,
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
        }
        _LOGGER.info("Sending event from device counter sensor entity: %s", signal)
        self._device.send_event(signal)

    def to_json(self) -> dict:
        """Return a JSON representation of the platform entity."""
        json = super().to_json()
        json["name"] = self._attr_name
        json["device_ieee"] = str(self._device.ieee)
        json["counter"] = self._zigpy_counter.name
        json["counter_value"] = self._zigpy_counter.value
        return json


class EnumSensor(Sensor):
    """Sensor with value from enum."""

    _attr_device_class: SensorDeviceClass = SensorDeviceClass.ENUM
    _enum: type[enum.Enum]

    def _init_from_quirks_metadata(self, entity_metadata: EntityMetadata) -> None:
        """Init this entity from the quirks metadata."""
        PlatformEntity._init_from_quirks_metadata(self, entity_metadata)  # pylint: disable=protected-access
        sensor_metadata: ZCLEnumMetadata = entity_metadata.entity_metadata
        self._attribute_name = sensor_metadata.attribute_name
        self._enum = sensor_metadata.enum

    def formatter(self, value: int) -> str | None:
        """Use name of enum."""
        assert self._enum is not None
        return self._enum(value).name


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ANALOG_INPUT,
    manufacturers="Digi",
    stop_on_match_group=CLUSTER_HANDLER_ANALOG_INPUT,
)
class AnalogInput(Sensor):
    """Sensor that displays analog input values."""

    _attribute_name = "present_value"
    _attr_translation_key: str = "analog_input"


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_POWER_CONFIGURATION)
class Battery(Sensor):
    """Battery sensor of power configuration cluster."""

    _attribute_name = "battery_percentage_remaining"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.BATTERY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Unlike any other entity, PowerConfiguration cluster may not support
        battery_percent_remaining attribute, but zha-device-handlers takes care of it
        so create the entity regardless
        """
        if zha_device.is_mains_powered:
            return None
        return cls(unique_id, zha_device, cluster_handlers, **kwargs)

    @staticmethod
    def formatter(value: int) -> int | None:  # pylint: disable=arguments-differ
        """Return the state of the entity."""
        # per zcl specs battery percent is reported at 200% ¯\_(ツ)_/¯
        if not isinstance(value, numbers.Number) or value == -1 or value == 255:
            return None
        value = round(value / 2)
        return value

    def get_state(self) -> dict[str, Any]:
        """Return the state for battery sensors."""
        response = super().get_state()
        battery_size = self._cluster_handler.cluster.get("battery_size")
        if battery_size is not None:
            response["battery_size"] = BATTERY_SIZES.get(battery_size, "Unknown")
        battery_quantity = self._cluster_handler.cluster.get("battery_quantity")
        if battery_quantity is not None:
            response["battery_quantity"] = battery_quantity
        battery_voltage = self._cluster_handler.cluster.get("battery_voltage")
        if battery_voltage is not None:
            response["battery_voltage"] = round(battery_voltage / 10, 2)
        return response


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT,
    stop_on_match_group=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT,
    models={"VZM31-SN", "SP 234", "outletv4"},
)
class ElectricalMeasurement(PollableSensor):
    """Active power measurement."""

    _use_custom_polling: bool = False
    _attribute_name = "active_power"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement: str = UnitOfPower.WATT
    _div_mul_prefix: str | None = "ac_power"

    def get_state(self) -> dict[str, Any]:
        """Return the state for this sensor."""
        response = super().get_state()
        if self._cluster_handler.measurement_type is not None:
            response["measurement_type"] = self._cluster_handler.measurement_type

        max_attr_name = f"{self._attribute_name}_max"
        if (max_v := self._cluster_handler.cluster.get(max_attr_name)) is not None:
            response[max_attr_name] = str(self.formatter(max_v))

        return response

    def formatter(self, value: int) -> int | float:
        """Return 'normalized' value."""
        if self._div_mul_prefix:
            multiplier = getattr(
                self._cluster_handler, f"{self._div_mul_prefix}_multiplier"
            )
            divisor = getattr(self._cluster_handler, f"{self._div_mul_prefix}_divisor")
        else:
            multiplier = self._multiplier
            divisor = self._divisor
        value = float(value * multiplier) / divisor
        if value < 100 and divisor > 1:
            return round(value, self._decimals)
        return round(value)


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT,
    stop_on_match_group=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT,
)
class PolledElectricalMeasurement(ElectricalMeasurement):
    """Polled active power measurement."""

    _use_custom_polling: bool = True


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT)
class ElectricalMeasurementApparentPower(PolledElectricalMeasurement):
    """Apparent power measurement."""

    _attribute_name = "apparent_power"
    _unique_id_suffix = "apparent_power"
    _use_custom_polling = False  # Poll indirectly by ElectricalMeasurementSensor
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.APPARENT_POWER
    _attr_native_unit_of_measurement = UnitOfApparentPower.VOLT_AMPERE
    _div_mul_prefix = "ac_power"


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT)
class ElectricalMeasurementRMSCurrent(PolledElectricalMeasurement):
    """RMS current measurement."""

    _attribute_name = "rms_current"
    _unique_id_suffix = "rms_current"
    _use_custom_polling = False  # Poll indirectly by ElectricalMeasurementSensor
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _div_mul_prefix = "ac_current"


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT)
class ElectricalMeasurementRMSVoltage(PolledElectricalMeasurement):
    """RMS Voltage measurement."""

    _attribute_name = "rms_voltage"
    _unique_id_suffix = "rms_voltage"
    _use_custom_polling = False  # Poll indirectly by ElectricalMeasurementSensor
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _div_mul_prefix = "ac_voltage"


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT)
class ElectricalMeasurementFrequency(PolledElectricalMeasurement):
    """Frequency measurement."""

    _attribute_name = "ac_frequency"
    _unique_id_suffix = "ac_frequency"
    _use_custom_polling = False  # Poll indirectly by ElectricalMeasurementSensor
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.FREQUENCY
    _attr_translation_key: str = "ac_frequency"
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _div_mul_prefix = "ac_frequency"


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT)
class ElectricalMeasurementPowerFactor(PolledElectricalMeasurement):
    """Power Factor measurement."""

    _attribute_name = "power_factor"
    _unique_id_suffix = "power_factor"
    _use_custom_polling = False  # Poll indirectly by ElectricalMeasurementSensor
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER_FACTOR
    _attr_native_unit_of_measurement = PERCENTAGE
    _div_mul_prefix = None


@MULTI_MATCH(
    generic_ids=CLUSTER_HANDLER_ST_HUMIDITY_CLUSTER,
    stop_on_match_group=CLUSTER_HANDLER_HUMIDITY,
)
@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_HUMIDITY,
    stop_on_match_group=CLUSTER_HANDLER_HUMIDITY,
)
class Humidity(Sensor):
    """Humidity sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.HUMIDITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_SOIL_MOISTURE)
class SoilMoisture(Sensor):
    """Soil Moisture sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.HUMIDITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "soil_moisture"
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_LEAF_WETNESS)
class LeafWetness(Sensor):
    """Leaf Wetness sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.HUMIDITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "leaf_wetness"
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ILLUMINANCE)
class Illuminance(Sensor):
    """Illuminance Sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.ILLUMINANCE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX

    def formatter(self, value: int) -> int | None:
        """Convert illumination data."""
        if value == 0:
            return 0
        if value == 0xFFFF:
            return None
        return round(pow(10, ((value - 1) / 10000)))


@dataclass(frozen=True, kw_only=True)
class SmartEnergyMeteringEntityDescription:
    """Dataclass that describes a Zigbee smart energy metering entity."""

    key: str = "instantaneous_demand"
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    scale: int = 1
    native_unit_of_measurement: str | None = None
    device_class: SensorDeviceClass | None = None


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    stop_on_match_group=CLUSTER_HANDLER_SMARTENERGY_METERING,
)
class SmartEnergyMetering(PollableSensor):
    """Metering sensor."""

    entity_description: SmartEnergyMeteringEntityDescription
    _use_custom_polling: bool = False
    _attribute_name = "instantaneous_demand"
    _attr_translation_key: str = "instantaneous_demand"

    _ENTITY_DESCRIPTION_MAP = {
        0x00: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfPower.WATT,
            device_class=SensorDeviceClass.POWER,
        ),
        0x01: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
            device_class=None,  # volume flow rate is not supported yet
        ),
        0x02: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_FEET_PER_MINUTE,
            device_class=None,  # volume flow rate is not supported yet
        ),
        0x03: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
            device_class=None,  # volume flow rate is not supported yet
            scale=100,
        ),
        0x04: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=f"{UnitOfVolume.GALLONS}/{UnitOfTime.HOURS}",  # US gallons per hour
            device_class=None,  # volume flow rate is not supported yet
        ),
        0x05: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=f"IMP {UnitOfVolume.GALLONS}/{UnitOfTime.HOURS}",  # IMP gallons per hour
            device_class=None,  # needs to be None as imperial gallons are not supported
        ),
        0x06: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfPower.BTU_PER_HOUR,
            device_class=None,
            state_class=None,
        ),
        0x07: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=f"l/{UnitOfTime.HOURS}",
            device_class=None,  # volume flow rate is not supported yet
        ),
        0x08: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfPressure.KPA,
            device_class=SensorDeviceClass.PRESSURE,
        ),  # gauge
        0x09: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=UnitOfPressure.KPA,
            device_class=SensorDeviceClass.PRESSURE,
        ),  # absolute
        0x0A: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=f"{UnitOfVolume.CUBIC_FEET}/{UnitOfTime.HOURS}",  # cubic feet per hour
            device_class=None,  # volume flow rate is not supported yet
            scale=1000,
        ),
        0x0B: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement="unitless", device_class=None, state_class=None
        ),
        0x0C: SmartEnergyMeteringEntityDescription(
            native_unit_of_measurement=f"{UnitOfEnergy.MEGA_JOULE}/{UnitOfTime.SECONDS}",
            device_class=None,  # needs to be None as MJ/s is not supported
        ),
    }

    def __init__(
        self,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> None:
        """Init."""
        super().__init__(unique_id, zha_device, cluster_handlers, **kwargs)

        entity_description = self._ENTITY_DESCRIPTION_MAP.get(
            self._cluster_handler.unit_of_measurement
        )
        if entity_description is not None:
            self.entity_description = entity_description

    def formatter(self, value: int) -> int | float:
        """Pass through cluster handler formatter."""
        return self._cluster_handler.demand_formatter(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return device state attrs for battery sensors."""
        attrs = {}
        if self._cluster_handler.device_type is not None:
            attrs["device_type"] = self._cluster_handler.device_type
        if (status := self._cluster_handler.metering_status) is not None:
            if isinstance(status, enum.IntFlag):
                attrs["status"] = str(
                    status.name if status.name is not None else status.value
                )
            else:
                attrs["status"] = str(status)[len(status.__class__.__name__) + 1 :]
        return attrs

    def get_state(self) -> dict[str, Any]:
        """Return state for this sensor."""
        response = super().get_state()
        if self._cluster_handler.device_type is not None:
            response["device_type"] = self._cluster_handler.device_type
        if (status := self._cluster_handler.metering_status) is not None:
            if isinstance(status, enum.IntFlag):
                response["status"] = str(
                    status.name if status.name is not None else status.value
                )
            else:
                response["status"] = str(status)[len(status.__class__.__name__) + 1 :]
        return response

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the entity."""
        state = super().native_value
        if hasattr(self, "entity_description") and state is not None:
            return float(state) * self.entity_description.scale

        return state


@dataclass(frozen=True, kw_only=True)
class SmartEnergySummationEntityDescription(SmartEnergyMeteringEntityDescription):
    """Dataclass that describes a Zigbee smart energy summation entity."""

    key: str = "summation_delivered"
    state_class: SensorStateClass | None = SensorStateClass.TOTAL_INCREASING


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    stop_on_match_group=CLUSTER_HANDLER_SMARTENERGY_METERING,
)
class SmartEnergySummation(SmartEnergyMetering):
    """Smart Energy Metering summation sensor."""

    entity_description: SmartEnergySummationEntityDescription
    _attribute_name = "current_summ_delivered"
    _unique_id_suffix = "summation_delivered"
    _attr_translation_key: str = "summation_delivered"

    _ENTITY_DESCRIPTION_MAP = {
        0x00: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            device_class=SensorDeviceClass.ENERGY,
        ),
        0x01: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            device_class=SensorDeviceClass.VOLUME,
        ),
        0x02: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfVolume.CUBIC_FEET,
            device_class=SensorDeviceClass.VOLUME,
        ),
        0x03: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfVolume.CUBIC_FEET,
            device_class=SensorDeviceClass.VOLUME,
            scale=100,
        ),
        0x04: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfVolume.GALLONS,  # US gallons
            device_class=SensorDeviceClass.VOLUME,
        ),
        0x05: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=f"IMP {UnitOfVolume.GALLONS}",
            device_class=None,  # needs to be None as imperial gallons are not supported
        ),
        0x06: SmartEnergySummationEntityDescription(
            native_unit_of_measurement="BTU", device_class=None, state_class=None
        ),
        0x07: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfVolume.LITERS,
            device_class=SensorDeviceClass.VOLUME,
        ),
        0x08: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfPressure.KPA,
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
        ),  # gauge
        0x09: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfPressure.KPA,
            device_class=SensorDeviceClass.PRESSURE,
            state_class=SensorStateClass.MEASUREMENT,
        ),  # absolute
        0x0A: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfVolume.CUBIC_FEET,
            device_class=SensorDeviceClass.VOLUME,
            scale=1000,
        ),
        0x0B: SmartEnergySummationEntityDescription(
            native_unit_of_measurement="unitless", device_class=None, state_class=None
        ),
        0x0C: SmartEnergySummationEntityDescription(
            native_unit_of_measurement=UnitOfEnergy.MEGA_JOULE,
            device_class=SensorDeviceClass.ENERGY,
        ),
    }

    def formatter(self, value: int) -> int | float:
        """Numeric pass-through formatter."""
        if self._cluster_handler.unit_of_measurement != 0:
            return self._cluster_handler.summa_formatter(value)

        cooked = (
            float(self._cluster_handler.multiplier * value)
            / self._cluster_handler.divisor
        )
        return round(cooked, 3)


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"TS011F", "ZLinky_TIC", "TICMeter"},
    stop_on_match_group=CLUSTER_HANDLER_SMARTENERGY_METERING,
)
class PolledSmartEnergySummation(SmartEnergySummation):
    """Polled Smart Energy Metering summation sensor."""

    _use_custom_polling: bool = True


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"ZLinky_TIC", "TICMeter"},
)
class Tier1SmartEnergySummation(PolledSmartEnergySummation):
    """Tier 1 Smart Energy Metering summation sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_tier1_summ_delivered"
    _unique_id_suffix = "tier1_summation_delivered"
    _attr_translation_key: str = "tier1_summation_delivered"


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"ZLinky_TIC", "TICMeter"},
)
class Tier2SmartEnergySummation(PolledSmartEnergySummation):
    """Tier 2 Smart Energy Metering summation sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_tier2_summ_delivered"
    _unique_id_suffix = "tier2_summation_delivered"
    _attr_translation_key: str = "tier2_summation_delivered"


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"ZLinky_TIC", "TICMeter"},
)
class Tier3SmartEnergySummation(PolledSmartEnergySummation):
    """Tier 3 Smart Energy Metering summation sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_tier3_summ_delivered"
    _unique_id_suffix = "tier3_summation_delivered"
    _attr_translation_key: str = "tier3_summation_delivered"


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"ZLinky_TIC", "TICMeter"},
)
class Tier4SmartEnergySummation(PolledSmartEnergySummation):
    """Tier 4 Smart Energy Metering summation sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_tier4_summ_delivered"
    _unique_id_suffix = "tier4_summation_delivered"
    _attr_translation_key: str = "tier4_summation_delivered"


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"ZLinky_TIC", "TICMeter"},
)
class Tier5SmartEnergySummation(PolledSmartEnergySummation):
    """Tier 5 Smart Energy Metering summation sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_tier5_summ_delivered"
    _unique_id_suffix = "tier5_summation_delivered"
    _attr_translation_key: str = "tier5_summation_delivered"


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
    models={"ZLinky_TIC", "TICMeter"},
)
class Tier6SmartEnergySummation(PolledSmartEnergySummation):
    """Tier 6 Smart Energy Metering summation sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_tier6_summ_delivered"
    _unique_id_suffix = "tier6_summation_delivered"
    _attr_translation_key: str = "tier6_summation_delivered"


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_SMARTENERGY_METERING,
)
class SmartEnergySummationReceived(PolledSmartEnergySummation):
    """Smart Energy Metering summation received sensor."""

    _use_custom_polling = False  # Poll indirectly by PolledSmartEnergySummation
    _attribute_name = "current_summ_received"
    _unique_id_suffix = "summation_received"
    _attr_translation_key: str = "summation_received"

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        This attribute only started to be initialized in HA 2024.2.0,
        so the entity would be created on the first HA start after the
        upgrade for existing devices, as the initialization to see if
        an attribute is unsupported happens later in the background.
        To avoid creating unnecessary entities for existing devices,
        wait until the attribute was properly initialized once for now.
        """
        if cluster_handlers[0].cluster.get(cls._attribute_name) is None:
            return None
        return super().create_entity(unique_id, zha_device, cluster_handlers, **kwargs)


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_PRESSURE)
class Pressure(Sensor):
    """Pressure sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.PRESSURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _decimals = 0
    _attr_native_unit_of_measurement = UnitOfPressure.HPA


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_TEMPERATURE)
class Temperature(Sensor):
    """Temperature Sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.TEMPERATURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 100
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_DEVICE_TEMPERATURE)
class DeviceTemperature(Sensor):
    """Device Temperature Sensor."""

    _attribute_name = "current_temperature"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.TEMPERATURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "device_temperature"
    _divisor = 100
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC


@MULTI_MATCH(cluster_handler_names="carbon_dioxide_concentration")
class CarbonDioxideConcentration(Sensor):
    """Carbon Dioxide Concentration sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CO2
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _decimals = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION


@MULTI_MATCH(cluster_handler_names="carbon_monoxide_concentration")
class CarbonMonoxideConcentration(Sensor):
    """Carbon Monoxide Concentration sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CO
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _decimals = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION


@MULTI_MATCH(generic_ids="cluster_handler_0x042e", stop_on_match_group="voc_level")
@MULTI_MATCH(cluster_handler_names="voc_level", stop_on_match_group="voc_level")
class VOCLevel(Sensor):
    """VOC Level sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _decimals = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER


@MULTI_MATCH(
    cluster_handler_names="voc_level",
    models="lumi.airmonitor.acn01",
    stop_on_match_group="voc_level",
)
class PPBVOCLevel(Sensor):
    """VOC Level sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = (
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS
    )
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _decimals = 0
    _multiplier = 1
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_BILLION


@MULTI_MATCH(cluster_handler_names="pm25")
class PM25(Sensor):
    """Particulate Matter 2.5 microns or less sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.PM25
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _decimals = 0
    _multiplier = 1
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER


@MULTI_MATCH(cluster_handler_names="formaldehyde_concentration")
class FormaldehydeConcentration(Sensor):
    """Formaldehyde Concentration sensor."""

    _attribute_name = "measured_value"
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "formaldehyde"
    _decimals = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class ThermostatHVACAction(Sensor):
    """Thermostat HVAC action sensor."""

    _unique_id_suffix = "hvac_action"
    _attr_translation_key: str = "hvac_action"

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """

        return cls(unique_id, zha_device, cluster_handlers, **kwargs)

    @property
    def native_value(self) -> str | None:
        """Return the current HVAC action."""
        if (
            self._cluster_handler.pi_heating_demand is None
            and self._cluster_handler.pi_cooling_demand is None
        ):
            return self._rm_rs_action
        return self._pi_demand_action

    @property
    def _rm_rs_action(self) -> HVACAction | None:
        """Return the current HVAC action based on running mode and running state."""

        if (running_state := self._cluster_handler.running_state) is None:
            return None

        rs_heat = (
            self._cluster_handler.RunningState.Heat_State_On
            | self._cluster_handler.RunningState.Heat_2nd_Stage_On
        )
        if running_state & rs_heat:
            return HVACAction.HEATING

        rs_cool = (
            self._cluster_handler.RunningState.Cool_State_On
            | self._cluster_handler.RunningState.Cool_2nd_Stage_On
        )
        if running_state & rs_cool:
            return HVACAction.COOLING

        running_state = self._cluster_handler.running_state
        if running_state and running_state & (
            self._cluster_handler.RunningState.Fan_State_On
            | self._cluster_handler.RunningState.Fan_2nd_Stage_On
            | self._cluster_handler.RunningState.Fan_3rd_Stage_On
        ):
            return HVACAction.FAN

        running_state = self._cluster_handler.running_state
        if running_state and running_state & self._cluster_handler.RunningState.Idle:
            return HVACAction.IDLE

        if self._cluster_handler.system_mode != self._cluster_handler.SystemMode.Off:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def _pi_demand_action(self) -> HVACAction:
        """Return the current HVAC action based on pi_demands."""

        heating_demand = self._cluster_handler.pi_heating_demand
        if heating_demand is not None and heating_demand > 0:
            return HVACAction.HEATING
        cooling_demand = self._cluster_handler.pi_cooling_demand
        if cooling_demand is not None and cooling_demand > 0:
            return HVACAction.COOLING

        if self._cluster_handler.system_mode != self._cluster_handler.SystemMode.Off:
            return HVACAction.IDLE
        return HVACAction.OFF

    def get_state(self) -> dict:
        """Return the current HVAC action."""
        response = super().get_state()
        if (
            self._cluster_handler.pi_heating_demand is None
            and self._cluster_handler.pi_cooling_demand is None
        ):
            response["state"] = self._rm_rs_action
        else:
            response["state"] = self._pi_demand_action
        return response


@MULTI_MATCH(
    cluster_handler_names={CLUSTER_HANDLER_THERMOSTAT},
    manufacturers="Sinope Technologies",
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class SinopeHVACAction(ThermostatHVACAction):
    """Sinope Thermostat HVAC action sensor."""

    @property
    def _rm_rs_action(self) -> HVACAction:
        """Return the current HVAC action based on running mode and running state."""

        running_mode = self._cluster_handler.running_mode
        if running_mode == self._cluster_handler.RunningMode.Heat:
            return HVACAction.HEATING
        if running_mode == self._cluster_handler.RunningMode.Cool:
            return HVACAction.COOLING

        running_state = self._cluster_handler.running_state
        if running_state and running_state & (
            self._cluster_handler.RunningState.Fan_State_On
            | self._cluster_handler.RunningState.Fan_2nd_Stage_On
            | self._cluster_handler.RunningState.Fan_3rd_Stage_On
        ):
            return HVACAction.FAN
        if (
            self._cluster_handler.system_mode != self._cluster_handler.SystemMode.Off
            and running_mode == self._cluster_handler.SystemMode.Off
        ):
            return HVACAction.IDLE
        return HVACAction.OFF


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_BASIC)
class RSSISensor(Sensor):
    """RSSI sensor for a device."""

    _attribute_name = "rssi"
    _unique_id_suffix = "rssi"
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_device_class: SensorDeviceClass | None = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement: str | None = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_should_poll = True  # BaseZhaEntity defaults to False
    _attr_translation_key: str = "rssi"

    @classmethod
    def create_entity(
        cls,
        unique_id: str,
        zha_device: ZHADevice,
        cluster_handlers: list[ClusterHandler],
        **kwargs: Any,
    ) -> Self | None:
        """Entity Factory.

        Return entity if it is a supported configuration, otherwise return None
        """
        key = f"{CLUSTER_HANDLER_BASIC}_{cls._unique_id_suffix}"
        if PLATFORM_ENTITIES.prevent_entity_creation(
            Platform.SENSOR, zha_device.ieee, key
        ):
            return None
        return cls(unique_id, zha_device, cluster_handlers, **kwargs)

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the entity."""
        return getattr(self._device.device, self._attribute_name)

    def get_state(self) -> dict:
        """Return the state of the sensor."""
        response = super().get_state()
        response["state"] = getattr(self.device.device, self._unique_id_suffix)
        return response


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_BASIC)
class LQISensor(RSSISensor):
    """LQI sensor for a device."""

    _attribute_name = "lqi"
    _unique_id_suffix = "lqi"
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_translation_key = "lqi"


@MULTI_MATCH(
    cluster_handler_names="tuya_manufacturer",
    manufacturers={
        "_TZE200_htnnfasr",
    },
)
class TimeLeft(Sensor):
    """Sensor that displays time left value."""

    _attribute_name = "timer_time_left"
    _unique_id_suffix = "time_left"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.DURATION
    _attr_icon = "mdi:timer"
    _attr_translation_key: str = "timer_time_left"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES


@MULTI_MATCH(cluster_handler_names="ikea_airpurifier")
class IkeaDeviceRunTime(Sensor):
    """Sensor that displays device run time (in minutes)."""

    _attribute_name = "device_run_time"
    _unique_id_suffix = "device_run_time"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.DURATION
    _attr_icon = "mdi:timer"
    _attr_translation_key: str = "device_run_time"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC


@MULTI_MATCH(cluster_handler_names="ikea_airpurifier")
class IkeaFilterRunTime(Sensor):
    """Sensor that displays run time of the current filter (in minutes)."""

    _attribute_name = "filter_run_time"
    _unique_id_suffix = "filter_run_time"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.DURATION
    _attr_icon = "mdi:timer"
    _attr_translation_key: str = "filter_run_time"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC


class AqaraFeedingSource(types.enum8):
    """Aqara pet feeder feeding source."""

    Feeder = 0x01
    HomeAssistant = 0x02


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"})
class AqaraPetFeederLastFeedingSource(EnumSensor):
    """Sensor that displays the last feeding source of pet feeder."""

    _attribute_name = "last_feeding_source"
    _unique_id_suffix = "last_feeding_source"
    _attr_translation_key: str = "last_feeding_source"
    _attr_icon = "mdi:devices"
    _enum = AqaraFeedingSource


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"})
class AqaraPetFeederLastFeedingSize(Sensor):
    """Sensor that displays the last feeding size of the pet feeder."""

    _attribute_name = "last_feeding_size"
    _unique_id_suffix = "last_feeding_size"
    _attr_translation_key: str = "last_feeding_size"
    _attr_icon: str = "mdi:counter"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"})
class AqaraPetFeederPortionsDispensed(Sensor):
    """Sensor that displays the number of portions dispensed by the pet feeder."""

    _attribute_name = "portions_dispensed"
    _unique_id_suffix = "portions_dispensed"
    _attr_translation_key: str = "portions_dispensed_today"
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _attr_icon: str = "mdi:counter"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"})
class AqaraPetFeederWeightDispensed(Sensor):
    """Sensor that displays the weight dispensed by the pet feeder."""

    _attribute_name = "weight_dispensed"
    _unique_id_suffix = "weight_dispensed"
    _attr_translation_key: str = "weight_dispensed_today"
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _attr_icon: str = "mdi:weight-gram"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"})
class AqaraSmokeDensityDbm(Sensor):
    """Sensor that displays the smoke density of an Aqara smoke sensor in dB/m."""

    _attribute_name = "smoke_density_dbm"
    _unique_id_suffix = "smoke_density_dbm"
    _attr_translation_key: str = "smoke_density"
    _attr_native_unit_of_measurement = "dB/m"
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_icon: str = "mdi:google-circles-communities"
    _attr_suggested_display_precision: int = 3


class SonoffIlluminationStates(types.enum8):
    """Enum for displaying last Illumination state."""

    Dark = 0x00
    Light = 0x01


@MULTI_MATCH(cluster_handler_names="sonoff_manufacturer", models={"SNZB-06P"})
class SonoffPresenceSenorIlluminationStatus(EnumSensor):
    """Sensor that displays the illumination status the last time peresence was detected."""

    _attribute_name = "last_illumination_state"
    _unique_id_suffix = "last_illumination"
    _attr_translation_key: str = "last_illumination_state"
    _attr_icon: str = "mdi:theme-light-dark"
    _enum = SonoffIlluminationStates


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT)
class PiHeatingDemand(Sensor):
    """Sensor that displays the percentage of heating power demanded.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "pi_heating_demand"
    _attribute_name = "pi_heating_demand"
    _attr_translation_key: str = "pi_heating_demand"
    _attr_icon: str = "mdi:radiator"
    _attr_native_unit_of_measurement = PERCENTAGE
    _decimals = 0
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC


class SetpointChangeSourceEnum(types.enum8):
    """The source of the setpoint change."""

    Manual = 0x00
    Schedule = 0x01
    External = 0x02


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT)
class SetpointChangeSource(EnumSensor):
    """Sensor that displays the source of the setpoint change.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "setpoint_change_source"
    _attribute_name = "setpoint_change_source"
    _attr_translation_key: str = "setpoint_change_source"
    _attr_icon: str = "mdi:thermostat"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _enum = SetpointChangeSourceEnum


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_COVER)
class WindowCoveringTypeSensor(EnumSensor):
    """Sensor that displays the type of a cover device."""

    _attribute_name: str = WindowCovering.AttributeDefs.window_covering_type.name
    _enum = WindowCovering.WindowCoveringType
    _unique_id_suffix: str = WindowCovering.AttributeDefs.window_covering_type.name
    _attr_translation_key: str = WindowCovering.AttributeDefs.window_covering_type.name
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:curtains"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_BASIC, models={"lumi.curtain.agl001"}
)
class AqaraCurtainMotorPowerSourceSensor(EnumSensor):
    """Sensor that displays the power source of the Aqara E1 curtain motor device."""

    _attribute_name: str = Basic.AttributeDefs.power_source.name
    _enum = Basic.PowerSource
    _unique_id_suffix: str = Basic.AttributeDefs.power_source.name
    _attr_translation_key: str = Basic.AttributeDefs.power_source.name
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-positive"


class AqaraE1HookState(types.enum8):
    """Aqara hook state."""

    Unlocked = 0x00
    Locked = 0x01
    Locking = 0x02
    Unlocking = 0x03


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.curtain.agl001"}
)
class AqaraCurtainHookStateSensor(EnumSensor):
    """Representation of a ZHA curtain mode configuration entity."""

    _attribute_name = "hooks_state"
    _enum = AqaraE1HookState
    _unique_id_suffix = "hooks_state"
    _attr_translation_key: str = "hooks_state"
    _attr_icon: str = "mdi:hook"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
