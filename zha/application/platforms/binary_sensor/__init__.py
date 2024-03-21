"""Binary sensors on Zigbee Home Automation networks."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

from zigpy.quirks.v2 import BinarySensorMetadata

from zha.application import Platform
from zha.application.const import ATTR_DEVICE_CLASS, ENTITY_METADATA
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.platforms.binary_sensor.const import (
    IAS_ZONE_CLASS_MAPPING,
    BinarySensorDeviceClass,
)
from zha.application.platforms.helpers import validate_device_class
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ACCELEROMETER,
    CLUSTER_HANDLER_BINARY_INPUT,
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_HUE_OCCUPANCY,
    CLUSTER_HANDLER_OCCUPANCY,
    CLUSTER_HANDLER_ON_OFF,
    CLUSTER_HANDLER_ZONE,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint


STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.BINARY_SENSOR)
MULTI_MATCH = functools.partial(
    PLATFORM_ENTITIES.multipass_match, Platform.BINARY_SENSOR
)
CONFIG_DIAGNOSTIC_MATCH = functools.partial(
    PLATFORM_ENTITIES.config_diagnostic_match, Platform.BINARY_SENSOR
)
_LOGGER = logging.getLogger(__name__)


class BinarySensor(PlatformEntity):
    """ZHA BinarySensor."""

    _attr_device_class: BinarySensorDeviceClass | None
    _attribute_name: str
    PLATFORM: Platform = Platform.BINARY_SENSOR

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ) -> None:
        """Initialize the ZHA binary sensor."""
        self._cluster_handler = cluster_handlers[0]
        if ENTITY_METADATA in kwargs:
            self._init_from_quirks_metadata(kwargs[ENTITY_METADATA])
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._cluster_handler.on_event(
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )

    def _init_from_quirks_metadata(self, entity_metadata: BinarySensorMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        self._attribute_name = entity_metadata.attribute_name
        if entity_metadata.device_class is not None:
            self._attr_device_class = validate_device_class(
                BinarySensorDeviceClass,
                entity_metadata.device_class,
                Platform.BINARY_SENSOR.value,
                _LOGGER,
            )

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on based on the state machine."""
        raw_state = self._cluster_handler.cluster.get(self._attribute_name)
        if raw_state is None:
            return False
        return self.parse(raw_state)

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the class of this entity."""
        return self._attr_device_class

    def get_state(self) -> dict:
        """Return the state of the binary sensor."""
        response = super().get_state()
        response["state"] = self.is_on
        return response

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute updates from the cluster handler."""
        if self._attribute_name is None or self._attribute_name != event.name:
            return
        self._state = bool(event.value)
        self.maybe_send_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve on off state from the binary sensor."""
        await super().async_update()
        attribute = getattr(self._cluster_handler, "value_attribute", "on_off")
        attr_value = await self._cluster_handler.get_attribute_value(attribute)
        if attr_value is not None:
            self._state = attr_value
            self.maybe_send_state_changed_event()

    def to_json(self) -> dict:
        """Return a JSON representation of the binary sensor."""
        json = super().to_json()
        json["sensor_attribute"] = self._attribute_name
        if hasattr(self, ATTR_DEVICE_CLASS):
            json[ATTR_DEVICE_CLASS] = self._attr_device_class
        return json

    @staticmethod
    def parse(value: bool | int) -> bool:
        """Parse the raw attribute into a bool state."""
        return bool(value)


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ACCELEROMETER)
class Accelerometer(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "acceleration"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.MOVING
    _attr_translation_key: str = "accelerometer"


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_OCCUPANCY)
class Occupancy(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "occupancy"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OCCUPANCY


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_HUE_OCCUPANCY)
class HueOccupancy(Occupancy):
    """ZHA Hue occupancy."""

    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OCCUPANCY


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_ON_OFF)
class Opening(BinarySensor):
    """ZHA OnOff BinarySensor."""

    _attribute_name = "on_off"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.OPENING

    # pylint: disable=pointless-string-statement
    """TODO
    # Client/out cluster attributes aren't stored in the zigpy database, but are properly stored in the runtime cache.
    # We need to manually restore the last state from the sensor state to the runtime cache for now.

    def async_restore_last_state(self, last_state):
        #Restore previous state to zigpy cache.
        self._cluster_handler.cluster.update_attribute(
            OnOff.attributes_by_name[self._attribute_name].id,
            t.Bool.true if last_state.state == STATE_ON else t.Bool.false,
        )
    """


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_BINARY_INPUT)
class BinaryInput(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "present_value"
    _attr_translation_key: str = "binary_input"


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF,
    manufacturers="IKEA of Sweden",
    models=lambda model: isinstance(model, str)
    and model is not None
    and model.find("motion") != -1,
)
@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF,
    manufacturers="Philips",
    models={"SML001", "SML002"},
)
class Motion(Opening):
    """ZHA OnOff BinarySensor with motion device class."""

    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.MOTION


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_ZONE)
class IASZone(BinarySensor):
    """ZHA IAS BinarySensor."""

    _attribute_name = "zone_status"

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ) -> None:
        """Initialize the ZHA binary sensor."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._attr_device_class = self.device_class
        self._attr_translation_key = self.translation_key

    @property
    def translation_key(self) -> str | None:
        """Return the name of the sensor."""
        zone_type = self._cluster_handler.cluster.get("zone_type")
        if zone_type in IAS_ZONE_CLASS_MAPPING:
            return None
        return "ias_zone"

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return device class from component DEVICE_CLASSES."""
        zone_type = self._cluster_handler.cluster.get("zone_type")
        return IAS_ZONE_CLASS_MAPPING.get(zone_type)

    @staticmethod
    def parse(value: bool | int) -> bool:
        """Parse the raw attribute into a bool state."""
        return BinarySensor.parse(value & 3)  # use only bit 0 and 1 for alarm state


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_ZONE, models={"WL4200", "WL4200S"})
class SinopeLeakStatus(BinarySensor):
    """Sinope water leak sensor."""

    _attribute_name = "leak_status"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE


@MULTI_MATCH(
    cluster_handler_names="tuya_manufacturer",
    manufacturers={
        "_TZE200_htnnfasr",
    },
)
class FrostLock(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "frost_lock"
    _unique_id_suffix = "frost_lock"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.LOCK
    _attr_translation_key: str = "frost_lock"


@MULTI_MATCH(cluster_handler_names="ikea_airpurifier")
class ReplaceFilter(BinarySensor):
    """ZHA BinarySensor."""

    _attribute_name = "replace_filter"
    _unique_id_suffix = "replace_filter"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _attr_translation_key: str = "replace_filter"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"})
class AqaraPetFeederErrorDetected(BinarySensor):
    """ZHA aqara pet feeder error detected binary sensor."""

    _attribute_name = "error_detected"
    _unique_id_suffix = "error_detected"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PROBLEM


@MULTI_MATCH(
    cluster_handler_names="opple_cluster",
    models={"lumi.plug.mmeu01", "lumi.plug.maeu01"},
)
class XiaomiPlugConsumerConnected(BinarySensor):
    """ZHA Xiaomi plug consumer connected binary sensor."""

    _attribute_name = "consumer_connected"
    _unique_id_suffix = "consumer_connected"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PLUG
    _attr_translation_key: str = "consumer_connected"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"})
class AqaraThermostatWindowOpen(BinarySensor):
    """ZHA Aqara thermostat window open binary sensor."""

    _attribute_name = "window_open"
    _unique_id_suffix = "window_open"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.WINDOW


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"})
class AqaraThermostatValveAlarm(BinarySensor):
    """ZHA Aqara thermostat valve alarm binary sensor."""

    _attribute_name = "valve_alarm"
    _unique_id_suffix = "valve_alarm"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key: str = "valve_alarm"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"}
)
class AqaraThermostatCalibrated(BinarySensor):
    """ZHA Aqara thermostat calibrated binary sensor."""

    _attribute_name = "calibrated"
    _unique_id_suffix = "calibrated"
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _attr_translation_key: str = "calibrated"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"}
)
class AqaraThermostatExternalSensor(BinarySensor):
    """ZHA Aqara thermostat external sensor binary sensor."""

    _attribute_name = "sensor"
    _unique_id_suffix = "sensor"
    _attr_entity_category: EntityCategory = EntityCategory.DIAGNOSTIC
    _attr_translation_key: str = "external_sensor"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"})
class AqaraLinkageAlarmState(BinarySensor):
    """ZHA Aqara linkage alarm state binary sensor."""

    _attribute_name = "linkage_alarm_state"
    _unique_id_suffix = "linkage_alarm_state"
    _attr_device_class: BinarySensorDeviceClass = BinarySensorDeviceClass.SMOKE
    _attr_translation_key: str = "linkage_alarm_state"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.curtain.agl001"}
)
class AqaraE1CurtainMotorOpenedByHandBinarySensor(BinarySensor):
    """Opened by hand binary sensor."""

    _unique_id_suffix = "hand_open"
    _attribute_name = "hand_open"
    _attr_translation_key = "hand_open"
    _attr_icon = "mdi:hand-wave"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
