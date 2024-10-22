"""Manufacturer specific cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from zhaquirks.inovelli.types import AllLEDEffectType, SingleLEDEffectType
from zhaquirks.quirk_ids import (
    DANFOSS_ALLY_THERMOSTAT,
    TUYA_PLUG_MANUFACTURER,
    XIAOMI_AQARA_VIBRATION_AQ1,
)
import zigpy.zcl
from zigpy.zcl.clusters.closures import DoorLock
from zigpy.zcl.clusters.homeautomation import Diagnostic
from zigpy.zcl.clusters.hvac import Thermostat, UserInterface

from zha.zigbee.cluster_handlers import (
    AttrReportConfig,
    ClientClusterHandler,
    ClusterHandler,
    registries,
)
from zha.zigbee.cluster_handlers.const import (
    AQARA_OPPLE_CLUSTER,
    ATTRIBUTE_ID,
    ATTRIBUTE_NAME,
    ATTRIBUTE_VALUE,
    IKEA_AIR_PURIFIER_CLUSTER,
    IKEA_REMOTE_CLUSTER,
    INOVELLI_CLUSTER,
    OSRAM_BUTTON_CLUSTER,
    PHILIPS_CONTACT_CLUSTER,
    PHILLIPS_REMOTE_CLUSTER,
    REPORT_CONFIG_ASAP,
    REPORT_CONFIG_DEFAULT,
    REPORT_CONFIG_IMMEDIATE,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_MIN_INT,
    REPORT_CONFIG_MIN_INT_IMMEDIATE,
    REPORT_CONFIG_RPT_CHANGE,
    SIGNAL_ATTR_UPDATED,
    SINOPE_MANUFACTURER_CLUSTER,
    SMARTTHINGS_ACCELERATION_CLUSTER,
    SMARTTHINGS_HUMIDITY_CLUSTER,
    SONOFF_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
    UNKNOWN,
)
from zha.zigbee.cluster_handlers.general import MultistateInputClusterHandler

from .homeautomation import DiagnosticClusterHandler
from .hvac import ThermostatClusterHandler, UserInterfaceClusterHandler

if TYPE_CHECKING:
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)


@registries.CLUSTER_HANDLER_REGISTRY.register(SMARTTHINGS_HUMIDITY_CLUSTER)
class SmartThingsHumidityClusterHandler(ClusterHandler):
    """Smart Things Humidity cluster handler."""

    REPORT_CONFIG = (
        {
            "attr": "measured_value",
            "config": (REPORT_CONFIG_MIN_INT, REPORT_CONFIG_MAX_INT, 50),
        },
    )


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(OSRAM_BUTTON_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(OSRAM_BUTTON_CLUSTER)
class OsramButtonClusterHandler(ClusterHandler):
    """Osram button cluster handler."""

    REPORT_CONFIG = ()


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(PHILIPS_CONTACT_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(PHILIPS_CONTACT_CLUSTER)
class PhillipsContactClusterHandler(ClusterHandler):
    """Phillips contact cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(attr="contact", config=REPORT_CONFIG_IMMEDIATE),
        AttrReportConfig(attr="tamper", config=REPORT_CONFIG_IMMEDIATE),
    )


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(PHILLIPS_REMOTE_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(PHILLIPS_REMOTE_CLUSTER)
class PhillipsRemoteClusterHandler(ClusterHandler):
    """Phillips remote cluster handler."""

    REPORT_CONFIG = ()


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(TUYA_MANUFACTURER_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(TUYA_MANUFACTURER_CLUSTER)
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


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(AQARA_OPPLE_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(AQARA_OPPLE_CLUSTER)
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

    async def async_initialize_cluster_handler_specific(self, from_cache: bool) -> None:  # pylint: disable=unused-argument
        """Initialize cluster handler specific."""
        if self.cluster.endpoint.model in ("lumi.motion.ac02", "lumi.motion.agl04"):
            interval = self.cluster.get("detection_interval", self.cluster.get(0x0102))
            if interval is not None:
                self.debug("Loaded detection interval at startup: %s", interval)
                self.cluster.endpoint.ias_zone.reset_s = int(interval)


@registries.CLUSTER_HANDLER_REGISTRY.register(SMARTTHINGS_ACCELERATION_CLUSTER)
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

    def attribute_updated(self, attrid: int, value: Any, _: Any) -> None:
        """Handle attribute updates on this cluster."""
        super().attribute_updated(attrid, value, _)
        try:
            attr_name = self._cluster.attributes[attrid].name
        except KeyError:
            attr_name = UNKNOWN

        self.emit_zha_event(
            SIGNAL_ATTR_UPDATED,
            {
                ATTRIBUTE_ID: attrid,
                ATTRIBUTE_NAME: attr_name,
                ATTRIBUTE_VALUE: value,
            },
        )


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(INOVELLI_CLUSTER)
class InovelliNotificationClientClusterHandler(ClientClusterHandler):
    """Inovelli Notification cluster handler."""

    def attribute_updated(self, attrid: int, value: Any, _: Any) -> None:
        """Handle an attribute updated on this cluster."""

    def cluster_command(self, tsn, command_id, args):
        """Handle a cluster command received on this cluster."""


@registries.CLUSTER_HANDLER_REGISTRY.register(INOVELLI_CLUSTER)
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
                "ramp_rate_off_to_on_remote": True,
                "ramp_rate_off_to_on_local": True,
                "dimming_speed_down_remote": True,
                "dimming_speed_down_local": True,
                "ramp_rate_on_to_off_remote": True,
                "ramp_rate_on_to_off_local": True,
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
                "leading_or_trailing_edge": True,
                "internal_temp_monitor": True,
                "overheated": True,
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

    async def issue_all_led_effect(  # pylint: disable=unused-argument
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

    async def issue_individual_led_effect(  # pylint: disable=too-many-arguments,unused-argument
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


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(IKEA_AIR_PURIFIER_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(IKEA_AIR_PURIFIER_CLUSTER)
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
    def fan_speed(self) -> int | None:
        """Return current fan speed."""
        return self.cluster.get("fan_speed")

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
        await self.get_attribute_value("fan_speed", from_cache=False)


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(IKEA_REMOTE_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(IKEA_REMOTE_CLUSTER)
class IkeaRemoteClusterHandler(ClusterHandler):
    """Ikea Matter remote cluster handler."""

    REPORT_CONFIG = ()


@registries.CLUSTER_HANDLER_REGISTRY.register(
    DoorLock.cluster_id, XIAOMI_AQARA_VIBRATION_AQ1
)
class XiaomiVibrationAQ1ClusterHandler(MultistateInputClusterHandler):
    """Xiaomi DoorLock Cluster is in fact a MultiStateInput Cluster."""


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(SONOFF_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(SONOFF_CLUSTER)
class SonoffPresenceSenorClusterHandler(ClusterHandler):
    """SonoffPresenceSensor cluster handler."""

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize SonoffPresenceSensor cluster handler."""
        super().__init__(cluster, endpoint)
        if self.cluster.endpoint.model == "SNZB-06P":
            self.ZCL_INIT_ATTRS = {"last_illumination_state": True}


@registries.CLUSTER_HANDLER_REGISTRY.register(
    Thermostat.cluster_id, DANFOSS_ALLY_THERMOSTAT
)
class DanfossThermostatClusterHandler(ThermostatClusterHandler):
    """Thermostat cluster handler for the Danfoss TRV and derivatives."""

    REPORT_CONFIG = (
        *ThermostatClusterHandler.REPORT_CONFIG,
        AttrReportConfig(attr="open_window_detection", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="heat_required", config=REPORT_CONFIG_ASAP),
        AttrReportConfig(attr="mounting_mode_active", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="load_estimate", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="adaptation_run_status", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="preheat_status", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="preheat_time", config=REPORT_CONFIG_DEFAULT),
    )

    ZCL_INIT_ATTRS = {
        **ThermostatClusterHandler.ZCL_INIT_ATTRS,
        "external_open_window_detected": True,
        "window_open_feature": True,
        "exercise_day_of_week": True,
        "exercise_trigger_time": True,
        "mounting_mode_control": False,  # Can change
        "orientation": True,
        "external_measured_room_sensor": False,  # Can change
        "radiator_covered": True,
        "heat_available": True,
        "load_balancing_enable": True,
        "load_room_mean": False,  # Can change
        "control_algorithm_scale_factor": True,
        "regulation_setpoint_offset": True,
        "adaptation_run_control": True,
        "adaptation_run_settings": True,
    }


@registries.CLUSTER_HANDLER_REGISTRY.register(
    UserInterface.cluster_id, DANFOSS_ALLY_THERMOSTAT
)
class DanfossUserInterfaceClusterHandler(UserInterfaceClusterHandler):
    """Interface cluster handler for the Danfoss TRV and derivatives."""

    ZCL_INIT_ATTRS = {
        **UserInterfaceClusterHandler.ZCL_INIT_ATTRS,
        "viewing_direction": True,
    }


@registries.CLUSTER_HANDLER_REGISTRY.register(
    Diagnostic.cluster_id, DANFOSS_ALLY_THERMOSTAT
)
class DanfossDiagnosticClusterHandler(DiagnosticClusterHandler):
    """Diagnostic cluster handler for the Danfoss TRV and derivatives."""

    REPORT_CONFIG = (
        *DiagnosticClusterHandler.REPORT_CONFIG,
        AttrReportConfig(attr="sw_error_code", config=REPORT_CONFIG_DEFAULT),
        AttrReportConfig(attr="motor_step_counter", config=REPORT_CONFIG_DEFAULT),
    )


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(SINOPE_MANUFACTURER_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(SINOPE_MANUFACTURER_CLUSTER)
class SinopeManufacturerClusterHandler(ClusterHandler):
    """Sinope Manufacturer cluster handler."""

    BIND = True

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize Sinope cluster handler."""
        super().__init__(cluster, endpoint)
        self.ZCL_INIT_ATTRS = {
            "double_up_full": True,
            "on_led_color": True,
            "off_led_color": True,
            "off_led_intensity": True,
            "on_led_intensity": True,
        }

        if self.cluster.endpoint.model in [
            "DM2550ZB",
            "DM2550ZB-G2",
            "DM2500ZB-G2",
            "DM2500ZB",
        ]:
            self.ZCL_INIT_ATTRS["on_intensity"] = True

    _value_attribute = "action_report"
    REPORT_CONFIG = (
        AttrReportConfig(
            attr="action_report",
            config=(
                REPORT_CONFIG_MIN_INT_IMMEDIATE,
                REPORT_CONFIG_MIN_INT_IMMEDIATE,
                REPORT_CONFIG_RPT_CHANGE,
            ),
        ),
    )

    @classmethod
    def matches(cls, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> bool:
        """Filter the cluster match for specific devices."""
        switches = (
            "SW2500ZB",
            "SW2500ZB-G2",
            "DM2500ZB",
            "DM2500ZB-G2",
            "DM2550ZB",
            "DM2550ZB-G2",
        )

        _LOGGER.debug(
            "matching sinope device to cluster handler %s", cluster.endpoint.model
        )

        return cluster.endpoint.model in switches
