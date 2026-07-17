"""Support for ZHA AnalogOutput cluster."""  # pylint: disable=too-many-lines

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import functools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.general import AnalogOutput, Basic, LevelControl
from zigpy.zcl.clusters.hvac import Thermostat
from zigpy.zcl.clusters.lighting import Ballast, Color
from zigpy.zcl.clusters.measurement import OccupancySensing

from zha.application import Platform
from zha.application.helpers import safe_read, write_attributes_safe
from zha.application.platforms import (
    AttrConfig,
    BaseEntityInfo,
    ClusterConfig,
    ClusterMatch,
    EntityCategory,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)
from zha.application.platforms.const import (
    IKEA_AIR_PURIFIER_CLUSTER,
    INOVELLI_CLUSTER,
    SINOPE_MANUFACTURER_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
)
from zha.application.platforms.helpers import validate_device_class
from zha.application.platforms.legacy_quirks import AQARA_OPPLE_CLUSTER
from zha.application.platforms.number.bacnet import BACNET_UNITS_TO_HA_UNITS
from zha.application.platforms.number.const import ICONS, NumberDeviceClass, NumberMode
from zha.quirks import DANFOSS_ALLY_THERMOSTAT
from zha.units import UnitOfMass, UnitOfTemperature, UnitOfTime

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class NumberEntityInfo(BaseEntityInfo):
    """Number entity info."""

    mode: NumberMode
    native_max_value: float
    native_min_value: float
    native_step: float | None
    native_unit_of_measurement: str | None


class BaseNumber(PlatformEntity, ABC):
    """Representation of a ZHA Number entity."""

    PLATFORM = Platform.NUMBER

    _attr_device_class: NumberDeviceClass | None = None

    _attr_mode: NumberMode = NumberMode.AUTO
    _attr_native_max_value: float
    _attr_native_min_value: float
    _attr_native_step: float | None = None
    _attr_native_value: float | None
    _attr_native_unit_of_measurement: str | None = None

    @property
    @abstractmethod
    def native_value(self) -> float | None:
        """Return the current value."""

    @functools.cached_property
    def info_object(self) -> NumberEntityInfo:
        """Return a representation of the number entity."""
        return NumberEntityInfo(
            **super().info_object.__dict__,
            mode=self.mode,
            native_max_value=self.native_max_value,
            native_min_value=self.native_min_value,
            native_step=self.native_step,
            native_unit_of_measurement=self.native_unit_of_measurement,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the entity."""
        response = super().state
        response["state"] = self.native_value
        return response

    @property
    def native_min_value(self) -> float:
        """Return the minimum value."""
        return self._attr_native_min_value

    @property
    def native_max_value(self) -> float:
        """Return the maximum value."""
        return self._attr_native_max_value

    @property
    def native_step(self) -> float | None:
        """Return the value step."""
        return self._attr_native_step

    @functools.cached_property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit the value is expressed in."""
        return self._attr_native_unit_of_measurement

    @functools.cached_property
    def mode(self) -> NumberMode:
        """Return the mode of the entity."""
        return self._attr_mode

    @abstractmethod
    async def async_set_native_value(self, value: float) -> None:
        """Update the current value from HA."""


@register_entity(AnalogOutput.cluster_id)
class AnalogOutputNumber(BaseNumber):
    """Representation of a ZHA Number entity."""

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AnalogOutput.cluster_id}),
    )

    _server_cluster_config = {
        AnalogOutput.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                AnalogOutput.AttributeDefs.present_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                AnalogOutput.AttributeDefs.min_present_value: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogOutput.AttributeDefs.max_present_value: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogOutput.AttributeDefs.resolution: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogOutput.AttributeDefs.relinquish_default: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogOutput.AttributeDefs.description: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogOutput.AttributeDefs.engineering_units: AttrConfig(
                    read_on_startup=False,
                ),
                AnalogOutput.AttributeDefs.application_type: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()

        min_val = self._cluster.get(AnalogOutput.AttributeDefs.min_present_value.name)
        max_val = self._cluster.get(AnalogOutput.AttributeDefs.max_present_value.name)
        self._attr_native_min_value = min_val or 0
        self._attr_native_max_value = max_val or 1023
        self._attr_native_step = self._cluster.get(
            AnalogOutput.AttributeDefs.resolution.name
        )
        self._attr_native_unit_of_measurement = BACNET_UNITS_TO_HA_UNITS.get(
            self._cluster.get(AnalogOutput.AttributeDefs.engineering_units.name)
        )

        application_type = self._cluster.get(
            AnalogOutput.AttributeDefs.application_type.name
        )
        if application_type is not None:
            self._attr_icon = ICONS.get(application_type >> 16)
        else:
            self._attr_icon = None

        self._attr_fallback_name = self._cluster.get(
            AnalogOutput.AttributeDefs.description.name
        )

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

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return self._cluster.get(AnalogOutput.AttributeDefs.present_value.name)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value from HA."""
        await write_attributes_safe(
            self._cluster,
            {AnalogOutput.AttributeDefs.present_value.name: float(value)},
        )
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Poll present_value from the cluster."""
        await safe_read(
            self._cluster,
            [AnalogOutput.AttributeDefs.present_value.name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle value update from cluster."""
        self.maybe_emit_state_changed_event()


class NumberConfigurationEntity(BaseNumber):
    """Representation of a ZHA number configuration entity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0.0
    _attr_native_max_value: float = 100.0
    _attr_native_step: float = 1.0
    _multiplier: float = 1
    _attribute_name: str

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        attribute_name: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        step: float | None = None,
        multiplier: float | None = None,
        device_class: NumberDeviceClass | None = None,
        unit: str | None = None,
        mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Init this number configuration entity."""
        if attribute_name is not None:
            self._attribute_name = attribute_name
        if min_value is not None:
            self._attr_native_min_value = min_value
        if max_value is not None:
            self._attr_native_max_value = max_value
        if step is not None:
            self._attr_native_step = step
        if multiplier is not None:
            self._multiplier = multiplier
        if device_class is not None:
            self._attr_device_class = validate_device_class(
                NumberDeviceClass,
                device_class,
                Platform.NUMBER.value,
                _LOGGER,
            )
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if mode is not None and mode in NumberMode:
            self._attr_mode = NumberMode(mode)

        super().__init__(endpoint=endpoint, device=device, **kwargs)

    def _is_supported(self) -> bool:
        """Return if the entity is supported for the device, internal."""
        if (
            self._attribute_name not in self._cluster.attributes_by_name
            or self._cluster.is_attribute_unsupported(self._attribute_name)
            or self._cluster.get(self._attribute_name) is None
        ):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                self._attribute_name,
                self.__class__.__name__,
            )
            return False

        return super()._is_supported()

    def on_add(self) -> None:
        """Initialize entity."""
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

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the entity."""
        response = super().state
        response["state"] = self.native_value
        return response

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self._cluster.get(self._attribute_name)
        if value is None:
            return None
        return value * self._multiplier

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value from HA."""
        await write_attributes_safe(
            self._cluster, {self._attribute_name: int(value / self._multiplier)}
        )
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve the state of the entity."""
        _LOGGER.debug("polling current state")
        result = await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        _LOGGER.debug("read value=%s", result.get(self._attribute_name))
        self.maybe_emit_state_changed_event()

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle value update from cluster."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMotionDetectionInterval(NumberConfigurationEntity):
    """Representation of a ZHA motion detection interval configuration entity."""

    _unique_id_suffix = "detection_interval"
    _attr_native_min_value: float = 2
    _attr_native_max_value: float = 65535
    _attribute_name = "detection_interval"
    _attr_translation_key: str = "detection_interval"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac02", "lumi.motion.agl04"}),
    )


@register_entity(LevelControl.cluster_id)
class OnOffTransitionTimeConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA on off transition time configuration entity."""

    _unique_id_suffix = "on_off_transition_time"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFF
    _attribute_name = "on_off_transition_time"
    _attr_translation_key: str = "on_off_transition_time"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
    )

    _server_cluster_config = {
        LevelControl.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                LevelControl.AttributeDefs.current_level: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
                LevelControl.AttributeDefs.on_off_transition_time: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.on_level: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.on_transition_time: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.off_transition_time: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.default_move_rate: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.start_up_current_level: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(LevelControl.cluster_id)
class OnLevelConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA on level configuration entity."""

    _unique_id_suffix = "on_level"
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFF
    _attribute_name = "on_level"
    _attr_translation_key: str = "on_level"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
    )


@register_entity(LevelControl.cluster_id)
class OnTransitionTimeConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA on transition time configuration entity."""

    _unique_id_suffix = "on_transition_time"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFE
    _attribute_name = "on_transition_time"
    _attr_translation_key: str = "on_transition_time"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
    )


@register_entity(LevelControl.cluster_id)
class OffTransitionTimeConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA off transition time configuration entity."""

    _unique_id_suffix = "off_transition_time"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFE
    _attribute_name = "off_transition_time"
    _attr_translation_key: str = "off_transition_time"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
    )


@register_entity(LevelControl.cluster_id)
class DefaultMoveRateConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA default move rate configuration entity."""

    _unique_id_suffix = "default_move_rate"
    _attr_entity_registry_enabled_default = False
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFE
    _attribute_name = "default_move_rate"
    _attr_translation_key: str = "default_move_rate"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
    )


@register_entity(LevelControl.cluster_id)
class StartUpCurrentLevelConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA startup current level configuration entity."""

    _unique_id_suffix = "start_up_current_level"
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFF
    _attribute_name = "start_up_current_level"
    _attr_translation_key: str = "start_up_current_level"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
    )


@register_entity(Color.cluster_id)
class StartUpColorTemperatureConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA startup color temperature configuration entity."""

    _unique_id_suffix = "start_up_color_temperature"
    _attr_native_min_value: float = 153
    _attr_native_max_value: float = 500
    _attribute_name = "start_up_color_temperature"
    _attr_translation_key: str = "start_up_color_temperature"
    _cluster_id = Color.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Color.cluster_id}),
    )

    _server_cluster_config = {
        Color.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                Color.AttributeDefs.current_x: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Color.AttributeDefs.current_y: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Color.AttributeDefs.color_temperature: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Color.AttributeDefs.color_mode: AttrConfig(
                    read_on_startup=True,
                ),
                Color.AttributeDefs.color_temp_physical_min: AttrConfig(
                    read_on_startup=False,
                ),
                Color.AttributeDefs.color_temp_physical_max: AttrConfig(
                    read_on_startup=False,
                ),
                Color.AttributeDefs.color_capabilities: AttrConfig(
                    read_on_startup=False,
                ),
                Color.AttributeDefs.color_loop_active: AttrConfig(
                    read_on_startup=True,
                ),
                Color.AttributeDefs.start_up_color_temperature: AttrConfig(
                    read_on_startup=False,
                ),
                Color.AttributeDefs.options: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        min_mireds = self._cluster.get(
            Color.AttributeDefs.color_temp_physical_min.name, 153
        )
        if min_mireds == 0:
            min_mireds = 153
        max_mireds = self._cluster.get(
            Color.AttributeDefs.color_temp_physical_max.name, 500
        )
        if max_mireds == 0:
            max_mireds = 500
        self._attr_native_min_value = min_mireds
        self._attr_native_max_value = max_mireds


@register_entity(Ballast.cluster_id)
class BallastMinLevel(NumberConfigurationEntity):
    """Ballast minimum level configuration entity."""

    _unique_id_suffix = "ballast_min_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0x01
    _attr_native_max_value: float = 0xFE
    _attribute_name = "min_level"
    _attr_translation_key: str = "minimum_dimming_level"
    _cluster_id = Ballast.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Ballast.cluster_id}),
    )

    _server_cluster_config = {
        Ballast.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                Ballast.AttributeDefs.min_level: AttrConfig(
                    read_on_startup=True,
                ),
                Ballast.AttributeDefs.max_level: AttrConfig(
                    read_on_startup=True,
                ),
            },
        ),
    }


@register_entity(Ballast.cluster_id)
class BallastMaxLevel(NumberConfigurationEntity):
    """Ballast maximum level configuration entity."""

    _unique_id_suffix = "ballast_max_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0x01
    _attr_native_max_value: float = 0xFE
    _attribute_name = "max_level"
    _attr_translation_key: str = "maximum_dimming_level"
    _cluster_id = Ballast.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Ballast.cluster_id}),
    )


@register_entity(OccupancySensing.cluster_id)
class PIROccupiedToUnoccupiedDelayConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA PIR occupied to unoccupied delay configuration entity."""

    _unique_id_suffix = "pir_o_to_u_delay"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFF
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement: str = UnitOfTime.SECONDS
    _attribute_name = "pir_o_to_u_delay"
    _attr_translation_key: str = "pir_o_to_u_delay"
    _cluster_id = OccupancySensing.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OccupancySensing.cluster_id}),
    )

    _server_cluster_config = {
        OccupancySensing.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                OccupancySensing.AttributeDefs.occupancy: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                OccupancySensing.AttributeDefs.pir_o_to_u_delay: AttrConfig(
                    read_on_startup=False,
                ),
                OccupancySensing.AttributeDefs.pir_u_to_o_delay: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(OccupancySensing.cluster_id)
class PIRUnoccupiedToOccupiedDelayConfigurationEntity(NumberConfigurationEntity):
    """Representation of a ZHA PIR unoccupied to occupied delay configuration entity."""

    _unique_id_suffix = "pir_u_to_o_delay"
    _attr_native_min_value: float = 0x0000
    _attr_native_max_value: float = 0xFFFF
    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement: str = UnitOfTime.SECONDS
    _attribute_name = "pir_u_to_o_delay"
    _attr_translation_key: str = "pir_u_to_o_delay"
    _cluster_id = OccupancySensing.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OccupancySensing.cluster_id}),
    )


@register_entity(OccupancySensing.cluster_id)
class SonoffPresenceSenorTimeout(NumberConfigurationEntity):
    """Configuration of Sonoff sensor presence detection timeout."""

    _unique_id_suffix = "presence_detection_timeout"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: int = 15
    _attr_native_max_value: int = 60
    _attribute_name = "ultrasonic_o_to_u_delay"
    _attr_translation_key: str = "presence_detection_timeout"
    _cluster_id = OccupancySensing.cluster_id

    _attr_mode: NumberMode = NumberMode.BOX

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OccupancySensing.cluster_id}),
        models=frozenset({"SNZB-06P", "SNZB-03P"}),
    )

    _server_cluster_config = {
        OccupancySensing.cluster_id: ClusterConfig(
            attributes={
                OccupancySensing.AttributeDefs.ultrasonic_o_to_u_delay: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class TimerDurationMinutes(NumberConfigurationEntity):
    """Representation of a ZHA timer duration configuration entity."""

    _unique_id_suffix = "timer_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0x257
    _attr_native_unit_of_measurement: str = UnitOfTime.MINUTES
    _attribute_name = "timer_duration"
    _attr_translation_key: str = "timer_duration"
    _cluster_id = TUYA_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
        manufacturers=frozenset({"_TZE200_htnnfasr"}),
    )


@register_entity(IKEA_AIR_PURIFIER_CLUSTER)
class FilterLifeTime(NumberConfigurationEntity):
    """Representation of a ZHA filter lifetime configuration entity."""

    _unique_id_suffix = "filter_life_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0x00
    _attr_native_max_value: float = 0xFFFFFFFF
    _attr_native_unit_of_measurement: str = UnitOfTime.MINUTES
    _attribute_name = "filter_life_time"
    _attr_translation_key: str = "filter_life_time"
    _cluster_id = IKEA_AIR_PURIFIER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IKEA_AIR_PURIFIER_CLUSTER}),
    )


@register_entity(Basic.cluster_id)
class TiRouterTransmitPower(NumberConfigurationEntity):
    """Representation of a ZHA TI transmit power configuration entity."""

    _unique_id_suffix = "transmit_power"
    _attr_native_min_value: float = -20
    _attr_native_max_value: float = 20
    _attribute_name = "transmit_power"
    _attr_translation_key: str = "transmit_power"
    _cluster_id = Basic.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Basic.cluster_id}),
        manufacturers=frozenset({"TexasInstruments"}),
        models=frozenset({"ti.router"}),
    )

    _server_cluster_config = {
        Basic.cluster_id: ClusterConfig(
            bind=False,
            attributes={
                "transmit_power": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(INOVELLI_CLUSTER)
class InovelliRemoteDimmingUpSpeed(NumberConfigurationEntity):
    """Inovelli remote dimming up speed configuration entity."""

    _unique_id_suffix = "dimming_speed_up_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 126
    _attribute_name = "dimming_speed_up_remote"
    _attr_translation_key: str = "dimming_speed_up_remote"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliButtonDelay(NumberConfigurationEntity):
    """Inovelli button delay configuration entity."""

    _unique_id_suffix = "button_delay"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 9
    _attribute_name = "button_delay"
    _attr_translation_key: str = "button_delay"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliLocalDimmingUpSpeed(NumberConfigurationEntity):
    """Inovelli local dimming up speed configuration entity."""

    _unique_id_suffix = "dimming_speed_up_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "dimming_speed_up_local"
    _attr_translation_key: str = "dimming_speed_up_local"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliLocalRampRateOffToOn(NumberConfigurationEntity):
    """Inovelli off to on local ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_off_to_on_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_off_to_on_local"
    _attr_translation_key: str = "ramp_rate_off_to_on_local"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliRemoteDimmingSpeedOffToOn(NumberConfigurationEntity):
    """Inovelli off to on remote ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_off_to_on_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_off_to_on_remote"
    _attr_translation_key: str = "ramp_rate_off_to_on_remote"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliRemoteDimmingDownSpeed(NumberConfigurationEntity):
    """Inovelli remote dimming down speed configuration entity."""

    _unique_id_suffix = "dimming_speed_down_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "dimming_speed_down_remote"
    _attr_translation_key: str = "dimming_speed_down_remote"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliLocalDimmingDownSpeed(NumberConfigurationEntity):
    """Inovelli local dimming down speed configuration entity."""

    _unique_id_suffix = "dimming_speed_down_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "dimming_speed_down_local"
    _attr_translation_key: str = "dimming_speed_down_local"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliLocalRampRateOnToOff(NumberConfigurationEntity):
    """Inovelli local on to off ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_on_to_off_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_on_to_off_local"
    _attr_translation_key: str = "ramp_rate_on_to_off_local"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliRemoteDimmingSpeedOnToOff(NumberConfigurationEntity):
    """Inovelli remote on to off ramp rate configuration entity."""

    _unique_id_suffix = "ramp_rate_on_to_off_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 127
    _attribute_name = "ramp_rate_on_to_off_remote"
    _attr_translation_key: str = "ramp_rate_on_to_off_remote"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliMinimumLoadDimmingLevel(NumberConfigurationEntity):
    """Inovelli minimum load dimming level configuration entity."""

    _unique_id_suffix = "minimum_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 254
    _attribute_name = "minimum_level"
    _attr_translation_key: str = "minimum_level"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliMaximumLoadDimmingLevel(NumberConfigurationEntity):
    """Inovelli maximum load dimming level configuration entity."""

    _unique_id_suffix = "maximum_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 2
    _attr_native_max_value: float = 255
    _attribute_name = "maximum_level"
    _attr_translation_key: str = "maximum_level"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliAutoShutoffTimer(NumberConfigurationEntity):
    """Inovelli automatic switch shutoff timer configuration entity."""

    _unique_id_suffix = "auto_off_timer"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 32767
    _attribute_name = "auto_off_timer"
    _attr_translation_key: str = "auto_off_timer"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliLocalDefaultLevel(NumberConfigurationEntity):
    """Inovelli local default dimming/fan level configuration entity."""

    _unique_id_suffix = "default_level_local"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "default_level_local"
    _attr_translation_key: str = "default_level_local"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliRemoteDefaultLevel(NumberConfigurationEntity):
    """Inovelli remote default dimming/fan level configuration entity."""

    _unique_id_suffix = "default_level_remote"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "default_level_remote"
    _attr_translation_key: str = "default_level_remote"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliStartupDefaultLevel(NumberConfigurationEntity):
    """Inovelli start-up default dimming/fan level configuration entity."""

    _unique_id_suffix = "state_after_power_restored"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "state_after_power_restored"
    _attr_translation_key: str = "state_after_power_restored"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliQuickStartTime(NumberConfigurationEntity):
    """Inovelli fan quick start time configuration entity."""

    _unique_id_suffix = "quick_start_time"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 10
    _attribute_name = "quick_start_time"
    _attr_translation_key: str = "quick_start_time"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM35-SN"}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliLoadLevelIndicatorTimeout(NumberConfigurationEntity):
    """Inovelli load level indicator timeout configuration entity."""

    _unique_id_suffix = "load_level_indicator_timeout"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 11
    _attribute_name = "load_level_indicator_timeout"
    _attr_translation_key: str = "load_level_indicator_timeout"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliDefaultAllLEDOnColor(NumberConfigurationEntity):
    """Inovelli default all led color when on configuration entity."""

    _unique_id_suffix = "led_color_when_on"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "led_color_when_on"
    _attr_translation_key: str = "led_color_when_on"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliDefaultAllLEDOffColor(NumberConfigurationEntity):
    """Inovelli default all led color when off configuration entity."""

    _unique_id_suffix = "led_color_when_off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 255
    _attribute_name = "led_color_when_off"
    _attr_translation_key: str = "led_color_when_off"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliDefaultAllLEDOnIntensity(NumberConfigurationEntity):
    """Inovelli default all led intensity when on configuration entity."""

    _unique_id_suffix = "led_intensity_when_on"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 100
    _attribute_name = "led_intensity_when_on"
    _attr_translation_key: str = "led_intensity_when_on"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliDefaultAllLEDOffIntensity(NumberConfigurationEntity):
    """Inovelli default all led intensity when off configuration entity."""

    _unique_id_suffix = "led_intensity_when_off"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 100
    _attribute_name = "led_intensity_when_off"
    _attr_translation_key: str = "led_intensity_when_off"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliDoubleTapUpLevel(NumberConfigurationEntity):
    """Inovelli double tap up level configuration entity."""

    _unique_id_suffix = "double_tap_up_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 2
    _attr_native_max_value: float = 254
    _attribute_name = "double_tap_up_level"
    _attr_translation_key: str = "double_tap_up_level"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(INOVELLI_CLUSTER)
class InovelliDoubleTapDownLevel(NumberConfigurationEntity):
    """Inovelli double tap down level configuration entity."""

    _unique_id_suffix = "double_tap_down_level"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 0
    _attr_native_max_value: float = 254
    _attribute_name = "double_tap_down_level"
    _attr_translation_key: str = "double_tap_down_level"

    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederServingSize(NumberConfigurationEntity):
    """Aqara pet feeder serving size configuration entity."""

    _unique_id_suffix = "serving_size"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 10
    _attribute_name = "serving_size"
    _attr_translation_key: str = "serving_size"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _attr_mode: NumberMode = NumberMode.BOX

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederPortionWeight(NumberConfigurationEntity):
    """Aqara pet feeder portion weight configuration entity."""

    _unique_id_suffix = "portion_weight"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 100
    _attribute_name = "portion_weight"
    _attr_translation_key: str = "portion_weight"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_unit_of_measurement: str = UnitOfMass.GRAMS

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatAwayTemp(NumberConfigurationEntity):
    """Aqara away preset temperature configuration entity."""

    _unique_id_suffix = "away_preset_temperature"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 5
    _attr_native_max_value: float = 30
    _multiplier: float = 0.01
    _attribute_name = "away_preset_temperature"
    _attr_translation_key: str = "away_preset_temperature"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _attr_mode: NumberMode = NumberMode.SLIDER
    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )


@register_entity(Thermostat.cluster_id)
class ThermostatLocalTempCalibration(NumberConfigurationEntity):
    """Local temperature calibration."""

    _unique_id_suffix = "local_temperature_calibration"
    _attr_native_min_value: float = -2.5
    _attr_native_max_value: float = 2.5
    _attr_native_step: float = 0.1
    _multiplier: float = 0.1
    _attribute_name = "local_temperature_calibration"
    _attr_translation_key: str = "local_temperature_calibration"
    _cluster_id = Thermostat.cluster_id

    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        feature_priority=(PlatformFeatureGroup.LOCAL_TEMPERATURE_CALIBRATION, 0),
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


@register_entity(Thermostat.cluster_id)
class SonoffThermostatLocalTempCalibration(ThermostatLocalTempCalibration):
    """Local temperature calibration for the Sonoff TRVZB."""

    _attr_native_min_value: float = -12.8
    _attr_native_max_value: float = 12.7
    _attr_native_step: float = 0.1

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        models=frozenset({"TRVZB"}),
        feature_priority=(PlatformFeatureGroup.LOCAL_TEMPERATURE_CALIBRATION, 1),
    )


@register_entity(Thermostat.cluster_id)
class BoschThermostatLocalTempCalibration(ThermostatLocalTempCalibration):
    """Local temperature calibration for the Bosch TRV/RTH."""

    _attr_native_min_value: float = -5.0
    _attr_native_max_value: float = 5.0
    _attr_native_step: float = 0.1

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        models=frozenset(
            {
                "RBSH-RTH0-ZB-EU",
                "RBSH-TRV0-ZB-EU",
                "RBSH-TRV1-ZB-EU",
                "RBSH-RTH0-BAT-ZB-EU",
            }
        ),
        feature_priority=(PlatformFeatureGroup.LOCAL_TEMPERATURE_CALIBRATION, 1),
    )


class ZCLTemperatureEntity(NumberConfigurationEntity):
    """Common entity class for ZCL temperature input."""

    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS
    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_step: float = 0.01
    _multiplier: float = 0.01


class ZCLHeatSetpointLimitEntity(ZCLTemperatureEntity):
    """Min or max heat setpoint setting on thermostats."""

    _attr_native_step: float = 0.5

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        self._attr_native_min_value = (
            self._cluster.get(
                Thermostat.AttributeDefs.abs_min_heat_setpoint_limit.name, -27315
            )
            * self._multiplier
        )
        self._attr_native_max_value = (
            self._cluster.get(
                Thermostat.AttributeDefs.abs_max_heat_setpoint_limit.name, 0x7FFF
            )
            * self._multiplier
        )


@register_entity(Thermostat.cluster_id)
class MaxHeatSetpointLimit(ZCLHeatSetpointLimitEntity):
    """Max heat setpoint setting on thermostats.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "max_heat_setpoint_limit"
    _attribute_name: str = "max_heat_setpoint_limit"
    _attr_translation_key: str = "max_heat_setpoint_limit"
    _attr_entity_category = EntityCategory.CONFIG
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
    )

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        self._attr_native_min_value = (
            self._cluster.get(
                Thermostat.AttributeDefs.min_heat_setpoint_limit.name, -27315
            )
            * self._multiplier
        )


@register_entity(Thermostat.cluster_id)
class MinHeatSetpointLimit(ZCLHeatSetpointLimitEntity):
    """Min heat setpoint setting on thermostats.

    Optional thermostat attribute.
    """

    _unique_id_suffix = "min_heat_setpoint_limit"
    _attribute_name: str = "min_heat_setpoint_limit"
    _attr_translation_key: str = "min_heat_setpoint_limit"
    _attr_entity_category = EntityCategory.CONFIG
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
    )

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        self._attr_native_max_value = (
            self._cluster.get(
                Thermostat.AttributeDefs.max_heat_setpoint_limit.name, 0x7FFF
            )
            * self._multiplier
        )


@register_entity(Thermostat.cluster_id)
class DanfossExerciseTriggerTime(NumberConfigurationEntity):
    """Danfoss proprietary attribute to set the time to exercise the valve."""

    _unique_id_suffix = "exercise_trigger_time"
    _attribute_name: str = "exercise_trigger_time"
    _attr_translation_key: str = "exercise_trigger_time"
    _attr_native_min_value: int = 0
    _attr_native_max_value: int = 1439
    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_unit_of_measurement: str = UnitOfTime.MINUTES
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            attributes={"exercise_trigger_time": AttrConfig(read_on_startup=False)},
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossExternalMeasuredRoomSensor(ZCLTemperatureEntity):
    """Danfoss proprietary attribute to communicate the value of the external temperature sensor."""

    _unique_id_suffix = "external_measured_room_sensor"
    _attribute_name: str = "external_measured_room_sensor"
    _attr_translation_key: str = "external_temperature_sensor"
    _attr_native_min_value: float = -80
    _attr_native_max_value: float = 35
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            attributes={
                "external_measured_room_sensor": AttrConfig(read_on_startup=True)
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossLoadRoomMean(NumberConfigurationEntity):
    """Danfoss proprietary attribute to set a value for the load."""

    _unique_id_suffix = "load_room_mean"
    _attribute_name: str = "load_room_mean"
    _attr_translation_key: str = "load_room_mean"
    _attr_native_min_value: int = -8000
    _attr_native_max_value: int = 2000
    _attr_mode: NumberMode = NumberMode.BOX
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            attributes={"load_room_mean": AttrConfig(read_on_startup=True)},
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossRegulationSetpointOffset(NumberConfigurationEntity):
    """Danfoss proprietary attribute to set the regulation setpoint offset."""

    _unique_id_suffix = "regulation_setpoint_offset"
    _attribute_name: str = "regulation_setpoint_offset"
    _attr_translation_key: str = "regulation_setpoint_offset"
    _attr_mode: NumberMode = NumberMode.BOX
    _attr_native_unit_of_measurement: str = UnitOfTemperature.CELSIUS
    _attr_native_min_value: float = -2.5
    _attr_native_max_value: float = 2.5
    _attr_native_step: float = 0.1
    _multiplier = 1 / 10
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            attributes={
                "regulation_setpoint_offset": AttrConfig(read_on_startup=False)
            },
        ),
    }


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeDimmerOnLevelConfigurationEntity(NumberConfigurationEntity):
    """Representation of a Sinope dimmer switch on level."""

    _unique_id_suffix = "on_intensity"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 255
    _attribute_name = "on_intensity"
    _attr_translation_key: str = "on_level"
    _cluster_id = SINOPE_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=frozenset({"DM2500ZB", "DM2500ZB-G2", "DM2550ZB", "DM2550ZB-G2"}),
    )


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeLightLEDOnIntensityConfigurationEntity(NumberConfigurationEntity):
    """Representation of a Sinope switch LED on-level brightness."""

    _unique_id_suffix = "on_led_intensity"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 100
    _attribute_name = "on_led_intensity"
    _attr_translation_key: str = "on_led_intensity"
    _cluster_id = SINOPE_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=frozenset(
            {
                "DM2500ZB",
                "DM2500ZB-G2",
                "DM2550ZB",
                "DM2550ZB-G2",
                "SW2500ZB",
                "SW2500ZB-G2",
            }
        ),
    )


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeLightLEDOffIntensityConfigurationEntity(NumberConfigurationEntity):
    """Representation of a Sinope switch LED off-level brightness."""

    _unique_id_suffix = "off_led_intensity"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value: float = 1
    _attr_native_max_value: float = 100
    _attribute_name = "off_led_intensity"
    _attr_translation_key: str = "off_led_intensity"
    _cluster_id = SINOPE_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=frozenset(
            {
                "DM2500ZB",
                "DM2500ZB-G2",
                "DM2550ZB",
                "DM2550ZB-G2",
                "SW2500ZB",
                "SW2500ZB-G2",
            }
        ),
    )
