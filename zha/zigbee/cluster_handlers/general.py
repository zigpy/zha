"""General cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import zigpy.exceptions
import zigpy.types as t
import zigpy.zcl
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
)
from zigpy.zcl.clusters.general import (
    Alarms,
    AnalogInput,
    AnalogOutput,
    AnalogValue,
    ApplianceControl,
    Basic,
    BinaryInput,
    BinaryOutput,
    BinaryValue,
    Commissioning,
    DeviceTemperature,
    GreenPowerProxy,
    Groups,
    Identify,
    LevelControl,
    MultistateInput,
    MultistateOutput,
    MultistateValue,
    OnOff,
    OnOffConfiguration,
    Ota,
    Partition,
    PowerConfiguration,
    PowerProfile,
    RSSILocation,
    Scenes,
    Time,
)
from zigpy.zcl.clusters.general_const import ApplicationType
from zigpy.zcl.foundation import Status

from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers import (
    AttrReportConfig,
    ClientClusterHandler,
    ClusterHandler,
    parse_and_log_command,
    registries,
)
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_LEVEL_CHANGED,
    REPORT_CONFIG_ASAP,
    REPORT_CONFIG_BATTERY_SAVE,
    REPORT_CONFIG_DEFAULT,
    REPORT_CONFIG_IMMEDIATE,
    REPORT_CONFIG_MAX_INT,
    REPORT_CONFIG_MIN_INT,
    SIGNAL_MOVE_LEVEL,
    SIGNAL_SET_LEVEL,
)

if TYPE_CHECKING:
    from zha.zigbee.endpoint import Endpoint


@dataclass(frozen=True, kw_only=True)
class LevelChangeEvent:
    """Event to signal that a cluster attribute has been updated."""

    level: int
    event: str
    event_type: Final[str] = "cluster_handler_event"


@registries.CLUSTER_HANDLER_REGISTRY.register(Alarms.cluster_id)
class AlarmsClusterHandler(ClusterHandler):
    """Alarms cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(AnalogInput.cluster_id)
class AnalogInputClusterHandler(ClusterHandler):
    """Analog Input cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=AnalogInput.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )
    ZCL_INIT_ATTRS = {
        AnalogInput.AttributeDefs.description.name: True,
        AnalogInput.AttributeDefs.max_present_value.name: True,
        AnalogInput.AttributeDefs.min_present_value.name: True,
        AnalogInput.AttributeDefs.out_of_service.name: True,
        AnalogInput.AttributeDefs.reliability.name: True,
        AnalogInput.AttributeDefs.resolution.name: True,
        AnalogInput.AttributeDefs.status_flags.name: True,
        AnalogInput.AttributeDefs.engineering_units.name: True,
        AnalogInput.AttributeDefs.application_type.name: True,
    }

    @property
    def present_value(self) -> float | None:
        """Return cached value of present_value."""
        return self.cluster.get(AnalogInput.AttributeDefs.present_value.name)

    @property
    def description(self) -> str | None:
        """Return cached value of description."""
        return self.cluster.get(AnalogInput.AttributeDefs.description.name)

    @property
    def max_present_value(self) -> float | None:
        """Return cached value of max_present_value."""
        return self.cluster.get(AnalogInput.AttributeDefs.max_present_value.name)

    @property
    def min_present_value(self) -> float | None:
        """Return cached value of min_present_value."""
        return self.cluster.get(AnalogInput.AttributeDefs.min_present_value.name)

    @property
    def out_of_service(self) -> bool | None:
        """Return cached value of out_of_service."""
        return self.cluster.get(AnalogInput.AttributeDefs.out_of_service.name)

    @property
    def reliability(self) -> int | None:
        """Return cached value of reliability."""
        return self.cluster.get(AnalogInput.AttributeDefs.reliability.name)

    @property
    def resolution(self) -> float | None:
        """Return cached value of resolution."""
        return self.cluster.get(AnalogInput.AttributeDefs.resolution.name)

    @property
    def status_flags(self) -> int | None:
        """Return cached value of status_flags."""
        return self.cluster.get(AnalogInput.AttributeDefs.status_flags.name)

    @property
    def engineering_units(self) -> int | None:
        """Return cached value of engineering_units."""
        return self.cluster.get(AnalogInput.AttributeDefs.engineering_units.name)

    @property
    def application_type(self) -> ApplicationType | None:
        """Return cached value of application_type."""
        result = self.cluster.get(AnalogInput.AttributeDefs.application_type.name)
        if result is None:
            return None
        return ApplicationType(result)

    async def async_update(self):
        """Update cluster value attribute."""
        await self.get_attribute_value(
            AnalogInput.AttributeDefs.present_value.name, from_cache=False
        )


@registries.BINDABLE_CLUSTERS.register(AnalogOutput.cluster_id)
@registries.CLUSTER_HANDLER_REGISTRY.register(AnalogOutput.cluster_id)
class AnalogOutputClusterHandler(ClusterHandler):
    """Analog Output cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=AnalogOutput.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )
    ZCL_INIT_ATTRS = {
        AnalogOutput.AttributeDefs.min_present_value.name: True,
        AnalogOutput.AttributeDefs.max_present_value.name: True,
        AnalogOutput.AttributeDefs.resolution.name: True,
        AnalogOutput.AttributeDefs.relinquish_default.name: True,
        AnalogOutput.AttributeDefs.description.name: True,
        AnalogOutput.AttributeDefs.engineering_units.name: True,
        AnalogOutput.AttributeDefs.application_type.name: True,
    }

    @property
    def present_value(self) -> float | None:
        """Return cached value of present_value."""
        return self.cluster.get(AnalogOutput.AttributeDefs.present_value.name)

    @property
    def min_present_value(self) -> float | None:
        """Return cached value of min_present_value."""
        return self.cluster.get(AnalogOutput.AttributeDefs.min_present_value.name)

    @property
    def max_present_value(self) -> float | None:
        """Return cached value of max_present_value."""
        return self.cluster.get(AnalogOutput.AttributeDefs.max_present_value.name)

    @property
    def resolution(self) -> float | None:
        """Return cached value of resolution."""
        return self.cluster.get(AnalogOutput.AttributeDefs.resolution.name)

    @property
    def relinquish_default(self) -> float | None:
        """Return cached value of relinquish_default."""
        return self.cluster.get(AnalogOutput.AttributeDefs.relinquish_default.name)

    @property
    def description(self) -> str | None:
        """Return cached value of description."""
        return self.cluster.get(AnalogOutput.AttributeDefs.description.name)

    @property
    def engineering_units(self) -> int | None:
        """Return cached value of engineering_units."""
        return self.cluster.get(AnalogOutput.AttributeDefs.engineering_units.name)

    @property
    def application_type(self) -> int | None:
        """Return cached value of application_type."""
        return self.cluster.get(AnalogOutput.AttributeDefs.application_type.name)

    async def async_set_present_value(self, value: float) -> None:
        """Update present_value."""
        await self.write_attributes_safe(
            {AnalogOutput.AttributeDefs.present_value.name: value}
        )

    async def async_update(self):
        """Update cluster value attribute."""
        await self.get_attribute_value(
            AnalogOutput.AttributeDefs.present_value.name, from_cache=False
        )


@registries.CLUSTER_HANDLER_REGISTRY.register(AnalogValue.cluster_id)
class AnalogValueClusterHandler(ClusterHandler):
    """Analog Value cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=AnalogValue.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(ApplianceControl.cluster_id)
class ApplianceControlClusterHandler(ClusterHandler):
    """Appliance Control cluster handler."""


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(Basic.cluster_id)
@registries.CLUSTER_HANDLER_REGISTRY.register(Basic.cluster_id)
class BasicClusterHandler(ClusterHandler):
    """Cluster handler to interact with the basic cluster.

    Per-model attribute initialization (Hue `trigger_indicator`, TI router
    `transmit_power`, Aqara curtain `power_source`) lives on the corresponding
    entities' `_server_cluster_config` now.
    """

    UNKNOWN = 0
    BATTERY = 3
    BIND: bool = False

    POWER_SOURCES = {
        UNKNOWN: "Unknown",
        1: "Mains (single phase)",
        2: "Mains (3 phase)",
        BATTERY: "Battery",
        4: "DC source",
        5: "Emergency mains constantly powered",
        6: "Emergency mains and transfer switch",
    }


@registries.CLUSTER_HANDLER_REGISTRY.register(BinaryInput.cluster_id)
class BinaryInputClusterHandler(ClusterHandler):
    """Binary Input cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=BinaryInput.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
    )

    ZCL_INIT_ATTRS = {
        BinaryInput.AttributeDefs.description.name: True,
    }

    @property
    def description(self) -> str | None:
        """Return cached value of description."""
        return self.cluster.get(BinaryInput.AttributeDefs.description.name)


@registries.CLUSTER_HANDLER_REGISTRY.register(BinaryOutput.cluster_id)
class BinaryOutputClusterHandler(ClusterHandler):
    """Binary Output cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=BinaryOutput.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
    )

    ZCL_INIT_ATTRS = {
        BinaryOutput.AttributeDefs.description.name: True,
    }

    @property
    def description(self) -> str | None:
        """Return cached value of description."""
        return self.cluster.get(BinaryOutput.AttributeDefs.description.name)

    @property
    def present_value(self) -> bool | None:
        """Return cached value of present_value."""
        return self.cluster.get(BinaryOutput.AttributeDefs.present_value.name)

    async def async_set_present_value(self, value: bool) -> None:
        """Update present_value."""
        await self.write_attributes_safe(
            {BinaryOutput.AttributeDefs.present_value.name: value}
        )

    async def async_update(self):
        """Update cluster value attribute."""
        await self.get_attribute_value(
            BinaryOutput.AttributeDefs.present_value.name, from_cache=False
        )


@registries.CLUSTER_HANDLER_REGISTRY.register(BinaryValue.cluster_id)
class BinaryValueClusterHandler(ClusterHandler):
    """Binary Value cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=BinaryValue.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(Commissioning.cluster_id)
class CommissioningClusterHandler(ClusterHandler):
    """Commissioning cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(DeviceTemperature.cluster_id)
class DeviceTemperatureClusterHandler(ClusterHandler):
    """Device Temperature cluster handler."""

    REPORT_CONFIG = (
        {
            "attr": DeviceTemperature.AttributeDefs.current_temperature.name,
            "config": (REPORT_CONFIG_MIN_INT, REPORT_CONFIG_MAX_INT, 50),
        },
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(GreenPowerProxy.cluster_id)
class GreenPowerProxyClusterHandler(ClusterHandler):
    """Green Power Proxy cluster handler."""

    BIND: bool = False


@registries.CLUSTER_HANDLER_REGISTRY.register(Groups.cluster_id)
class GroupsClusterHandler(ClusterHandler):
    """Groups cluster handler."""

    BIND: bool = False


@registries.CLUSTER_HANDLER_REGISTRY.register(Identify.cluster_id)
class IdentifyClusterHandler(ClusterHandler):
    """Identify cluster handler.

    `trigger_effect` → zha_event dispatch lives on the
    `IdentifyTriggerEffectEvent` virtual entity now.
    """

    BIND: bool = False


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(LevelControl.cluster_id)
class LevelControlClientClusterHandler(ClientClusterHandler):
    """LevelControl client cluster."""


@registries.BINDABLE_CLUSTERS.register(LevelControl.cluster_id)
@registries.CLUSTER_HANDLER_REGISTRY.register(LevelControl.cluster_id)
class LevelControlClusterHandler(ClusterHandler):
    """Cluster handler for the LevelControl Zigbee cluster."""

    CURRENT_LEVEL = 0
    REPORT_CONFIG = (
        AttrReportConfig(
            attr=LevelControl.AttributeDefs.current_level.name,
            config=REPORT_CONFIG_ASAP,
        ),
    )
    ZCL_INIT_ATTRS = {
        LevelControl.AttributeDefs.on_off_transition_time.name: True,
        LevelControl.AttributeDefs.on_level.name: True,
        LevelControl.AttributeDefs.on_transition_time.name: True,
        LevelControl.AttributeDefs.off_transition_time.name: True,
        LevelControl.AttributeDefs.default_move_rate.name: True,
        LevelControl.AttributeDefs.start_up_current_level.name: True,
    }

    @property
    def current_level(self) -> int | None:
        """Return cached value of the current_level attribute."""
        return self.cluster.get(LevelControl.AttributeDefs.current_level.name)

    def cluster_command(self, tsn, command_id, args):
        """Handle commands received to this cluster."""
        cmd = parse_and_log_command(self, tsn, command_id, args)

        if cmd in (
            LevelControl.ServerCommandDefs.move_to_level.name,
            LevelControl.ServerCommandDefs.move_to_level_with_on_off.name,
        ):
            self.dispatch_level_change(SIGNAL_SET_LEVEL, args[0])
        elif cmd in (
            LevelControl.ServerCommandDefs.move.name,
            LevelControl.ServerCommandDefs.move_with_on_off.name,
        ):
            # We should dim slowly -- for now, just step once
            rate = args[1]
            if args[0] == 0xFF:
                rate = 10  # Should read default move rate
            self.dispatch_level_change(SIGNAL_MOVE_LEVEL, -rate if args[0] else rate)
        elif cmd in (
            LevelControl.ServerCommandDefs.step.name,
            LevelControl.ServerCommandDefs.step_with_on_off.name,
        ):
            # Step (technically may change on/off)
            self.dispatch_level_change(
                SIGNAL_MOVE_LEVEL, -args[1] if args[0] else args[1]
            )

    def _handle_attribute_updated_event(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle attribute updates on this cluster."""
        self.debug(
            "received attribute: %s update with value: %s",
            event.attribute_id,
            event.value,
        )
        if event.attribute_id == self.CURRENT_LEVEL:
            self.dispatch_level_change(SIGNAL_SET_LEVEL, event.value)
        else:
            super()._handle_attribute_updated_event(event)

    def dispatch_level_change(self, command, level):
        """Dispatch level change."""
        self.emit(
            CLUSTER_HANDLER_LEVEL_CHANGED,
            LevelChangeEvent(
                level=level,
                event=f"cluster_handler_{command}",
            ),
        )


@registries.CLUSTER_HANDLER_REGISTRY.register(MultistateInput.cluster_id)
class MultistateInputClusterHandler(ClusterHandler):
    """Multistate Input cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=MultistateInput.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(MultistateOutput.cluster_id)
class MultistateOutputClusterHandler(ClusterHandler):
    """Multistate Output cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=MultistateOutput.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(MultistateValue.cluster_id)
class MultistateValueClusterHandler(ClusterHandler):
    """Multistate Value cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=MultistateValue.AttributeDefs.present_value.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(OnOff.cluster_id)
class OnOffClientClusterHandler(ClientClusterHandler):
    """OnOff client cluster handler.

    Server attribute cache sync from incoming commands lives on the
    `OnOffClientCacheSync` virtual entity now.
    """


@registries.BINDABLE_CLUSTERS.register(OnOff.cluster_id)
@registries.CLUSTER_HANDLER_REGISTRY.register(OnOff.cluster_id)
class OnOffClusterHandler(ClusterHandler):
    """Cluster handler for the OnOff Zigbee cluster."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=OnOff.AttributeDefs.on_off.name, config=REPORT_CONFIG_IMMEDIATE
        ),
    )
    ZCL_INIT_ATTRS = {
        OnOff.AttributeDefs.start_up_on_off.name: True,
    }

    @classmethod
    def matches(cls, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> bool:
        """Filter the cluster match for specific devices."""
        return not (
            cluster.endpoint.device.manufacturer == "Konke"
            and cluster.endpoint.device.model
            in ("3AFE280100510001", "3AFE170100510001")
        )

    @property
    def on_off(self) -> bool | None:
        """Return cached value of on/off attribute."""
        return self.cluster.get(OnOff.AttributeDefs.on_off.name)

    async def turn_on(self) -> None:
        """Turn the on off cluster on."""
        result = await self.on()
        if result[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to turn on: {result[1]}")
        self.cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.true)

    async def turn_off(self) -> None:
        """Turn the on off cluster off."""
        result = await self.off()
        if result[1] is not Status.SUCCESS:
            raise ZHAException(f"Failed to turn off: {result[1]}")
        self.cluster.update_attribute(OnOff.AttributeDefs.on_off.id, t.Bool.false)

    async def async_update(self):
        """Initialize cluster handler."""
        if self.cluster.is_client:
            return
        from_cache = not self._endpoint.device.is_mains_powered
        self.debug("attempting to update onoff state - from cache: %s", from_cache)
        await self.get_attribute_value(
            OnOff.AttributeDefs.on_off.name, from_cache=from_cache
        )


@registries.CLUSTER_HANDLER_REGISTRY.register(OnOffConfiguration.cluster_id)
class OnOffConfigurationClusterHandler(ClusterHandler):
    """OnOff Configuration cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(Ota.cluster_id)
class OtaClusterHandler(ClusterHandler):
    """OTA cluster handler."""

    BIND: bool = False

    # Some devices have this cluster in the wrong collection (e.g. Third Reality)
    ZCL_INIT_ATTRS = {
        Ota.AttributeDefs.current_file_version.name: True,
    }

    @property
    def current_file_version(self) -> int | None:
        """Return cached value of current_file_version attribute."""
        return self.cluster.get(Ota.AttributeDefs.current_file_version.name)


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(Ota.cluster_id)
class OtaClientClusterHandler(ClientClusterHandler):
    """OTA client cluster handler.

    The `current_file_version` cache update on `query_next_image` lives on the
    `OtaCurrentFileVersionCache` virtual entity now.
    """

    BIND: bool = False

    ZCL_INIT_ATTRS = {
        Ota.AttributeDefs.current_file_version.name: True,
    }

    @property
    def current_file_version(self) -> int | None:
        """Return cached value of current_file_version attribute."""
        return self.cluster.get(Ota.AttributeDefs.current_file_version.name)

    def _handle_attribute_updated_event(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle an attribute updated on this cluster."""
        # We intentionally avoid the `ClientClusterHandler` attribute update handler:
        # it emits a logbook event on every update, which pollutes the logbook
        ClusterHandler._handle_attribute_updated_event(self, event)


@registries.CLUSTER_HANDLER_REGISTRY.register(Partition.cluster_id)
class PartitionClusterHandler(ClusterHandler):
    """Partition cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(PowerConfiguration.cluster_id)
class PowerConfigurationClusterHandler(ClusterHandler):
    """Cluster handler for the zigbee power configuration cluster.

    `battery_size` / `battery_quantity` reads are declared on the `Battery`
    sensor entity now.
    """

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=PowerConfiguration.AttributeDefs.battery_voltage.name,
            config=REPORT_CONFIG_BATTERY_SAVE,
        ),
        AttrReportConfig(
            attr=PowerConfiguration.AttributeDefs.battery_percentage_remaining.name,
            config=REPORT_CONFIG_BATTERY_SAVE,
        ),
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(PowerProfile.cluster_id)
class PowerProfileClusterHandler(ClusterHandler):
    """Power Profile cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(RSSILocation.cluster_id)
class RSSILocationClusterHandler(ClusterHandler):
    """RSSI Location cluster handler."""


@registries.CLIENT_CLUSTER_HANDLER_REGISTRY.register(Scenes.cluster_id)
class ScenesClientClusterHandler(ClientClusterHandler):
    """Scenes cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(Scenes.cluster_id)
class ScenesClusterHandler(ClusterHandler):
    """Scenes cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(Time.cluster_id)
class TimeClusterHandler(ClusterHandler):
    """Time cluster handler."""
