"""Sensors on Zigbee Home Automation networks."""  # pylint: disable=too-many-lines

from __future__ import annotations

from abc import ABC, abstractmethod
import contextlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import enum
import functools
import logging
import math
import numbers
import typing
from typing import TYPE_CHECKING, Any, cast

from zhaquirks.danfoss import thermostat as danfoss_thermostat
from zhaquirks.quirk_ids import DANFOSS_ALLY_THERMOSTAT, SE_POLL_SUMMATION
from zigpy import types
from zigpy.quirks.v2 import ZCLEnumMetadata, ZCLSensorMetadata
from zigpy.state import Counter, State
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
    foundation,
)
from zigpy.zcl.clusters.closures import WindowCovering
from zigpy.zcl.clusters.general import (
    AnalogInput,
    Basic,
    DeviceTemperature as DeviceTemperatureCluster,
    PowerConfiguration,
)
from zigpy.zcl.clusters.general_const import ApplicationType
from zigpy.zcl.clusters.homeautomation import Diagnostic, ElectricalMeasurement
from zigpy.zcl.clusters.hvac import Thermostat
from zigpy.zcl.clusters.measurement import (
    PM25 as PM25Cluster,
    CarbonDioxideConcentration as CarbonDioxideConcentrationCluster,
    CarbonMonoxideConcentration as CarbonMonoxideConcentrationCluster,
    ElectricalConductivity as ElectricalConductivityCluster,
    FlowMeasurement,
    FormaldehydeConcentration as FormaldehydeConcentrationCluster,
    IlluminanceMeasurement,
    LeafWetness as LeafWetnessCluster,
    PressureMeasurement,
    RelativeHumidity,
    SoilMoisture as SoilMoistureCluster,
    TemperatureMeasurement,
    WindSpeed as WindSpeedCluster,
)
from zigpy.zcl.clusters.smartenergy import (
    Metering,
    MeteringUnitofMeasure,
    NumberFormatting,
)

from zha.application import Platform
from zha.application.helpers import safe_read
from zha.application.platforms import (
    AttrConfig,
    BaseEntity,
    BaseEntityInfo,
    BaseIdentifiers,
    ClusterConfig,
    ClusterMatch,
    EntityCategory,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)
from zha.application.platforms.climate.const import HVACAction
from zha.application.platforms.const import (
    AQARA_OPPLE_CLUSTER,
    IKEA_AIR_PURIFIER_CLUSTER,
    INOVELLI_CLUSTER,
    SMARTTHINGS_HUMIDITY_CLUSTER,
    SONOFF_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
    VOC_LEVEL_CLUSTER,
)
from zha.application.platforms.helpers import validate_device_class
from zha.application.platforms.number.bacnet import BACNET_UNITS_TO_HA_UNITS
from zha.application.platforms.sensor.const import (
    ANALOG_INPUT_APPTYPE_DEV_CLASS,
    ANALOG_INPUT_APPTYPE_UNITS,
    LEGACY_MEASUREMENT_TYPE_REMAPPING,
    METERING_DEVICE_TYPES_ELECTRIC,
    METERING_DEVICE_TYPES_GAS,
    METERING_DEVICE_TYPES_HEATING_COOLING,
    METERING_DEVICE_TYPES_WATER,
    ZCL_EPOCH,
    DeviceStatusDefault,
    DeviceStatusElectric,
    DeviceStatusGas,
    DeviceStatusHeatingCooling,
    DeviceStatusWater,
    SensorDeviceClass,
    SensorStateClass,
    metering_device_type_name,
)
from zha.application.platforms.sensor.helpers import (
    create_number_formatter,
    resolution_to_decimal_precision,
)
from zha.application.platforms.virtual import VirtualEntity
from zha.decorators import periodic
from zha.units import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_BILLION,
    CONCENTRATION_PARTS_PER_MILLION,
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfApparentPower,
    UnitOfConductivity,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfMass,
    UnitOfPower,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

DEFAULT_FORMATTING = NumberFormatting(
    num_digits_right_of_decimal=1,
    num_digits_left_of_decimal=15,
    suppress_leading_zeros=1,
)

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


@dataclass(frozen=True, kw_only=True)
class SensorEntityInfo(BaseEntityInfo):
    """Sensor entity info."""

    suggested_display_precision: int | None = None
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None


@dataclass(frozen=True, kw_only=True)
class DeviceCounterEntityInfo(BaseEntityInfo):
    """Device counter entity info."""

    device_ieee: str
    suggested_display_precision: int
    available: bool
    counter: str
    counter_value: int
    counter_groups: str
    counter_group: str


@dataclass(frozen=True, kw_only=True)
class DeviceCounterSensorIdentifiers(BaseIdentifiers):
    """Device counter sensor identifiers."""

    device_ieee: str


class BaseSensor(PlatformEntity, ABC):
    """Abstract base class for ZHA sensor entities."""

    PLATFORM = Platform.SENSOR

    _attr_suggested_display_precision: int | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_device_class: SensorDeviceClass | None = None
    _attr_state_class: SensorStateClass | None = None

    @property
    def suggested_display_precision(self) -> int | None:
        """Return the suggested display precision."""
        return self._attr_suggested_display_precision

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""
        return self._attr_native_unit_of_measurement

    @functools.cached_property
    def info_object(self) -> SensorEntityInfo:
        """Return a representation of the sensor."""
        return SensorEntityInfo(
            **super().info_object.__dict__,
            suggested_display_precision=self.suggested_display_precision,
            unit=self.native_unit_of_measurement,
        )

    @property
    def state(self) -> dict:
        """Return the state for this sensor."""
        response = super().state
        response["state"] = self.native_value
        return response

    @property
    @abstractmethod
    def native_value(self) -> date | datetime | str | int | float | None:
        """Return the current sensor value."""


class Sensor(BaseSensor):
    """Base ZHA sensor."""

    _attribute_name: int | str | None = None
    _attribute_converter: typing.Callable[[typing.Any], typing.Any] | None = None
    _divisor: int | float | None = None
    _multiplier: int | float | None = None
    _skip_creation_if_no_attr_cache: bool = False

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        self._attr_def: foundation.ZCLAttributeDef | None = None

        super().__init__(endpoint=endpoint, device=device, **kwargs)

        # After super() for quirks v2 entities
        if self._attribute_name is not None:
            # Invalid attribute names filtered by is_supported
            with contextlib.suppress(KeyError):
                self._attr_def = self._cluster.find_attribute(self._attribute_name)

        self.recompute_capabilities()

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type, self.handle_attribute_updated
                )
            )

    def _is_supported(self) -> bool:
        if (
            self._attribute_name not in self._cluster.attributes_by_name
        ) or self._cluster.is_attribute_unsupported(self._attribute_name):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                self._attribute_name,
                self.__class__.__name__,
            )
            return False

        if (
            self._skip_creation_if_no_attr_cache
            and self._cluster.get(self._attribute_name) is None
        ):
            return False

        return super()._is_supported()

    def _validate_state_class(
        self,
        state_class_value: SensorStateClass,
    ) -> SensorStateClass | None:
        """Validate and return a state class."""
        try:
            return SensorStateClass(state_class_value)
        except ValueError as ex:
            _LOGGER.warning(
                "Quirks provided an invalid state class: %s: %s",
                state_class_value,
                ex,
            )
            return None

    def _init_from_quirks_metadata(self, entity_metadata: ZCLSensorMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        self._attribute_name = entity_metadata.attribute_name
        if entity_metadata.attribute_converter is not None:
            self._attribute_converter = entity_metadata.attribute_converter
        if entity_metadata.divisor is not None and entity_metadata.divisor != 1:
            self._divisor = entity_metadata.divisor
        if entity_metadata.multiplier is not None and entity_metadata.multiplier != 1:
            self._multiplier = entity_metadata.multiplier
        if entity_metadata.device_class is not None:
            self._attr_device_class = validate_device_class(
                SensorDeviceClass,
                entity_metadata.device_class,
                Platform.SENSOR.value,
                _LOGGER,
            )
        if entity_metadata.state_class is not None:
            self._attr_state_class = self._validate_state_class(
                entity_metadata.state_class
            )
        if entity_metadata.unit is not None:
            self._attr_native_unit_of_measurement = entity_metadata.unit

    @property
    def native_value(self) -> date | datetime | str | int | float | None:
        """Return the state of the entity."""
        assert self._attribute_name is not None
        raw_state = self._cluster.get(self._attribute_name)
        if raw_state is None:
            return None
        if self._is_non_value(raw_state):
            return None
        if self._attribute_converter:
            return self._attribute_converter(raw_state)
        return self.formatter(raw_state)

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle attribute updates from the cluster."""
        if (
            event.attribute_name == self._attribute_name
            or (
                hasattr(self, "_attr_extra_state_attribute_names")
                and event.attribute_name
                in getattr(self, "_attr_extra_state_attribute_names")
            )
            or self._attribute_name is None
        ):
            self.maybe_emit_state_changed_event()

    def _is_non_value(
        self, value: int | float, *, attr_def: foundation.ZCLAttributeDef | None = None
    ) -> bool:
        """Ignore non-value numerical values."""
        if isinstance(value, float) and math.isnan(value):
            return True

        if attr_def is None:
            attr_def = self._attr_def
        assert attr_def is not None

        data_type = foundation.DataType.from_type_id(attr_def.zcl_type)
        return value == data_type.non_value

    def formatter(self, value: Any) -> date | datetime | int | float | str | None:
        """Numeric pass-through formatter."""
        if self._multiplier is not None:
            value *= self._multiplier

        if self._divisor is not None:
            value /= self._divisor

        return value

    async def async_update(self) -> None:
        """Retrieve latest state."""
        if self._attribute_name is None:
            return
        self.debug("polling current state")
        await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()


class TimestampSensor(Sensor):
    """Timestamp ZHA sensor."""


class DeviceCounterSensor(BaseEntity):
    """Device counter sensor."""

    PLATFORM = Platform.SENSOR
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        zha_device: Device,
        counter_groups: str,
        counter_group: str,
        counter: str,
    ) -> None:
        """Init this sensor."""

        # XXX: ZHA uses the IEEE address of the device passed through `slugify`!
        slugified_device_id = zha_device.unique_id.replace(":", "-")
        super().__init__(
            unique_id=f"{slugified_device_id}_{counter_groups}_{counter_group}_{counter}"
        )

        self._device: Device = zha_device
        state: State = self._device.gateway.application_controller.state
        self._zigpy_counter: Counter = (
            getattr(state, counter_groups).get(counter_group, {}).get(counter, None)
        )
        self._zigpy_counter_groups: str = counter_groups
        self._zigpy_counter_group: str = counter_group

        self._attr_fallback_name: str = self._zigpy_counter.name
        self._always_supported: bool = True

        # TODO: why do entities get created with " None" as a name suffix instead of
        # falling back to `fallback_name`? We should be able to provide translation keys
        # even if they do not exist.
        # self._attr_translation_key = f"counter_{self._zigpy_counter.name.lower()}"

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._device.gateway.global_updater.register_update_listener(self.update)
        self._on_remove_callbacks.append(
            lambda: self._device.gateway.global_updater.remove_update_listener(
                self.update
            )
        )

    @functools.cached_property
    def identifiers(self) -> DeviceCounterSensorIdentifiers:
        """Return a dict with the information necessary to identify this entity."""
        return DeviceCounterSensorIdentifiers(
            **super().identifiers.__dict__, device_ieee=str(self._device.ieee)
        )

    @functools.cached_property
    def info_object(self) -> DeviceCounterEntityInfo:
        """Return a representation of the platform entity."""
        return DeviceCounterEntityInfo(
            **super().info_object.__dict__,
            suggested_display_precision=self._attr_suggested_display_precision,
            counter=self._zigpy_counter.name,
            counter_value=self._zigpy_counter.value,
            counter_groups=self._zigpy_counter_groups,
            counter_group=self._zigpy_counter_group,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Return the state for this sensor."""
        response = super().state
        response["state"] = self._zigpy_counter.value
        return response

    @property
    def native_value(self) -> int | None:
        """Return the state of the entity."""
        return self._zigpy_counter.value

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self._device.available

    @functools.cached_property
    def device(self) -> Device:
        """Return the device."""
        return self._device

    def enable(self) -> None:
        """Enable the entity."""
        super().enable()
        self._device.gateway.global_updater.register_update_listener(self.update)

    def disable(self) -> None:
        """Disable the entity."""
        super().disable()
        self._device.gateway.global_updater.remove_update_listener(self.update)

    def update(self):
        """Call async_update at a constrained random interval."""
        if self._device.available and self._device.gateway.config.allow_polling:
            self.debug("polling for updated state")
            self.maybe_emit_state_changed_event()
        else:
            self.debug(
                "skipping polling for updated state, available: %s, allow polled requests: %s",
                self._device.available,
                self._device.gateway.config.allow_polling,
            )


class EnumSensor(Sensor):
    """Sensor with value from enum."""

    _attr_device_class: SensorDeviceClass = SensorDeviceClass.ENUM
    _enum: type[enum.Enum]

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._attr_options = [e.name for e in self._enum]

        # XXX: This class is not meant to be initialized directly, as `unique_id`
        # depends on the value of `_attribute_name`

    def _init_from_quirks_metadata(self, entity_metadata: ZCLEnumMetadata) -> None:
        """Init this entity from the quirks metadata."""
        self._attribute_name = entity_metadata.attribute_name
        self._enum = entity_metadata.enum

        PlatformEntity._init_from_quirks_metadata(self, entity_metadata)  # pylint: disable=protected-access

    def formatter(self, value: int) -> str | None:
        """Use name of enum."""
        assert self._enum is not None
        return self._enum(value).name


@register_entity(AnalogInput.cluster_id)
class DigiAnalogInput(Sensor):
    """Sensor that displays analog input values."""

    _attribute_name = "present_value"
    _attr_translation_key: str = "analog_input"
    _cluster_id = AnalogInput.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AnalogInput.cluster_id}),
        manufacturers=frozenset({"Digi"}),
    )

    _server_cluster_config = {
        AnalogInput.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                AnalogInput.AttributeDefs.present_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                AnalogInput.AttributeDefs.description: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.max_present_value: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.min_present_value: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.out_of_service: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.reliability: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.resolution: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.status_flags: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.engineering_units: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogInput.AttributeDefs.application_type: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(AnalogInput.cluster_id)
class AnalogInputSensor(Sensor):
    """Sensor that displays analog input values."""

    _attribute_name = "present_value"
    _unique_id_suffix = "analog_input"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _cluster_id = AnalogInput.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AnalogInput.cluster_id}),
    )

    _server_cluster_config = {
        AnalogInput.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                AnalogInput.AttributeDefs.present_value: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                AnalogInput.AttributeDefs.description: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.max_present_value: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.min_present_value: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.out_of_service: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.reliability: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.resolution: AttrConfig(read_on_startup=False),
                AnalogInput.AttributeDefs.status_flags: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.engineering_units: AttrConfig(
                    read_on_startup=False
                ),
                AnalogInput.AttributeDefs.application_type: AttrConfig(
                    read_on_startup=False
                ),
            },
        ),
    }

    def _application_type(self):
        """Return the AnalogInput application_type as an ApplicationType type."""
        result = self._cluster.get(AnalogInput.AttributeDefs.application_type.name)
        if result is None:
            return None
        return ApplicationType.deserialize(types.uint32_t(result).serialize())[0]

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()

        self._attr_fallback_name = self._cluster.get(
            AnalogInput.AttributeDefs.description.name
        )

        application_type = self._application_type()
        if application_type is not None:
            # The application type encodes a tiny bit more info but it's mostly
            # irrelevant, just use the `type` sub-field
            app_type = application_type.type
            self._attr_device_class = ANALOG_INPUT_APPTYPE_DEV_CLASS.get(app_type)

            # Application type units take precedence
            self._attr_native_unit_of_measurement = ANALOG_INPUT_APPTYPE_UNITS.get(
                app_type
            )
        else:
            self._attr_native_unit_of_measurement = BACNET_UNITS_TO_HA_UNITS.get(
                self._cluster.get(AnalogInput.AttributeDefs.engineering_units.name)
            )

        # Resolution indicates the minimum change in value that can be detected
        resolution = self._cluster.get(AnalogInput.AttributeDefs.resolution.name)
        if resolution is not None:
            self._attr_suggested_display_precision = resolution_to_decimal_precision(
                resolution
            )

    def _is_supported(self) -> bool:
        """Return True if this sensor is supported."""
        if self._cluster.get(AnalogInput.AttributeDefs.description.name) is None:
            return False

        # The units are determined by one of these
        if (
            self._application_type() is None
            and self._cluster.get(AnalogInput.AttributeDefs.engineering_units.name)
            is None
        ):
            return False

        return super()._is_supported()


@register_entity(PowerConfiguration.cluster_id)
class Battery(Sensor):
    """Battery sensor of power configuration cluster."""

    _attribute_name = "battery_percentage_remaining"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.BATTERY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision: int = 0
    _attr_extra_state_attribute_names: set[str] = {
        "battery_size",
        "battery_quantity",
        "battery_voltage",
    }
    _cluster_id = PowerConfiguration.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({PowerConfiguration.cluster_id}),
    )

    _server_cluster_config = {
        PowerConfiguration.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                PowerConfiguration.AttributeDefs.battery_voltage: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=3600, max_interval=10800, reportable_change=1
                    ),
                ),
                PowerConfiguration.AttributeDefs.battery_percentage_remaining: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=3600, max_interval=10800, reportable_change=1
                    ),
                ),
                PowerConfiguration.AttributeDefs.battery_size: AttrConfig(
                    read_on_startup=False,
                ),
                PowerConfiguration.AttributeDefs.battery_quantity: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def _is_supported(self) -> bool:
        # XXX: We intentionally ignore the presence of this attribute
        return PlatformEntity._is_supported(self) and not self.device.is_mains_powered

    @staticmethod
    def formatter(value: int) -> float | None:  # pylint: disable=arguments-differ
        """Return the state of the entity."""
        # per zcl specs battery percent is reported at 200% ¯\_(ツ)_/¯
        if not isinstance(value, numbers.Number) or value in (-1, 255):
            return None
        return value / 2

    @property
    def state(self) -> dict[str, Any]:
        """Return the state for battery sensors."""
        response = super().state
        battery_size = self._cluster.get("battery_size")
        if battery_size is not None:
            response["battery_size"] = BATTERY_SIZES.get(battery_size, "Unknown")
        battery_quantity = self._cluster.get("battery_quantity")
        if battery_quantity is not None:
            response["battery_quantity"] = battery_quantity
        battery_voltage = self._cluster.get("battery_voltage")
        if battery_voltage is not None:
            response["battery_voltage"] = round(battery_voltage / 10, 2)
        return response


class BaseElectricalMeasurement(Sensor):
    """Base class for electrical measurement."""

    _attr_max_attribute_name: str | None
    _multiplier_attribute_name: str | None
    _multiplier_fallback_attribute_name: str | None
    _divisor_attribute_name: str | None
    _divisor_fallback_attribute_name: str | None

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._attr_extra_state_attribute_names: set[str] = {"measurement_type"}
        if self._attr_max_attribute_name is not None:
            self._attr_extra_state_attribute_names.add(self._attr_max_attribute_name)

    @property
    def _measurement_type(self) -> str | None:
        """Decode the measurement_type bitmap into a human-readable string."""
        meas_type = self._cluster.get(
            ElectricalMeasurement.AttributeDefs.measurement_type.name
        )
        if meas_type is None:
            return None

        # Iterating over the bits only yields named bits so the earlier version of this
        # code omitted any measurement types that were not explicitly in the bitmap type.
        # TODO: deprecate this
        return ", ".join(
            LEGACY_MEASUREMENT_TYPE_REMAPPING[m]
            for m in ElectricalMeasurement.MeasurementType(meas_type)
            if m in LEGACY_MEASUREMENT_TYPE_REMAPPING
        )

    @property
    def state(self) -> dict[str, Any]:
        """Return the state for this sensor."""
        response = super().state
        meas_type = self._measurement_type
        if meas_type is not None:
            response["measurement_type"] = meas_type

        if (max_attr_name := self._attr_max_attribute_name) is None:
            return response

        if (max_v := self._cluster.get(max_attr_name)) is not None:
            response[max_attr_name] = self.formatter(max_v)

        return response

    @property
    def _multiplier(self) -> int | float | None:
        if not self._multiplier_attribute_name:
            return super()._multiplier

        value = self._cluster.get(self._multiplier_attribute_name)
        if value is None and self._multiplier_fallback_attribute_name:
            value = self._cluster.get(self._multiplier_fallback_attribute_name)
        return value or 1

    @_multiplier.setter
    def _multiplier(self, value: int | float | None) -> None:
        raise AttributeError("Cannot set multiplier directly")

    @property
    def _divisor(self) -> int | float | None:
        if not self._divisor_attribute_name:
            return super()._divisor

        value = self._cluster.get(self._divisor_attribute_name)
        if value is None and self._divisor_fallback_attribute_name:
            value = self._cluster.get(self._divisor_fallback_attribute_name)
        return value or 1

    @_divisor.setter
    def _divisor(self, value: int | float | None) -> None:
        raise AttributeError("Cannot set divisor directly")


class AggregatedClusterPoller(VirtualEntity):
    """Polls a cluster on behalf of sibling entities that need updates.

    Builds the polling list dynamically from the cluster configs of enabled
    sibling entities sharing this cluster — so disabling an entity in HA
    drops its attributes from the poll on the next cycle.
    """

    _cluster_id: int
    _REFRESH_INTERVAL = (30, 45)

    def on_add(self) -> None:
        """Start the periodic polling task."""
        super().on_add()
        task = self.device.gateway.async_create_background_task(
            self._refresh(),
            name=f"cluster_poller_{self.unique_id}",
            eager_start=True,
            untracked=True,
        )
        self._tracked_tasks.append(task)

    @periodic(_REFRESH_INTERVAL)
    async def _refresh(self) -> None:
        if not (self.device.available and self.device.gateway.config.allow_polling):
            return
        await self.async_update()

    async def async_update(self) -> None:
        """Poll the union of attrs read by enabled sibling entities."""
        attrs: set[str] = set()
        for entity in self.device.platform_entities.values():
            if entity is self or not isinstance(entity, Sensor):
                continue
            if entity._cluster is not self._cluster:
                continue
            if not entity.enabled:
                continue
            if entity._attribute_name and self._cluster.is_attribute_unsupported(
                entity._attribute_name
            ):
                continue
            cfg = entity._server_cluster_config.get(self._cluster_id)
            if cfg is None:
                continue
            for attr_def, attr_cfg in cfg.attributes.items():
                if attr_cfg.reporting is None:
                    continue
                if self._cluster.is_attribute_unsupported(attr_def):
                    continue

                attrs.add(attr_def if isinstance(attr_def, str) else attr_def.name)

        if not attrs:
            return

        self.debug("polling %d attrs: %s", len(attrs), sorted(attrs))
        await safe_read(
            self._cluster, sorted(attrs), allow_cache=False, only_cache=False
        )


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementPoller(AggregatedClusterPoller):
    """Polls the EM cluster on behalf of sibling entities that need updates."""

    _unique_id_suffix = "em_poller"
    _cluster_id = ElectricalMeasurement.cluster_id
    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
        feature_priority=(PlatformFeatureGroup.EM_POLLING, 0),
    )


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementReportingDevice(VirtualEntity):
    """Claims the EM polling slot for devices that support reporting.

    Higher priority than the default `ElectricalMeasurementPoller`, so for
    matching models the poller is not registered and no polling occurs.
    """

    _unique_id_suffix = "em_reporting_device"
    _cluster_id = ElectricalMeasurement.cluster_id
    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
        models=frozenset({"VZM31-SN", "SP 234", "outletv4", "INSPELNING Smart plug"}),
        feature_priority=(PlatformFeatureGroup.EM_POLLING, 1),
    )


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementActivePower(BaseElectricalMeasurement):
    """Active power measurement."""

    _attribute_name = "active_power"
    _attr_max_attribute_name = "active_power_max"
    _divisor_attribute_name = "ac_power_divisor"
    _divisor_fallback_attribute_name = "power_divisor"
    _multiplier_attribute_name = "ac_power_multiplier"
    _multiplier_fallback_attribute_name = "power_multiplier"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement: str = UnitOfPower.WATT
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power_max: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementActivePowerPhB(BaseElectricalMeasurement):
    """Active power phase B measurement."""

    _attribute_name = "active_power_ph_b"
    _unique_id_suffix = "active_power_ph_b"
    _attr_translation_key: str = "active_power_ph_b"
    _attr_max_attribute_name = "active_power_max_ph_b"
    _divisor_attribute_name = "ac_power_divisor"
    _divisor_fallback_attribute_name = "power_divisor"
    _multiplier_attribute_name = "ac_power_multiplier"
    _multiplier_fallback_attribute_name = "power_multiplier"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement: str = UnitOfPower.WATT
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power_ph_b: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power_max_ph_b: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementActivePowerPhC(BaseElectricalMeasurement):
    """Active power phase C measurement."""

    _attribute_name = "active_power_ph_c"
    _unique_id_suffix = "active_power_ph_c"
    _attr_translation_key: str = "active_power_ph_c"
    _attr_max_attribute_name = "active_power_max_ph_c"
    _divisor_attribute_name = "ac_power_divisor"
    _divisor_fallback_attribute_name = "power_divisor"
    _multiplier_attribute_name = "ac_power_multiplier"
    _multiplier_fallback_attribute_name = "power_multiplier"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement: str = UnitOfPower.WATT
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power_ph_c: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power_max_ph_c: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementTotalActivePower(BaseElectricalMeasurement):
    """Total active power measurement."""

    _attribute_name = "total_active_power"
    _unique_id_suffix = "total_active_power"
    _attr_translation_key: str = "total_active_power"
    _attr_max_attribute_name = "active_power_max"
    _divisor_attribute_name = "ac_power_divisor"
    _divisor_fallback_attribute_name = "power_divisor"
    _multiplier_attribute_name = "ac_power_multiplier"
    _multiplier_fallback_attribute_name = "power_multiplier"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement: str = UnitOfPower.WATT
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.total_active_power: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.active_power_max: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementApparentPower(BaseElectricalMeasurement):
    """Apparent power measurement."""

    _attribute_name = "apparent_power"
    _unique_id_suffix = "apparent_power"
    _attr_max_attribute_name = None
    _divisor_attribute_name = "ac_power_divisor"
    _divisor_fallback_attribute_name = "power_divisor"
    _multiplier_attribute_name = "ac_power_multiplier"
    _multiplier_fallback_attribute_name = "power_multiplier"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.APPARENT_POWER
    _attr_native_unit_of_measurement = UnitOfApparentPower.VOLT_AMPERE
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.apparent_power: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementRMSCurrent(BaseElectricalMeasurement):
    """RMS current measurement."""

    _attr_suggested_display_precision = 2
    _attribute_name = "rms_current"
    _unique_id_suffix = "rms_current"
    _attr_max_attribute_name = "rms_current_max"
    _divisor_attribute_name = "ac_current_divisor"
    _divisor_fallback_attribute_name = None
    _multiplier_attribute_name = "ac_current_multiplier"
    _multiplier_fallback_attribute_name = None
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_current_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_current_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_current: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_current_max: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementRMSCurrentPhB(ElectricalMeasurementRMSCurrent):
    """RMS current phase B measurement."""

    _attribute_name = "rms_current_ph_b"
    _unique_id_suffix = "rms_current_ph_b"
    _attr_translation_key: str = "rms_current_ph_b"
    _attr_max_attribute_name: str = "rms_current_max_ph_b"
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_current_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_current_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_current_ph_b: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_current_max_ph_b: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementRMSCurrentPhC(ElectricalMeasurementRMSCurrent):
    """RMS current phase C measurement."""

    _attribute_name: str = "rms_current_ph_c"
    _unique_id_suffix: str = "rms_current_ph_c"
    _attr_translation_key: str = "rms_current_ph_c"
    _attr_max_attribute_name: str = "rms_current_max_ph_c"
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_current_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_current_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_current_ph_c: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_current_max_ph_c: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementRMSVoltage(BaseElectricalMeasurement):
    """RMS Voltage measurement."""

    _attribute_name = "rms_voltage"
    _unique_id_suffix = "rms_voltage"
    _attr_max_attribute_name = "rms_voltage_max"
    _divisor_attribute_name = "ac_voltage_divisor"
    _divisor_fallback_attribute_name = None
    _multiplier_attribute_name = "ac_voltage_multiplier"
    _multiplier_fallback_attribute_name = None
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_voltage_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_voltage_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_voltage: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_voltage_max: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementRMSVoltagePhB(ElectricalMeasurementRMSVoltage):
    """RMS voltage phase B measurement."""

    _attribute_name = "rms_voltage_ph_b"
    _unique_id_suffix = "rms_voltage_ph_b"
    _attr_translation_key: str = "rms_voltage_ph_b"
    _attr_max_attribute_name = "rms_voltage_max_ph_b"
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_voltage_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_voltage_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_voltage_ph_b: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_voltage_max_ph_b: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementRMSVoltagePhC(ElectricalMeasurementRMSVoltage):
    """RMS voltage phase C measurement."""

    _attribute_name = "rms_voltage_ph_c"
    _unique_id_suffix = "rms_voltage_ph_c"
    _attr_translation_key: str = "rms_voltage_ph_c"
    _attr_max_attribute_name = "rms_voltage_max_ph_c"
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_voltage_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_voltage_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_voltage_ph_c: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.rms_voltage_max_ph_c: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementFrequency(BaseElectricalMeasurement):
    """Frequency measurement."""

    _attribute_name = "ac_frequency"
    _unique_id_suffix = "ac_frequency"
    _attr_translation_key: str = "ac_frequency"
    _attr_max_attribute_name = "ac_frequency_max"
    _divisor_attribute_name = "ac_frequency_divisor"
    _divisor_fallback_attribute_name = None
    _multiplier_attribute_name = "ac_frequency_multiplier"
    _multiplier_fallback_attribute_name = None
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_frequency_multiplier: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_frequency_divisor: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.ac_frequency: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.ac_frequency_max: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementPowerFactor(BaseElectricalMeasurement):
    """Power Factor measurement."""

    _attribute_name = "power_factor"
    _unique_id_suffix = "power_factor"
    _attr_max_attribute_name = None
    _divisor_attribute_name = None
    _divisor_fallback_attribute_name = None
    _multiplier_attribute_name = None
    _multiplier_fallback_attribute_name = None
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER_FACTOR
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.power_factor: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementPowerFactorPhB(ElectricalMeasurementPowerFactor):
    """Power factor phase B measurement."""

    _attribute_name = "power_factor_ph_b"
    _unique_id_suffix = "power_factor_ph_b"
    _attr_translation_key: str = "power_factor_ph_b"
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.power_factor_ph_b: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementPowerFactorPhC(ElectricalMeasurementPowerFactor):
    """Power factor phase C measurement."""

    _attribute_name = "power_factor_ph_c"
    _unique_id_suffix = "power_factor_ph_c"
    _attr_translation_key: str = "power_factor_ph_c"
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.power_factor_ph_c: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementDCVoltage(BaseElectricalMeasurement):
    """DC Voltage measurement."""

    _attribute_name = "dc_voltage"
    _unique_id_suffix = "dc_voltage"
    _attr_translation_key: str = "dc_voltage"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_max_attribute_name = None
    _divisor_attribute_name = "dc_voltage_divisor"
    _divisor_fallback_attribute_name = None
    _multiplier_attribute_name = "dc_voltage_multiplier"
    _multiplier_fallback_attribute_name = None
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.dc_voltage_multiplier: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.dc_voltage_divisor: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.dc_voltage: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementDCCurrent(BaseElectricalMeasurement):
    """DC Current measurement."""

    _attribute_name = "dc_current"
    _unique_id_suffix = "dc_current"
    _attr_translation_key: str = "dc_current"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_max_attribute_name = None
    _divisor_attribute_name = "dc_current_divisor"
    _divisor_fallback_attribute_name = None
    _multiplier_attribute_name = "dc_current_multiplier"
    _multiplier_fallback_attribute_name = None
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.dc_current_multiplier: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.dc_current_divisor: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.dc_current: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementDCPower(BaseElectricalMeasurement):
    """DC Power measurement."""

    _attribute_name = "dc_power"
    _unique_id_suffix = "dc_power"
    _attr_translation_key: str = "dc_power"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_max_attribute_name = None
    _divisor_attribute_name = "dc_power_divisor"
    _divisor_fallback_attribute_name = "power_divisor"
    _multiplier_attribute_name = "dc_power_multiplier"
    _multiplier_fallback_attribute_name = "power_multiplier"
    _attr_suggested_display_precision = 1
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = ElectricalMeasurement.cluster_id
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalMeasurement.AttributeDefs.measurement_type: AttrConfig(
                    read_on_startup=False,
                ),
                ElectricalMeasurement.AttributeDefs.dc_power_multiplier: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.dc_power_divisor: AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_multiplier: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.power_divisor: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                ElectricalMeasurement.AttributeDefs.dc_power: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(RelativeHumidity.cluster_id)
class Humidity(Sensor):
    """Humidity sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.HUMIDITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_primary_weight = 1
    _cluster_id = RelativeHumidity.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({RelativeHumidity.cluster_id}),
    )

    _server_cluster_config = {
        RelativeHumidity.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                RelativeHumidity.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=100
                    ),
                ),
            },
        ),
    }


@register_entity(SMARTTHINGS_HUMIDITY_CLUSTER)
class SmartThingsHumidity(Sensor):
    """Humidity sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.HUMIDITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_primary_weight = 1
    _cluster_id = SMARTTHINGS_HUMIDITY_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SMARTTHINGS_HUMIDITY_CLUSTER}),
    )

    _server_cluster_config = {
        SMARTTHINGS_HUMIDITY_CLUSTER: ClusterConfig(
            bind=True,
            attributes={
                "measured_value": AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=50
                    ),
                ),
            },
        ),
    }


@register_entity(SoilMoistureCluster.cluster_id)
class SoilMoisture(Sensor):
    """Soil Moisture sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.MOISTURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "soil_moisture"
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_primary_weight = 1
    _cluster_id = SoilMoistureCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SoilMoistureCluster.cluster_id}),
    )

    _server_cluster_config = {
        SoilMoistureCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                SoilMoistureCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=100
                    ),
                ),
            },
        ),
    }


@register_entity(LeafWetnessCluster.cluster_id)
class LeafWetness(Sensor):
    """Leaf Wetness sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.HUMIDITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "leaf_wetness"
    _divisor = 100
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_primary_weight = 1
    _cluster_id = LeafWetnessCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LeafWetnessCluster.cluster_id}),
    )

    _server_cluster_config = {
        LeafWetnessCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                LeafWetnessCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=100
                    ),
                ),
            },
        ),
    }


@register_entity(IlluminanceMeasurement.cluster_id)
class Illuminance(Sensor):
    """Illuminance Sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.ILLUMINANCE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_primary_weight = 1
    _cluster_id = IlluminanceMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IlluminanceMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        IlluminanceMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                IlluminanceMeasurement.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }

    def formatter(self, value: int) -> int | None:
        """Convert illumination data."""
        if self._is_non_value(value):
            return None
        if value == 0:
            return 0
        return round(pow(10, ((value - 1) / 10000)))


@dataclass(frozen=True, kw_only=True)
class SmartEnergyMeteringEntityDescription:
    """Dataclass that describes a Zigbee smart energy metering entity."""

    key: str = "instantaneous_demand"
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    scale: int = 1
    native_unit_of_measurement: str | None = None
    device_class: SensorDeviceClass | None = None


@register_entity(Metering.cluster_id)
class MeteringPoller(AggregatedClusterPoller):
    """Polls the Metering cluster for models known to need polling.

    Default Metering devices report reliably; only this short list of models
    are known to require polling.
    """

    _unique_id_suffix = "metering_poller"
    _cluster_id = Metering.cluster_id
    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"TS011F", "ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class ExposedFeatureMeteringPoller(MeteringPoller):
    """Polls the Metering cluster for devices whose quirk exposes SE_POLL_SUMMATION."""

    _unique_id_suffix = "metering_poller"
    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        exposed_features=frozenset({SE_POLL_SUMMATION}),
    )


@register_entity(Metering.cluster_id)
class SmartEnergyMetering(Sensor):
    """Metering sensor."""

    entity_description: SmartEnergyMeteringEntityDescription
    _attr_suggested_display_precision = 1
    _attribute_name = "instantaneous_demand"
    _attr_translation_key: str = "instantaneous_demand"
    _attr_extra_state_attribute_names: set[str] = {
        "device_type",
        "status",
        "zcl_unit_of_measurement",
    }
    _attr_primary_weight = 1
    _cluster_id = Metering.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
    )

    _server_cluster_config = {
        Metering.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                Metering.AttributeDefs.instantaneous_demand: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=5, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_tier1_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_tier2_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_tier3_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_tier4_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_tier5_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_tier6_summ_delivered: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.current_summ_received: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.status: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
                Metering.AttributeDefs.demand_formatting: AttrConfig(
                    read_on_startup=False,
                ),
                Metering.AttributeDefs.divisor: AttrConfig(
                    read_on_startup=False,
                ),
                Metering.AttributeDefs.metering_device_type: AttrConfig(
                    read_on_startup=False,
                ),
                Metering.AttributeDefs.multiplier: AttrConfig(
                    read_on_startup=False,
                ),
                Metering.AttributeDefs.summation_formatting: AttrConfig(
                    read_on_startup=False,
                ),
                Metering.AttributeDefs.unit_of_measure: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

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

    @property
    def _unit_of_measurement(self) -> int | None:
        return self._cluster.get(Metering.AttributeDefs.unit_of_measure.name)

    @property
    def _device_type(self) -> str | int | None:
        dev_type = self._cluster.get(Metering.AttributeDefs.metering_device_type.name)
        if dev_type is None:
            return None
        return metering_device_type_name(dev_type)

    @property
    def _metering_status(self) -> int | None:
        if (status := self._cluster.get(Metering.AttributeDefs.status.name)) is None:
            return None
        dev_type = self._cluster.get(Metering.AttributeDefs.metering_device_type.name)
        if dev_type in METERING_DEVICE_TYPES_ELECTRIC:
            return DeviceStatusElectric(status)
        if dev_type in METERING_DEVICE_TYPES_GAS:
            return DeviceStatusGas(status)
        if dev_type in METERING_DEVICE_TYPES_WATER:
            return DeviceStatusWater(status)
        if dev_type in METERING_DEVICE_TYPES_HEATING_COOLING:
            return DeviceStatusHeatingCooling(status)
        return DeviceStatusDefault(status)

    def _is_supported(self) -> bool:
        unit = self._unit_of_measurement
        if self._is_non_value(unit, attr_def=Metering.AttributeDefs.unit_of_measure):
            return False

        return super()._is_supported()

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags."""
        super().recompute_capabilities()
        entity_description = self._ENTITY_DESCRIPTION_MAP.get(self._unit_of_measurement)
        if entity_description is not None:
            self.entity_description = entity_description
            self._attr_device_class = entity_description.device_class
            self._attr_state_class = entity_description.state_class
            self._attr_native_unit_of_measurement = (
                entity_description.native_unit_of_measurement
            )

    @property
    def state(self) -> dict[str, Any]:
        """Return state for this sensor."""
        response = super().state
        if self._device_type is not None:
            response["device_type"] = self._device_type
        if (status := self._metering_status) is not None:
            if isinstance(status, enum.IntFlag):
                response["status"] = str(
                    status.name if status.name is not None else status.value
                )
            else:
                response["status"] = str(status)[len(status.__class__.__name__) + 1 :]
        response["zcl_unit_of_measurement"] = self._unit_of_measurement
        return response

    @property
    def _multiplier(self) -> int | float | None:
        return self._cluster.get(Metering.AttributeDefs.multiplier.name) or 1

    @_multiplier.setter
    def _multiplier(self, value: int | float | None) -> None:
        raise AttributeError("Cannot set multiplier directly")

    @property
    def _divisor(self) -> int | float | None:
        return self._cluster.get(Metering.AttributeDefs.divisor.name) or 1

    @_divisor.setter
    def _divisor(self, value: int | float | None) -> None:
        raise AttributeError("Cannot set divisor directly")

    def formatter(self, value: int) -> int | float:
        """Metering formatter."""
        # TODO: improve typing for base class
        scaled_value = cast(float, super().formatter(value))

        if self._unit_of_measurement == MeteringUnitofMeasure.Kwh_and_Kwh_binary:
            # Zigbee spec power unit is kW, but we show the value in W
            value_watt = scaled_value * 1000
            if value_watt < 100:
                return round(value_watt, 1)
            return round(value_watt)

        demand_formatting = self._cluster.get(
            Metering.AttributeDefs.demand_formatting.name
        )
        demand_formater = create_number_formatter(
            demand_formatting if demand_formatting is not None else DEFAULT_FORMATTING
        )
        return float(demand_formater.format(scaled_value))


@dataclass(frozen=True, kw_only=True)
class SmartEnergySummationEntityDescription(SmartEnergyMeteringEntityDescription):
    """Dataclass that describes a Zigbee smart energy summation entity."""

    key: str = "summation_delivered"
    state_class: SensorStateClass | None = SensorStateClass.TOTAL_INCREASING


@register_entity(Metering.cluster_id)
class SmartEnergySummation(SmartEnergyMetering):
    """Smart Energy Metering summation sensor."""

    entity_description: SmartEnergySummationEntityDescription
    _attribute_name = "current_summ_delivered"
    _unique_id_suffix = "summation_delivered"
    _attr_translation_key: str = "summation_delivered"
    _attr_suggested_display_precision: int = 3

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
    )

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
        """Metering summation formatter."""
        # TODO: improve typing for base class
        scaled_value = cast(float, Sensor.formatter(self, value))

        if self._unit_of_measurement == MeteringUnitofMeasure.Kwh_and_Kwh_binary:
            return scaled_value

        summation_formatting = self._cluster.get(
            Metering.AttributeDefs.summation_formatting.name
        )
        summation_formater = create_number_formatter(
            summation_formatting
            if summation_formatting is not None
            else DEFAULT_FORMATTING
        )
        return float(summation_formater.format(scaled_value))


@register_entity(Metering.cluster_id)
class Tier1SmartEnergySummation(SmartEnergySummation):
    """Tier 1 Smart Energy Metering summation sensor."""

    _attribute_name = "current_tier1_summ_delivered"
    _unique_id_suffix = "tier1_summation_delivered"
    _attr_translation_key: str = "tier1_summation_delivered"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class Tier2SmartEnergySummation(SmartEnergySummation):
    """Tier 2 Smart Energy Metering summation sensor."""

    _attribute_name = "current_tier2_summ_delivered"
    _unique_id_suffix = "tier2_summation_delivered"
    _attr_translation_key: str = "tier2_summation_delivered"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class Tier3SmartEnergySummation(SmartEnergySummation):
    """Tier 3 Smart Energy Metering summation sensor."""

    _attribute_name = "current_tier3_summ_delivered"
    _unique_id_suffix = "tier3_summation_delivered"
    _attr_translation_key: str = "tier3_summation_delivered"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class Tier4SmartEnergySummation(SmartEnergySummation):
    """Tier 4 Smart Energy Metering summation sensor."""

    _attribute_name = "current_tier4_summ_delivered"
    _unique_id_suffix = "tier4_summation_delivered"
    _attr_translation_key: str = "tier4_summation_delivered"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class Tier5SmartEnergySummation(SmartEnergySummation):
    """Tier 5 Smart Energy Metering summation sensor."""

    _attribute_name = "current_tier5_summ_delivered"
    _unique_id_suffix = "tier5_summation_delivered"
    _attr_translation_key: str = "tier5_summation_delivered"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class Tier6SmartEnergySummation(SmartEnergySummation):
    """Tier 6 Smart Energy Metering summation sensor."""

    _attribute_name = "current_tier6_summ_delivered"
    _unique_id_suffix = "tier6_summation_delivered"
    _attr_translation_key: str = "tier6_summation_delivered"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
        models=frozenset({"ZLinky_TIC", "TICMeter"}),
    )


@register_entity(Metering.cluster_id)
class SmartEnergySummationReceived(SmartEnergySummation):
    """Smart Energy Metering summation received sensor."""

    _attribute_name = "current_summ_received"
    _unique_id_suffix = "summation_received"
    _attr_translation_key: str = "summation_received"

    # This attribute only started to be initialized in HA 2024.2.0, so the entity would
    # be created on the first HA start after the upgrade for existing devices, as the
    # initialization to see if an attribute is unsupported happens later in the
    # background. To avoid creating unnecessary entities for existing devices, wait
    # until the attribute was properly initialized once for now.
    _skip_creation_if_no_attr_cache = True

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Metering.cluster_id}),
    )


@register_entity(PressureMeasurement.cluster_id)
class Pressure(Sensor):
    """Pressure sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.PRESSURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision: int = 0
    _attr_native_unit_of_measurement = UnitOfPressure.HPA
    _attr_primary_weight = 1
    _cluster_id = PressureMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({PressureMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        PressureMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                PressureMeasurement.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(FlowMeasurement.cluster_id)
class Flow(Sensor):
    """Flow Measurement sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 10
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR
    _attr_primary_weight = 1
    _cluster_id = FlowMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({FlowMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        FlowMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                FlowMeasurement.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(TemperatureMeasurement.cluster_id)
class Temperature(Sensor):
    """Temperature Sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.TEMPERATURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 100
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_primary_weight = 1
    _cluster_id = TemperatureMeasurement.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TemperatureMeasurement.cluster_id}),
    )

    _server_cluster_config = {
        TemperatureMeasurement.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                TemperatureMeasurement.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=50
                    ),
                ),
            },
        ),
    }


@register_entity(DeviceTemperatureCluster.cluster_id)
class DeviceTemperature(Sensor):
    """Device Temperature Sensor."""

    _attribute_name = "current_temperature"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.TEMPERATURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "device_temperature"
    _divisor = 100
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_primary_weight = 1
    _cluster_id = DeviceTemperatureCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({DeviceTemperatureCluster.cluster_id}),
    )

    _server_cluster_config = {
        DeviceTemperatureCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                DeviceTemperatureCluster.AttributeDefs.current_temperature: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=50
                    ),
                ),
            },
        ),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliInternalTemperature(Sensor):
    """Switch Internal Temperature Sensor."""

    _attribute_name = "internal_temp_monitor"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.TEMPERATURE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "internal_temp_monitor"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


class InovelliOverheatedState(types.enum8):
    """Inovelli overheat protection state."""

    Normal = 0x00
    Overheated = 0x01


@register_entity(INOVELLI_CLUSTER)
class InovelliOverheated(EnumSensor):
    """Sensor that displays the overheat protection state."""

    _attribute_name = "overheated"
    _unique_id_suffix = "overheated"
    _attr_translation_key: str = "overheated"
    _enum = InovelliOverheatedState
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(CarbonDioxideConcentrationCluster.cluster_id)
class CarbonDioxideConcentration(Sensor):
    """Carbon Dioxide Concentration sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CO2
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
    _attr_primary_weight = 1
    _cluster_id = CarbonDioxideConcentrationCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({CarbonDioxideConcentrationCluster.cluster_id}),
    )

    _server_cluster_config = {
        CarbonDioxideConcentrationCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                CarbonDioxideConcentrationCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=0.000001
                    ),
                ),
            },
        ),
    }


@register_entity(CarbonMonoxideConcentrationCluster.cluster_id)
class CarbonMonoxideConcentration(Sensor):
    """Carbon Monoxide Concentration sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CO
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
    _attr_primary_weight = 1
    _cluster_id = CarbonMonoxideConcentrationCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({CarbonMonoxideConcentrationCluster.cluster_id}),
    )

    _server_cluster_config = {
        CarbonMonoxideConcentrationCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                CarbonMonoxideConcentrationCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=0.000001
                    ),
                ),
            },
        ),
    }


@register_entity(VOC_LEVEL_CLUSTER)
class VOCLevel(Sensor):
    """VOC Level sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    _attr_primary_weight = 1

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({VOC_LEVEL_CLUSTER}),
        feature_priority=(PlatformFeatureGroup.VOC_LEVEL, 0),
    )

    _server_cluster_config = {
        VOC_LEVEL_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(VOC_LEVEL_CLUSTER)
class PPBVOCLevel(Sensor):
    """VOC Level sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = (
        SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS
    )
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _multiplier = 1
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_BILLION
    _attr_primary_weight = 1

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({VOC_LEVEL_CLUSTER}),
        models=frozenset({"lumi.airmonitor.acn01"}),
        feature_priority=(PlatformFeatureGroup.VOC_LEVEL, 1),
    )

    _server_cluster_config = {
        VOC_LEVEL_CLUSTER: ClusterConfig(bind=True),
    }


@register_entity(PM25Cluster.cluster_id)
class PM25(Sensor):
    """Particulate Matter 2.5 microns or less sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.PM25
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _multiplier = 1
    _attr_native_unit_of_measurement = CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    _attr_primary_weight = 1
    _cluster_id = PM25Cluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({PM25Cluster.cluster_id}),
    )

    _server_cluster_config = {
        PM25Cluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                PM25Cluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=0.1
                    ),
                ),
            },
        ),
    }


@register_entity(ElectricalConductivityCluster.cluster_id)
class ElectricalConductivity(Sensor):
    """Electrical Conductivity sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.CONDUCTIVITY
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfConductivity.MICROSIEMENS_PER_CM
    _cluster_id = ElectricalConductivityCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({ElectricalConductivityCluster.cluster_id}),
    )

    _server_cluster_config = {
        ElectricalConductivityCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                ElectricalConductivityCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(FormaldehydeConcentrationCluster.cluster_id)
class FormaldehydeConcentration(Sensor):
    """Formaldehyde Concentration sensor."""

    _attribute_name = "measured_value"
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key: str = "formaldehyde"
    _attr_suggested_display_precision = 0
    _multiplier = 1e6
    _attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
    _attr_primary_weight = 1
    _cluster_id = FormaldehydeConcentrationCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({FormaldehydeConcentrationCluster.cluster_id}),
    )

    _server_cluster_config = {
        FormaldehydeConcentrationCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                FormaldehydeConcentrationCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=0.000001
                    ),
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class ThermostatHVACAction(Sensor):
    """Thermostat HVAC action sensor."""

    _unique_id_suffix = "hvac_action"
    _attr_translation_key: str = "hvac_action"
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        feature_priority=(PlatformFeatureGroup.HVAC_ACTION, 0),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                Thermostat.AttributeDefs.local_temperature: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.occupied_cooling_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.occupied_heating_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.unoccupied_cooling_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.unoccupied_heating_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.running_mode: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.running_state: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.system_mode: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.occupancy: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.pi_cooling_demand: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=5
                    ),
                ),
                Thermostat.AttributeDefs.pi_heating_demand: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=5
                    ),
                ),
                Thermostat.AttributeDefs.abs_min_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.abs_max_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.abs_min_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.abs_max_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.ctrl_sequence_of_oper: AttrConfig(
                    read_on_startup=True,
                ),
                Thermostat.AttributeDefs.max_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.max_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.min_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.min_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.local_temperature_calibration: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.setpoint_change_source: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.setpoint_change_source_timestamp: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def _is_supported(self) -> bool:
        return PlatformEntity._is_supported(self)

    @property
    def _pi_heating_demand(self) -> int | None:
        return self._cluster.get(Thermostat.AttributeDefs.pi_heating_demand.name)

    @property
    def _pi_cooling_demand(self) -> int | None:
        return self._cluster.get(Thermostat.AttributeDefs.pi_cooling_demand.name)

    @property
    def _running_state(self) -> int | None:
        return self._cluster.get(Thermostat.AttributeDefs.running_state.name)

    @property
    def _running_mode(self) -> int | None:
        return self._cluster.get(Thermostat.AttributeDefs.running_mode.name)

    @property
    def _system_mode(self) -> int | None:
        return self._cluster.get(Thermostat.AttributeDefs.system_mode.name)

    @property
    def state(self) -> dict:
        """Return the current HVAC action."""
        response = super().state
        if self._pi_heating_demand is None and self._pi_cooling_demand is None:
            response["state"] = self._rm_rs_action
        else:
            response["state"] = self._pi_demand_action
        return response

    @property
    def native_value(self) -> str | None:
        """Return the current HVAC action."""
        if self._pi_heating_demand is None and self._pi_cooling_demand is None:
            return self._rm_rs_action
        return self._pi_demand_action

    @property
    def _rm_rs_action(self) -> HVACAction | None:
        """Return the current HVAC action based on running mode and running state."""

        if (running_state := self._running_state) is None:
            return None

        rs_heat = (
            Thermostat.RunningState.Heat_State_On
            | Thermostat.RunningState.Heat_2nd_Stage_On
        )
        if running_state & rs_heat:
            return HVACAction.HEATING

        rs_cool = (
            Thermostat.RunningState.Cool_State_On
            | Thermostat.RunningState.Cool_2nd_Stage_On
        )
        if running_state & rs_cool:
            return HVACAction.COOLING

        if running_state and running_state & (
            Thermostat.RunningState.Fan_State_On
            | Thermostat.RunningState.Fan_2nd_Stage_On
            | Thermostat.RunningState.Fan_3rd_Stage_On
        ):
            return HVACAction.FAN

        if running_state and running_state & Thermostat.RunningState.Idle:
            return HVACAction.IDLE

        if self._system_mode != Thermostat.SystemMode.Off:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def _pi_demand_action(self) -> HVACAction:
        """Return the current HVAC action based on pi_demands."""

        heating_demand = self._pi_heating_demand
        if heating_demand is not None and heating_demand > 0:
            return HVACAction.HEATING
        cooling_demand = self._pi_cooling_demand
        if cooling_demand is not None and cooling_demand > 0:
            return HVACAction.COOLING

        if self._system_mode != Thermostat.SystemMode.Off:
            return HVACAction.IDLE
        return HVACAction.OFF


@register_entity(Thermostat.cluster_id)
class SinopeHVACAction(ThermostatHVACAction):
    """Sinope Thermostat HVAC action sensor."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        manufacturers=frozenset({"Sinope Technologies"}),
        feature_priority=(PlatformFeatureGroup.HVAC_ACTION, 1),
    )

    @property
    def _rm_rs_action(self) -> HVACAction:
        """Return the current HVAC action based on running mode and running state."""

        running_mode = self._running_mode
        if running_mode == Thermostat.RunningMode.Heat:
            return HVACAction.HEATING
        if running_mode == Thermostat.RunningMode.Cool:
            return HVACAction.COOLING

        running_state = self._running_state
        if running_state and running_state & (
            Thermostat.RunningState.Fan_State_On
            | Thermostat.RunningState.Fan_2nd_Stage_On
            | Thermostat.RunningState.Fan_3rd_Stage_On
        ):
            return HVACAction.FAN
        if (
            self._system_mode != Thermostat.SystemMode.Off
            and running_mode == Thermostat.SystemMode.Off
        ):
            return HVACAction.IDLE
        return HVACAction.OFF


@register_entity(Basic.cluster_id)
class RSSISensor(Sensor):
    """RSSI sensor for a device."""

    # TODO: migrate this away from `PlatformEntity`
    _unique_id_suffix: str = "rssi"
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_device_class: SensorDeviceClass | None = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement: str | None = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key: str = "rssi"
    _cluster_id = Basic.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Basic.cluster_id}),
    )

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self.device.gateway.global_updater.register_update_listener(self.update)
        self._on_remove_callbacks.append(
            lambda: self.device.gateway.global_updater.remove_update_listener(
                self.update
            )
        )

    def _is_supported(self) -> bool:
        # This entity is not actually tied to an endpoint or cluster and will always be
        # supported
        return True

    def is_supported_in_list(self, entities: list[BaseEntity]) -> bool:
        """Check if the sensor is supported given the list of entities."""
        cls = type(self)
        return not any(type(entity) is cls for entity in entities if entity is not self)

    @property
    def state(self) -> dict:
        """Return the state of the sensor."""
        response = super().state
        response["state"] = self.device.device.rssi
        return response

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the entity."""
        return self._device.device.rssi

    def enable(self) -> None:
        """Enable the entity."""
        super().enable()
        self._device.gateway.global_updater.register_update_listener(self.update)

    def disable(self) -> None:
        """Disable the entity."""
        super().disable()
        self._device.gateway.global_updater.remove_update_listener(self.update)

    def update(self):
        """Call async_update at a constrained random interval."""
        if self._device.available and self._device.gateway.config.allow_polling:
            self.debug("polling for updated state")
            self.maybe_emit_state_changed_event()
        else:
            self.debug(
                "skipping polling for updated state, available: %s, allow polled requests: %s",
                self._device.available,
                self._device.gateway.config.allow_polling,
            )


@register_entity(Basic.cluster_id)
class LQISensor(RSSISensor):
    """LQI sensor for a device."""

    # TODO: migrate this away from `PlatformEntity`
    _unique_id_suffix: str = "lqi"
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_translation_key = "lqi"
    _cluster_id = Basic.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Basic.cluster_id}),
    )

    @property
    def state(self) -> dict:
        """Return the state of the sensor."""
        response = super().state
        response["state"] = self.device.device.lqi
        return response

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state of the entity."""
        return self._device.device.lqi


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class TimeLeft(Sensor):
    """Sensor that displays time left value."""

    _attribute_name = "timer_time_left"
    _unique_id_suffix = "time_left"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.DURATION
    _attr_translation_key: str = "timer_time_left"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _cluster_id = TUYA_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
        manufacturers=frozenset({"_TZE200_htnnfasr"}),
    )


@register_entity(IKEA_AIR_PURIFIER_CLUSTER)
class IkeaDeviceRunTime(Sensor):
    """Sensor that displays device run time (in minutes)."""

    _attribute_name = "device_run_time"
    _unique_id_suffix = "device_run_time"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.DURATION
    _attr_translation_key: str = "device_run_time"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _cluster_id = IKEA_AIR_PURIFIER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IKEA_AIR_PURIFIER_CLUSTER}),
    )


@register_entity(IKEA_AIR_PURIFIER_CLUSTER)
class IkeaFilterRunTime(Sensor):
    """Sensor that displays run time of the current filter (in minutes)."""

    _attribute_name = "filter_run_time"
    _unique_id_suffix = "filter_run_time"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.DURATION
    _attr_translation_key: str = "filter_run_time"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _cluster_id = IKEA_AIR_PURIFIER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IKEA_AIR_PURIFIER_CLUSTER}),
    )


class AqaraFeedingSource(types.enum8):
    """Aqara pet feeder feeding source."""

    Feeder = 0x01
    HomeAssistant = 0x02


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederLastFeedingSource(EnumSensor):
    """Sensor that displays the last feeding source of pet feeder."""

    _attribute_name = "last_feeding_source"
    _unique_id_suffix = "last_feeding_source"
    _attr_translation_key: str = "last_feeding_source"
    _enum = AqaraFeedingSource
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederLastFeedingSize(Sensor):
    """Sensor that displays the last feeding size of the pet feeder."""

    _attribute_name = "last_feeding_size"
    _unique_id_suffix = "last_feeding_size"
    _attr_translation_key: str = "last_feeding_size"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederPortionsDispensed(Sensor):
    """Sensor that displays the number of portions dispensed by the pet feeder."""

    _attribute_name = "portions_dispensed"
    _unique_id_suffix = "portions_dispensed"
    _attr_translation_key: str = "portions_dispensed_today"
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederWeightDispensed(Sensor):
    """Sensor that displays the weight dispensed by the pet feeder."""

    _attribute_name = "weight_dispensed"
    _unique_id_suffix = "weight_dispensed"
    _attr_translation_key: str = "weight_dispensed_today"
    _attr_native_unit_of_measurement = UnitOfMass.GRAMS
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraSmokeDensityDbm(Sensor):
    """Sensor that displays the smoke density of an Aqara smoke sensor in dB/m."""

    _attribute_name = "smoke_density_dbm"
    _unique_id_suffix = "smoke_density_dbm"
    _attr_translation_key: str = "smoke_density"
    _attr_native_unit_of_measurement = "dB/m"
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 3
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.sensor_smoke.acn03"}),
    )


class SonoffIlluminationStates(types.enum8):
    """Enum for displaying last Illumination state."""

    Dark = 0x00
    Light = 0x01


@register_entity(SONOFF_CLUSTER)
class SonoffPresenceSenorIlluminationStatus(EnumSensor):
    """Sensor that displays the illumination status the last time peresence was detected."""

    _attribute_name = "last_illumination_state"
    _unique_id_suffix = "last_illumination"
    _attr_translation_key: str = "last_illumination_state"
    _enum = SonoffIlluminationStates
    _cluster_id = SONOFF_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SONOFF_CLUSTER}),
        models=frozenset({"SNZB-06P"}),
    )


@register_entity(Thermostat.cluster_id)
class PiHeatingDemand(Sensor):
    """Sensor that displays the percentage of heating power demanded.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "pi_heating_demand"
    _attribute_name = "pi_heating_demand"
    _attr_translation_key: str = "pi_heating_demand"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _attr_suggested_display_precision = 0
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
    )


class SetpointChangeSourceEnum(types.enum8):
    """The source of the setpoint change."""

    Manual = 0x00
    Schedule = 0x01
    External = 0x02


@register_entity(Thermostat.cluster_id)
class SetpointChangeSource(EnumSensor):
    """Sensor that displays the source of the setpoint change.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "setpoint_change_source"
    _attribute_name = "setpoint_change_source"
    _attr_translation_key: str = "setpoint_change_source"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _enum = SetpointChangeSourceEnum
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
    )


@register_entity(Thermostat.cluster_id)
class SetpointChangeSourceTimestamp(TimestampSensor):
    """Sensor that displays the timestamp the setpoint change.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "setpoint_change_source_timestamp"
    _attribute_name = "setpoint_change_source_timestamp"
    _attr_translation_key: str = "setpoint_change_source_timestamp"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
    )

    def formatter(self, value: types.UTCTime) -> datetime:
        """Pass-through formatter."""
        return ZCL_EPOCH + timedelta(seconds=value)


@register_entity(WindowCovering.cluster_id)
class WindowCoveringTypeSensor(EnumSensor):
    """Sensor that displays the type of a cover device."""

    _attribute_name: str = WindowCovering.AttributeDefs.window_covering_type.name
    _enum = WindowCovering.WindowCoveringType
    _unique_id_suffix: str = "window_covering_type"
    _attr_translation_key: str = "window_covering_type"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = WindowCovering.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({WindowCovering.cluster_id}),
    )

    _server_cluster_config = {
        WindowCovering.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                WindowCovering.AttributeDefs.window_covering_type: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(Basic.cluster_id)
class AqaraCurtainMotorPowerSourceSensor(EnumSensor):
    """Sensor that displays the power source of the Aqara E1 curtain motor device."""

    _attribute_name: str = Basic.AttributeDefs.power_source.name
    _enum = Basic.PowerSource
    _unique_id_suffix: str = "power_source"
    _attr_translation_key: str = "power_source"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = Basic.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Basic.cluster_id}),
        models=frozenset({"lumi.curtain.agl001"}),
    )

    _server_cluster_config = {
        Basic.cluster_id: ClusterConfig(
            attributes={
                Basic.AttributeDefs.power_source: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


class AqaraE1HookState(types.enum8):
    """Aqara hook state."""

    Unlocked = 0x00
    Locked = 0x01
    Locking = 0x02
    Unlocking = 0x03


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraCurtainHookStateSensor(EnumSensor):
    """Representation of a ZHA curtain mode configuration entity."""

    _attribute_name = "hooks_state"
    _enum = AqaraE1HookState
    _unique_id_suffix = "hooks_state"
    _attr_translation_key: str = "hooks_state"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.curtain.agl001"}),
    )


class BitMapSensor(Sensor):
    """A sensor with only state attributes.

    The sensor value will be an aggregate of the state attributes.
    """

    _bitmap: types.bitmap8 | types.bitmap16

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this sensor."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._attr_extra_state_attribute_names: set[str] = {
            bit.name for bit in list(self._bitmap)
        }

    @property
    def state(self) -> dict[str, Any]:
        """Return the state for this sensor."""
        response = super().state
        response["state"] = self.native_value
        value = self._cluster.get(self._attribute_name)
        for bit in list(self._bitmap):
            if value is None:
                response[bit.name] = False
            else:
                response[bit.name] = bit in self._bitmap(value)
        return response

    def formatter(self, _value: int) -> str:
        """Summary of all attributes."""

        value = self._cluster.get(self._attribute_name)
        state_attr = {}

        for bit in list(self._bitmap):
            if value is None:
                state_attr[bit.name] = False
            else:
                state_attr[bit.name] = bit in self._bitmap(value)

        binary_state_attributes = [key for (key, elem) in state_attr.items() if elem]

        return "something" if binary_state_attributes else "nothing"


@register_entity(Thermostat.cluster_id)
class DanfossOpenWindowDetection(EnumSensor):
    """Danfoss proprietary attribute.

    Sensor that displays whether the TRV detects an open window using the temperature sensor.
    """

    _unique_id_suffix = "open_window_detection"
    _attribute_name = "open_window_detection"
    _attr_translation_key: str = "open_window_detected"
    _enum = danfoss_thermostat.DanfossOpenWindowDetectionEnum
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "open_window_detection": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossLoadEstimate(Sensor):
    """Danfoss proprietary attribute for communicating its estimate of the radiator load."""

    _unique_id_suffix = "load_estimate"
    _attribute_name = "load_estimate"
    _attr_translation_key: str = "load_estimate"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "load_estimate": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossAdaptationRunStatus(BitMapSensor):
    """Danfoss proprietary attribute for showing the status of the adaptation run."""

    _unique_id_suffix = "adaptation_run_status"
    _attribute_name = "adaptation_run_status"
    _attr_translation_key: str = "adaptation_run_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _bitmap = danfoss_thermostat.DanfossAdaptationRunStatusBitmap
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "adaptation_run_status": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossPreheatTime(Sensor):
    """Danfoss proprietary attribute for communicating the time when it starts pre-heating."""

    _unique_id_suffix = "preheat_time"
    _attribute_name = "preheat_time"
    _attr_translation_key: str = "preheat_time"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "preheat_time": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Diagnostic.cluster_id)
class DanfossSoftwareErrorCode(BitMapSensor):
    """Danfoss proprietary attribute for communicating the error code."""

    _unique_id_suffix = "sw_error_code"
    _attribute_name = "sw_error_code"
    _attr_translation_key: str = "software_error"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _bitmap = danfoss_thermostat.DanfossSoftwareErrorCodeBitmap
    _cluster_id = Diagnostic.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Diagnostic.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Diagnostic.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "sw_error_code": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Diagnostic.cluster_id)
class DanfossMotorStepCounter(Sensor):
    """Danfoss proprietary attribute for communicating the motor step counter."""

    _unique_id_suffix = "motor_step_counter"
    _attribute_name = "motor_step_counter"
    _attr_translation_key: str = "motor_stepcount"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = Diagnostic.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Diagnostic.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Diagnostic.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "motor_step_counter": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(WindSpeedCluster.cluster_id)
class WindSpeed(Sensor):
    """Wind Speed sensor."""

    _attribute_name = "measured_value"
    _attr_device_class: SensorDeviceClass = SensorDeviceClass.WIND_SPEED
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _divisor = 100
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND
    _attr_primary_weight = 2
    _cluster_id = WindSpeedCluster.cluster_id

    _server_cluster_config = {
        WindSpeedCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                WindSpeedCluster.AttributeDefs.measured_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=0.01
                    ),
                ),
            },
        ),
    }

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({WindSpeedCluster.cluster_id}),
    )
