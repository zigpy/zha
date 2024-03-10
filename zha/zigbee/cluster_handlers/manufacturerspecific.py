"""Manufacturer specific cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from zhaquirks.inovelli.types import AllLEDEffectType, SingleLEDEffectType
from zhaquirks.quirk_ids import TUYA_PLUG_MANUFACTURER, XIAOMI_AQARA_VIBRATION_AQ1
import zigpy.zcl
from zigpy.zcl.clusters.closures import DoorLock

from .. import registries
from ..const import (
    ATTR_ATTRIBUTE_ID,
    ATTR_ATTRIBUTE_NAME,
    ATTR_VALUE,
    REPORT_CONFIG_ASAP,
    REPORT_CONFIG_DEFAULT,
    REPORT_CONFIG_IMMEDIATE,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_MIN_INT,
    SIGNAL_ATTR_UPDATED,
    UNKNOWN,
)
from . import AttrReportConfig, ClientClusterHandler, ClusterHandler
from .general import MultistateInputClusterHandler

if TYPE_CHECKING:
    from ..endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)


@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(
    registries.SMARTTHINGS_HUMIDITY_CLUSTER
)
class SmartThingsHumidityClusterHandler(ClusterHandler):
    """Smart Things Humidity cluster handler."""

    REPORT_CONFIG = (
        {
            "attr": "measured_value",
            "config": (REPORT_CONFIG_MIN_INT, REPORT_CONFIG_MAX_INT, 50),
        },
    )


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(0xFD00)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(0xFD00)
class OsramButtonClusterHandler(ClusterHandler):
    """Osram button cluster handler."""

    REPORT_CONFIG = ()


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(registries.PHILLIPS_REMOTE_CLUSTER)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(registries.PHILLIPS_REMOTE_CLUSTER)
class PhillipsRemoteClusterHandler(ClusterHandler):
    """Phillips remote cluster handler."""

    REPORT_CONFIG = ()


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(registries.TUYA_MANUFACTURER_CLUSTER)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(
    registries.TUYA_MANUFACTURER_CLUSTER
)
class TuyaClusterHandler(ClusterHandler):
    """Cluster handler for the Tuya manufacturer Zigbee cluster."""

    REPORT_CONFIG = ()

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize TuyaClusterHandler."""
        super().__init__(cluster, endpoint)
        if endpoint.device.quirk_id == TUYA_PLUG_MANUFACTURER:
            self.ZCL_INIT_ATTRS = {
                "backlight_mode": True,
                "power_on_state": True,
            }


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(0xFCC0)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(0xFCC0)
class OppleRemoteClusterHandler(ClusterHandler):
    """Opple cluster handler."""

    REPORT_CONFIG = ()

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize Opple cluster handler."""
        super().__init__(cluster, endpoint)
        if self.cluster.endpoint.model == "lumi.motion.ac02":
            self.ZCL_INIT_ATTRS = {
                "detection_interval": True,
                "motion_sensitivity": True,
                "trigger_indicator": True,
            }
        elif self.cluster.endpoint.model == "lumi.motion.agl04":
            self.ZCL_INIT_ATTRS = {
                "detection_interval": True,
                "motion_sensitivity": True,
            }
        elif self.cluster.endpoint.model == "lumi.motion.ac01":
            self.ZCL_INIT_ATTRS = {
                "presence": True,
                "monitoring_mode": True,
                "motion_sensitivity": True,
                "approach_distance": True,
            }
        elif self.cluster.endpoint.model in ("lumi.plug.mmeu01", "lumi.plug.maeu01"):
            self.ZCL_INIT_ATTRS = {
                "power_outage_memory": True,
                "consumer_connected": True,
            }
        elif self.cluster.endpoint.model == "aqara.feeder.acn001":
            self.ZCL_INIT_ATTRS = {
                "portions_dispensed": True,
                "weight_dispensed": True,
                "error_detected": True,
                "disable_led_indicator": True,
                "child_lock": True,
                "feeding_mode": True,
                "serving_size": True,
                "portion_weight": True,
            }
        elif self.cluster.endpoint.model == "lumi.airrtc.agl001":
            self.ZCL_INIT_ATTRS = {
                "system_mode": True,
                "preset": True,
                "window_detection": True,
                "valve_detection": True,
                "valve_alarm": True,
                "child_lock": True,
                "away_preset_temperature": True,
                "window_open": True,
                "calibrated": True,
                "schedule": True,
                "sensor": True,
            }
        elif self.cluster.endpoint.model == "lumi.sensor_smoke.acn03":
            self.ZCL_INIT_ATTRS = {
                "buzzer_manual_mute": True,
                "smoke_density": True,
                "heartbeat_indicator": True,
                "buzzer_manual_alarm": True,
                "buzzer": True,
                "linkage_alarm": True,
            }
        elif self.cluster.endpoint.model == "lumi.magnet.ac01":
            self.ZCL_INIT_ATTRS = {
                "detection_distance": True,
            }
        elif self.cluster.endpoint.model == "lumi.switch.acn047":
            self.ZCL_INIT_ATTRS = {
                "switch_mode": True,
                "switch_type": True,
                "startup_on_off": True,
                "decoupled_mode": True,
            }
        elif self.cluster.endpoint.model == "lumi.curtain.agl001":
            self.ZCL_INIT_ATTRS = {
                "hooks_state": True,
                "hooks_lock": True,
                "positions_stored": True,
                "light_level": True,
                "hand_open": True,
            }

    async def async_initialize_cluster_handler_specific(self, from_cache: bool) -> None:
        """Initialize cluster handler specific."""
        if self.cluster.endpoint.model in ("lumi.motion.ac02", "lumi.motion.agl04"):
            interval = self.cluster.get("detection_interval", self.cluster.get(0x0102))
            if interval is not None:
                self.debug("Loaded detection interval at startup: %s", interval)
                self.cluster.endpoint.ias_zone.reset_s = int(interval)


@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(
    registries.SMARTTHINGS_ACCELERATION_CLUSTER
)
class SmartThingsAccelerationClusterHandler(ClusterHandler):
    """Smart Things Acceleration cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(attr="acceleration", config=REPORT_CONFIG_ASAP),
        AttrReportConfig(attr="x_axis", config=REPORT_CONFIG_ASAP),
        AttrReportConfig(attr="y_axis", config=REPORT_CONFIG_ASAP),
        AttrReportConfig(attr="z_axis", config=REPORT_CONFIG_ASAP),
    )

    @classmethod
    def matches(cls, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> bool:
        """Filter the cluster match for specific devices."""
        return cluster.endpoint.device.manufacturer in (
            "CentraLite",
            "Samjin",
            "SmartThings",
        )

    @callback
    def attribute_updated(self, attrid: int, value: Any, _: Any) -> None:
        """Handle attribute updates on this cluster."""
        try:
            attr_name = self._cluster.attributes[attrid].name
        except KeyError:
            attr_name = UNKNOWN

        if attrid == self.value_attribute:
            self.async_send_signal(
                f"{self.unique_id}_{SIGNAL_ATTR_UPDATED}",
                attrid,
                attr_name,
                value,
            )
            return

        self.zha_send_event(
            SIGNAL_ATTR_UPDATED,
            {
                ATTR_ATTRIBUTE_ID: attrid,
                ATTR_ATTRIBUTE_NAME: attr_name,
                ATTR_VALUE: value,
            },
        )


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(0xFC31)
class InovelliNotificationClientClusterHandler(ClientClusterHandler):
    """Inovelli Notification cluster handler."""

    @callback
    def attribute_updated(self, attrid: int, value: Any, _: Any) -> None:
        """Handle an attribute updated on this cluster."""

    @callback
    def cluster_command(self, tsn, command_id, args):
        """Handle a cluster command received on this cluster."""


@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(0xFC31)
class InovelliConfigEntityClusterHandler(ClusterHandler):
    """Inovelli Configuration Entity cluster handler."""

    REPORT_CONFIG = ()

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize Inovelli cluster handler."""
        super().__init__(cluster, endpoint)
        if self.cluster.endpoint.model == "VZM31-SN":
            self.ZCL_INIT_ATTRS = {
                "dimming_speed_up_remote": True,
                "dimming_speed_up_local": True,
                "ramp_rate_off_to_on_local": True,
                "ramp_rate_off_to_on_remote": True,
                "dimming_speed_down_remote": True,
                "dimming_speed_down_local": True,
                "ramp_rate_on_to_off_local": True,
                "ramp_rate_on_to_off_remote": True,
                "minimum_level": True,
                "maximum_level": True,
                "invert_switch": True,
                "auto_off_timer": True,
                "default_level_local": True,
                "default_level_remote": True,
                "state_after_power_restored": True,
                "load_level_indicator_timeout": True,
                "active_power_reports": True,
                "periodic_power_and_energy_reports": True,
                "active_energy_reports": True,
                "power_type": False,
                "switch_type": False,
                "increased_non_neutral_output": True,
                "button_delay": False,
                "smart_bulb_mode": False,
                "double_tap_up_enabled": True,
                "double_tap_down_enabled": True,
                "double_tap_up_level": True,
                "double_tap_down_level": True,
                "led_color_when_on": True,
                "led_color_when_off": True,
                "led_intensity_when_on": True,
                "led_intensity_when_off": True,
                "led_scaling_mode": True,
                "aux_switch_scenes": True,
                "binding_off_to_on_sync_level": True,
                "local_protection": False,
                "output_mode": False,
                "on_off_led_mode": True,
                "firmware_progress_led": True,
                "relay_click_in_on_off_mode": True,
                "disable_clear_notifications_double_tap": True,
            }
        elif self.cluster.endpoint.model == "VZM35-SN":
            self.ZCL_INIT_ATTRS = {
                "dimming_speed_up_remote": True,
                "dimming_speed_up_local": True,
                "ramp_rate_off_to_on_local": True,
                "ramp_rate_off_to_on_remote": True,
                "dimming_speed_down_remote": True,
                "dimming_speed_down_local": True,
                "ramp_rate_on_to_off_local": True,
                "ramp_rate_on_to_off_remote": True,
                "minimum_level": True,
                "maximum_level": True,
                "invert_switch": True,
                "auto_off_timer": True,
                "default_level_local": True,
                "default_level_remote": True,
                "state_after_power_restored": True,
                "load_level_indicator_timeout": True,
                "power_type": False,
                "switch_type": False,
                "non_neutral_aux_med_gear_learn_value": True,
                "non_neutral_aux_low_gear_learn_value": True,
                "quick_start_time": False,
                "button_delay": False,
                "smart_fan_mode": False,
                "double_tap_up_enabled": True,
                "double_tap_down_enabled": True,
                "double_tap_up_level": True,
                "double_tap_down_level": True,
                "led_color_when_on": True,
                "led_color_when_off": True,
                "led_intensity_when_on": True,
                "led_intensity_when_off": True,
                "aux_switch_scenes": True,
                "local_protection": False,
                "output_mode": False,
                "on_off_led_mode": True,
                "firmware_progress_led": True,
                "smart_fan_led_display_levels": True,
            }

    async def issue_all_led_effect(
        self,
        effect_type: AllLEDEffectType | int = AllLEDEffectType.Fast_Blink,
        color: int = 200,
        level: int = 100,
        duration: int = 3,
        **kwargs: Any,
    ) -> None:
        """Issue all LED effect command.

        This command is used to issue an LED effect to all LEDs on the device.
        """

        await self.led_effect(effect_type, color, level, duration, expect_reply=False)

    async def issue_individual_led_effect(
        self,
        led_number: int = 1,
        effect_type: SingleLEDEffectType | int = SingleLEDEffectType.Fast_Blink,
        color: int = 200,
        level: int = 100,
        duration: int = 3,
        **kwargs: Any,
    ) -> None:
        """Issue individual LED effect command.

        This command is used to issue an LED effect to the specified LED on the device.
        """

        await self.individual_led_effect(
            led_number, effect_type, color, level, duration, expect_reply=False
        )


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(registries.IKEA_AIR_PURIFIER_CLUSTER)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(
    registries.IKEA_AIR_PURIFIER_CLUSTER
)
class IkeaAirPurifierClusterHandler(ClusterHandler):
    """IKEA Air Purifier cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(attr="filter_run_time", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="replace_filter", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="filter_life_time", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="disable_led", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="air_quality_25pm", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="child_lock", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="fan_mode", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="fan_speed", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="device_run_time", config=REPORT_CONFIG_DEFAULT),
    )

    @property
    def fan_mode(self) -> int | None:
        """Return current fan mode."""
        return self.cluster.get("fan_mode")

    @property
    def fan_mode_sequence(self) -> int | None:
        """Return possible fan mode speeds."""
        return self.cluster.get("fan_mode_sequence")

    async def async_set_speed(self, value) -> None:
        """Set the speed of the fan."""
        await self.write_attributes_safe({"fan_mode": value})

    async def async_update(self) -> None:
        """Retrieve latest state."""
        await self.get_attribute_value("fan_mode", from_cache=False)

    @callback
    def attribute_updated(self, attrid: int, value: Any, _: Any) -> None:
        """Handle attribute update from fan cluster."""
        attr_name = self._get_attribute_name(attrid)
        self.debug(
            "Attribute report '%s'[%s] = %s", self.cluster.name, attr_name, value
        )
        if attr_name == "fan_mode":
            self.async_send_signal(
                f"{self.unique_id}_{SIGNAL_ATTR_UPDATED}", attrid, attr_name, value
            )


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(0xFC80)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(0xFC80)
class IkeaRemoteClusterHandler(ClusterHandler):
    """Ikea Matter remote cluster handler."""

    REPORT_CONFIG = ()


@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(
    DoorLock.cluster_id, XIAOMI_AQARA_VIBRATION_AQ1
)
class XiaomiVibrationAQ1ClusterHandler(MultistateInputClusterHandler):
    """Xiaomi DoorLock Cluster is in fact a MultiStateInput Cluster."""


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(0xFC11)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(0xFC11)
class SonoffPresenceSenorClusterHandler(ClusterHandler):
    """SonoffPresenceSensor cluster handler."""

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize SonoffPresenceSensor cluster handler."""
        super().__init__(cluster, endpoint)
        if self.cluster.endpoint.model == "SNZB-06P":
            self.ZCL_INIT_ATTRS = {"last_illumination_state": True}
