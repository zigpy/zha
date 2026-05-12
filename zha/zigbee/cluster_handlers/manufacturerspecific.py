"""Manufacturer specific cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from zhaquirks.inovelli.types import AllLEDEffectType, SingleLEDEffectType
from zhaquirks.quirk_ids import DANFOSS_ALLY_THERMOSTAT, XIAOMI_AQARA_VIBRATION_AQ1
import zigpy.zcl
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
)
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
    IKEA_AIR_PURIFIER_CLUSTER,
    IKEA_REMOTE_CLUSTER,
    IKEA_SHORTCUT_V1_CLUSTER,
    INOVELLI_CLUSTER,
    LEGRAND_CABLE_OUTLET_CLUSTER,
    OSRAM_BUTTON_CLUSTER,
    PHILIPS_CONTACT_CLUSTER,
    PHILLIPS_REMOTE_CLUSTER,
    REPORT_CONFIG_ASAP,
    REPORT_CONFIG_DEFAULT,
    REPORT_CONFIG_IMMEDIATE,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_MIN_INT,
    SINOPE_MANUFACTURER_CLUSTER,
    SMARTTHINGS_ACCELERATION_CLUSTER,
    SMARTTHINGS_HUMIDITY_CLUSTER,
    SONOFF_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
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
    """Cluster handler for the Tuya manufacturer Zigbee cluster.

    Per-feature attribute init lives on the `TuyaPlugManufacturerInit` virtual
    entity now.
    """

    REPORT_CONFIG = ()


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(AQARA_OPPLE_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(AQARA_OPPLE_CLUSTER)
class OppleRemoteClusterHandler(ClusterHandler):
    """Opple cluster handler.

    Per-model attribute init lives on the `Aqara*Init` virtual entities now.
    The cross-cluster `detection_interval` -> `ias_zone.reset_s` write is
    handled by `AqaraMotionDetectionIntervalSync`.
    """

    REPORT_CONFIG: tuple[AttrReportConfig, ...] = ()


@registries.CLUSTER_HANDLER_REGISTRY.register(SMARTTHINGS_ACCELERATION_CLUSTER)
class SmartThingsAccelerationClusterHandler(ClusterHandler):
    """Smart Things Acceleration cluster handler.

    `zha_event` emission per attribute update lives on the
    `SmartThingsAccelerationEvent` virtual entity now.
    """

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


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(INOVELLI_CLUSTER)
class InovelliNotificationClientClusterHandler(ClientClusterHandler):
    """Inovelli Notification cluster handler."""

    def _handle_attribute_updated_event(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle an attribute updated on this cluster."""

    def cluster_command(self, tsn, command_id, args):
        """Handle a cluster command received on this cluster."""


@registries.CLUSTER_HANDLER_REGISTRY.register(INOVELLI_CLUSTER)
class InovelliConfigEntityClusterHandler(ClusterHandler):
    """Inovelli Configuration Entity cluster handler.

    Per-model attribute init lives on the `InovelliVzm30/31/35Init` virtual
    entities now.
    """

    REPORT_CONFIG = ()

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
@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(IKEA_REMOTE_CLUSTER)
class IkeaRemoteClientClusterHandler(ClientClusterHandler):
    """Ikea Matter remote cluster handler."""

    REPORT_CONFIG = ()

    def cluster_command(self, tsn, command_id, args):
        """Handle a cluster command received on this cluster."""
        # Do not emit ZHA events when receiving a client command, this duplicates the
        # existing event sent by the quirk.
        pass


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(IKEA_SHORTCUT_V1_CLUSTER)
@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(IKEA_SHORTCUT_V1_CLUSTER)
class IkeaSymfoniskRemoteClientClusterHandler(ClientClusterHandler):
    """Ikea Symfonisk remote cluster handler."""

    REPORT_CONFIG = ()

    def cluster_command(self, tsn, command_id, args):
        """Handle a cluster command received on this cluster."""
        # Do not emit ZHA events when receiving a client command, this duplicates the
        # existing event sent by the quirk.
        pass


@registries.CLUSTER_HANDLER_REGISTRY.register(
    DoorLock.cluster_id, XIAOMI_AQARA_VIBRATION_AQ1
)
class XiaomiVibrationAQ1ClusterHandler(MultistateInputClusterHandler):
    """Xiaomi DoorLock Cluster is in fact a MultiStateInput Cluster."""


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(SONOFF_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(SONOFF_CLUSTER)
class SonoffPresenceSenorClusterHandler(ClusterHandler):
    """SonoffPresenceSensor cluster handler.

    Per-model attribute init lives on the `SonoffPresenceSensorInit` virtual
    entity now.
    """


@registries.CLUSTER_HANDLER_REGISTRY.register(
    Thermostat.cluster_id, DANFOSS_ALLY_THERMOSTAT
)
class DanfossThermostatClusterHandler(ThermostatClusterHandler):
    """Thermostat cluster handler for the Danfoss TRV and derivatives."""

    REPORT_CONFIG = (  # type: ignore[assignment]
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

    _value_attribute = "action_report"
    REPORT_CONFIG = ()

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


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(LEGRAND_CABLE_OUTLET_CLUSTER)
@registries.CLUSTER_HANDLER_REGISTRY.register(LEGRAND_CABLE_OUTLET_CLUSTER)
class LegrandCableOutletClusterHandler(ClusterHandler):
    """Legrand cable outlet cluster handler."""
