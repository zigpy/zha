"""Binary sensors on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from zigpy.profiles import zha, zll
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.general import BinaryInput as BinaryInputCluster, OnOff
from zigpy.zcl.clusters.hvac import Thermostat
from zigpy.zcl.clusters.measurement import OccupancySensing
from zigpy.zcl.clusters.security import IasZone

from zha.application import Platform
from zha.application.helpers import safe_read
from zha.application.platforms import (
    AttrConfig,
    BaseEntityState,
    ClusterConfig,
    ClusterMatch,
    EntityCategory,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)
from zha.application.platforms.binary_sensor.const import (
    IAS_ZONE_CLASS_MAPPING,
    BinarySensorDeviceClass,
)
from zha.application.platforms.const import (
    IKEA_AIR_PURIFIER_CLUSTER,
    SMARTTHINGS_ACCELERATION_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
)
from zha.application.platforms.helpers import validate_device_class
from zha.application.platforms.legacy_quirks import AQARA_OPPLE_CLUSTER
from zha.quirks import DANFOSS_ALLY_THERMOSTAT

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class BinarySensorState(BaseEntityState):
    """State for binary sensor entities."""

    is_on: bool
    attribute_name: str


class BaseBinarySensor(PlatformEntity, ABC):
    """Abstract base class for ZHA binary sensors."""

    PLATFORM: Platform = Platform.BINARY_SENSOR

    @property
    @abstractmethod
    def is_on(self) -> bool:
        """Return True if the binary sensor is on."""


class BinarySensor(BaseBinarySensor):
    """ZHA BinarySensor."""

    _attr_device_class: BinarySensorDeviceClass | None
    _attribute_name: str
    _attribute_converter: Callable[[Any], Any] | None = None

    @property
    def state(self) -> BinarySensorState:
        """Return the state of the binary sensor."""
        return BinarySensorState(
            **super().state.__dict__,
            is_on=self.is_on,
            attribute_name=self._attribute_name,
        )

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        attribute_name: str | None = None,
        attribute_converter: Callable[[Any], Any] | None = None,
        device_class: BinarySensorDeviceClass | None = None,
        **kwargs,
    ) -> None:
        """Initialize the ZHA binary sensor."""
        if attribute_name is not None:
            self._attribute_name = attribute_name
        if attribute_converter is not None:
            self._attribute_converter = attribute_converter
        if device_class is not None:
            self._attr_device_class = validate_device_class(
                BinarySensorDeviceClass,
                device_class,
                Platform.BINARY_SENSOR.value,
                _LOGGER,
            )

        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self.recompute_capabilities()

    def _is_supported(self) -> bool:
        if self._attribute_name not in self._cluster.attributes_by_name:
            return False
        return super()._is_supported()

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
    def is_on(self) -> bool:
        """Return True if the switch is on based on the state machine."""
        raw_state = self._cluster.get(self._attribute_name)
        if raw_state is None:
            return False
        if self._attribute_converter:
            return self._attribute_converter(raw_state)
        return self.parse(raw_state)

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle attribute updates from the cluster."""
        if self._attribute_name is None or self._attribute_name != event.attribute_name:
            return
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve on off state from the binary sensor."""
        self.debug("polling current state")
        attribute = self._attribute_name or "on_off"
        result = await safe_read(
            self._cluster,
            [attribute],
            allow_cache=False,
            only_cache=False,
        )
        attr_value = result.get(attribute)
        if attr_value is not None:
            self.maybe_emit_state_changed_event()

    @staticmethod
    def parse(value: bool | int) -> bool:
        """Parse the raw attribute into a bool state."""
        return bool(value)


@register_entity(SMARTTHINGS_ACCELERATION_CLUSTER)
class Accelerometer(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "acceleration"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.MOVING
    _attr_translation_key: str = "accelerometer"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SMARTTHINGS_ACCELERATION_CLUSTER}),
        manufacturers=frozenset({"CentraLite", "Samjin", "SmartThings"}),
    )

    _server_cluster_config = {
        SMARTTHINGS_ACCELERATION_CLUSTER: ClusterConfig(
            bind=True,
            attributes={
                "acceleration": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
                "x_axis": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
                "y_axis": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
                "z_axis": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(OccupancySensing.cluster_id)
class Occupancy(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "occupancy"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OCCUPANCY
    _attr_primary_weight = 2
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


@register_entity(OnOff.cluster_id)
class Opening(BinarySensor):
    """ZHA OnOff BinarySensor."""

    _attribute_name = "on_off"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OPENING
    _attr_primary_weight = 1

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({OnOff.cluster_id}),
        not_profile_device_types=frozenset(
            {
                (zha.PROFILE_ID, zha.DeviceType.COLOR_CONTROLLER),
                (zha.PROFILE_ID, zha.DeviceType.COLOR_DIMMER_SWITCH),
                (zha.PROFILE_ID, zha.DeviceType.COLOR_SCENE_CONTROLLER),
                (zha.PROFILE_ID, zha.DeviceType.DIMMER_SWITCH),
                (zha.PROFILE_ID, zha.DeviceType.LEVEL_CONTROL_SWITCH),
                (zha.PROFILE_ID, zha.DeviceType.NON_COLOR_CONTROLLER),
                (zha.PROFILE_ID, zha.DeviceType.NON_COLOR_SCENE_CONTROLLER),
                (zha.PROFILE_ID, zha.DeviceType.ON_OFF_SWITCH),
                (zha.PROFILE_ID, zha.DeviceType.ON_OFF_LIGHT_SWITCH),
                (zha.PROFILE_ID, zha.DeviceType.REMOTE_CONTROL),
                (zha.PROFILE_ID, zha.DeviceType.SCENE_SELECTOR),
                (zll.PROFILE_ID, zll.DeviceType.COLOR_CONTROLLER),
                (zll.PROFILE_ID, zll.DeviceType.COLOR_SCENE_CONTROLLER),
                (zll.PROFILE_ID, zll.DeviceType.CONTROL_BRIDGE),
                (zll.PROFILE_ID, zll.DeviceType.CONTROLLER),
                (zll.PROFILE_ID, zll.DeviceType.SCENE_CONTROLLER),
            }
        ),
        feature_priority=(PlatformFeatureGroup.BINARY_SENSOR, 0),
    )


@register_entity(BinaryInputCluster.cluster_id)
class BinaryInputWithDescription(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "present_value"
    _cluster_id = BinaryInputCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({BinaryInputCluster.cluster_id}),
    )

    _server_cluster_config = {
        BinaryInputCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                BinaryInputCluster.AttributeDefs.present_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                BinaryInputCluster.AttributeDefs.description: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        self._attr_fallback_name = self._cluster.get(
            BinaryInputCluster.AttributeDefs.description.name
        )

    def _is_supported(self) -> bool:
        if self._cluster.get(BinaryInputCluster.AttributeDefs.description.name) is None:
            return False

        return super()._is_supported()


@register_entity(BinaryInputCluster.cluster_id)
class BinaryInput(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "present_value"
    _attr_translation_key: str = "binary_input"
    _cluster_id = BinaryInputCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({BinaryInputCluster.cluster_id}),
    )

    _server_cluster_config = {
        BinaryInputCluster.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                BinaryInputCluster.AttributeDefs.present_value: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                BinaryInputCluster.AttributeDefs.description: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def _is_supported(self) -> bool:
        # Prefer to use the "WithDescription" variant above
        if (
            self._cluster.get(BinaryInputCluster.AttributeDefs.description.name)
            is not None
        ):
            return False

        return super()._is_supported()


@register_entity(OnOff.cluster_id)
class IkeaMotion(BinarySensor):
    """ZHA OnOff BinarySensor with motion device class for IKEA devices."""

    _attribute_name = "on_off"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.MOTION
    _attr_primary_weight = 1

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({OnOff.cluster_id}),
        manufacturers=frozenset({"IKEA of Sweden"}),
        models=frozenset({"TRADFRI motion sensor"}),
        feature_priority=(PlatformFeatureGroup.BINARY_SENSOR, 1),
    )


@register_entity(OnOff.cluster_id)
class PhilipsMotion(BinarySensor):
    """ZHA OnOff BinarySensor with motion device class for Philips devices."""

    _attribute_name = "on_off"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.MOTION
    _attr_primary_weight = 1

    _cluster_match = ClusterMatch(
        client_clusters=frozenset({OnOff.cluster_id}),
        manufacturers=frozenset({"Philips"}),
        models=frozenset({"SML001", "SML002"}),
        feature_priority=(PlatformFeatureGroup.BINARY_SENSOR, 1),
    )


@register_entity(IasZone.cluster_id)
class IASZone(BinarySensor):
    """ZHA IAS BinarySensor."""

    _attribute_name = "zone_status"
    _attr_primary_weight = 3
    _cluster_id = IasZone.cluster_id

    # TODO: split this sensor off into individual sensor classes per IASZone type

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasZone.cluster_id}),
    )

    _server_cluster_config = {
        IasZone.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                IasZone.AttributeDefs.zone_status: AttrConfig(
                    read_on_startup=True,
                ),
                IasZone.AttributeDefs.zone_state: AttrConfig(
                    read_on_startup=False,
                ),
                IasZone.AttributeDefs.zone_type: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        zone_type = self._cluster.get(IasZone.AttributeDefs.zone_type.name)

        if zone_type is None:
            self._attr_translation_key = "ias_zone"
            self._attr_device_class = None
        else:
            zone_type = IasZone.ZoneType(zone_type)
            self._attr_translation_key = (
                None if zone_type in IAS_ZONE_CLASS_MAPPING else "ias_zone"
            )
            self._attr_device_class = IAS_ZONE_CLASS_MAPPING.get(zone_type)

    @staticmethod
    def parse(value: bool | int) -> bool:
        """Parse the raw attribute into a bool state."""
        # use only bit 0 and 1 for alarm state
        return BinarySensor.parse(value & 0b00000011)

    async def async_update(self) -> None:
        """Attempt to retrieve on off state from the IAS Zone sensor."""
        self.debug("polling current state")
        await safe_read(
            self._cluster,
            [self._attribute_name],
            allow_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()


@register_entity(IasZone.cluster_id)
class SinopeLeakStatus(BinarySensor):
    """Sinope water leak sensor."""

    _attribute_name = "leak_status"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_primary_weight = 1
    _cluster_id = IasZone.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasZone.cluster_id}),
        models=frozenset({"WL4200", "WL4200S"}),
    )


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class FrostLock(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "frost_lock"
    _unique_id_suffix = "frost_lock"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.LOCK
    _attr_translation_key: str = "frost_lock"
    _cluster_id = TUYA_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
        manufacturers=frozenset({"_TZE200_htnnfasr"}),
    )


@register_entity(IKEA_AIR_PURIFIER_CLUSTER)
class ReplaceFilter(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "replace_filter"
    _unique_id_suffix = "replace_filter"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _attr_translation_key: str = "replace_filter"
    _cluster_id = IKEA_AIR_PURIFIER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IKEA_AIR_PURIFIER_CLUSTER}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederErrorDetected(BinarySensor):
    """ZHA aqara pet feeder error detected binary sensor."""

    _attribute_name = "error_detected"
    _unique_id_suffix = "error_detected"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PROBLEM
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class XiaomiPlugConsumerConnected(BinarySensor):
    """ZHA Xiaomi plug consumer connected binary sensor."""

    _attribute_name = "consumer_connected"
    _unique_id_suffix = "consumer_connected"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PLUG
    _attr_translation_key: str = "consumer_connected"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.plug.mmeu01", "lumi.plug.maeu01"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatWindowOpen(BinarySensor):
    """ZHA Aqara thermostat window open binary sensor."""

    _attribute_name = "window_open"
    _unique_id_suffix = "window_open"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.WINDOW
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatValveAlarm(BinarySensor):
    """ZHA Aqara thermostat valve alarm binary sensor."""

    _attribute_name = "valve_alarm"
    _unique_id_suffix = "valve_alarm"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key: str = "valve_alarm"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatCalibrated(BinarySensor):
    """ZHA Aqara thermostat calibrated binary sensor."""

    _attribute_name = "calibrated"
    _unique_id_suffix = "calibrated"
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _attr_translation_key: str = "calibrated"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatExternalSensor(BinarySensor):
    """ZHA Aqara thermostat external sensor binary sensor."""

    _attribute_name = "sensor"
    _unique_id_suffix = "sensor"
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _attr_translation_key: str = "external_sensor"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraLinkageAlarmState(BinarySensor):
    """ZHA Aqara linkage alarm state binary sensor."""

    _attribute_name = "linkage_alarm_state"
    _unique_id_suffix = "linkage_alarm_state"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.SMOKE
    _attr_translation_key: str = "linkage_alarm_state"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.sensor_smoke.acn03"}),
    )


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraE1CurtainMotorOpenedByHandBinarySensor(BinarySensor):
    """Opened by hand binary sensor."""

    _unique_id_suffix = "hand_open"
    _attribute_name = "hand_open"
    _attr_translation_key = "hand_open"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.curtain.agl001"}),
    )


@register_entity(Thermostat.cluster_id)
class DanfossMountingModeActive(BinarySensor):
    """Danfoss TRV proprietary attribute exposing whether in mounting mode."""

    _unique_id_suffix = "mounting_mode_active"
    _attribute_name = "mounting_mode_active"
    _attr_translation_key: str = "mounting_mode_active"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OPENING
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
                "mounting_mode_active": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossHeatRequired(BinarySensor):
    """Danfoss TRV proprietary attribute exposing whether heat is required."""

    _unique_id_suffix = "heat_required"
    _attribute_name = "heat_required"
    _attr_translation_key: str = "heat_required"
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "heat_required": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossPreheatStatus(BinarySensor):
    """Danfoss TRV proprietary attribute exposing whether in pre-heating mode."""

    _unique_id_suffix = "preheat_status"
    _attribute_name = "preheat_status"
    _attr_translation_key: str = "preheat_status"
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
                "preheat_status": AttrConfig(
                    read_on_startup=False,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
            },
        ),
    }
