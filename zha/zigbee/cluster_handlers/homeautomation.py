"""Home automation cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

import enum

from zigpy.zcl.clusters.homeautomation import (
    ApplianceEventAlerts,
    ApplianceIdentification,
    ApplianceStatistics,
    Diagnostic,
    ElectricalMeasurement,
    MeterIdentification,
)

from zha.zigbee.cluster_handlers import AttrReportConfig, ClusterHandler, registries
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT,
    REPORT_CONFIG_IMMEDIATE,
    REPORT_CONFIG_OP,
)


@registries.CLUSTER_HANDLER_REGISTRY.register(ApplianceEventAlerts.cluster_id)
class ApplianceEventAlertsClusterHandler(ClusterHandler):
    """Appliance Event Alerts cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(ApplianceIdentification.cluster_id)
class ApplianceIdentificationClusterHandler(ClusterHandler):
    """Appliance Identification cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(ApplianceStatistics.cluster_id)
class ApplianceStatisticsClusterHandler(ClusterHandler):
    """Appliance Statistics cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(Diagnostic.cluster_id)
class DiagnosticClusterHandler(ClusterHandler):
    """Diagnostic cluster handler."""


@registries.CLUSTER_HANDLER_REGISTRY.register(ElectricalMeasurement.cluster_id)
class ElectricalMeasurementClusterHandler(ClusterHandler):
    """Cluster handler that polls active power level."""

    CLUSTER_HANDLER_NAME = CLUSTER_HANDLER_ELECTRICAL_MEASUREMENT

    class MeasurementType(enum.IntFlag):
        """Measurement types."""

        ACTIVE_MEASUREMENT = 1
        REACTIVE_MEASUREMENT = 2
        APPARENT_MEASUREMENT = 4
        PHASE_A_MEASUREMENT = 8
        PHASE_B_MEASUREMENT = 16
        PHASE_C_MEASUREMENT = 32
        DC_MEASUREMENT = 64
        HARMONICS_MEASUREMENT = 128
        POWER_QUALITY_MEASUREMENT = 256

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_voltage_multiplier.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_voltage_divisor.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_current_multiplier.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_current_divisor.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_power_multiplier.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_power_divisor.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.power_multiplier.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.power_divisor.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.active_power.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.active_power_ph_b.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.active_power_ph_c.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.apparent_power.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.rms_current.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.rms_current_ph_b.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.rms_current_ph_c.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.rms_voltage.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.rms_voltage_ph_b.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.rms_voltage_ph_c.name,
            config=REPORT_CONFIG_OP,
        ),
        AttrReportConfig(
            attr=ElectricalMeasurement.AttributeDefs.ac_frequency.name,
            config=REPORT_CONFIG_OP,
        ),
    )
    ZCL_POLLING_ATTRS = [
        ElectricalMeasurement.AttributeDefs.ac_frequency.name,
        ElectricalMeasurement.AttributeDefs.ac_frequency_max.name,
        ElectricalMeasurement.AttributeDefs.active_power.name,
        ElectricalMeasurement.AttributeDefs.active_power_ph_b.name,
        ElectricalMeasurement.AttributeDefs.active_power_ph_c.name,
        ElectricalMeasurement.AttributeDefs.active_power_max.name,
        ElectricalMeasurement.AttributeDefs.active_power_max_ph_b.name,
        ElectricalMeasurement.AttributeDefs.active_power_max_ph_c.name,
        ElectricalMeasurement.AttributeDefs.apparent_power.name,
        ElectricalMeasurement.AttributeDefs.power_factor.name,
        ElectricalMeasurement.AttributeDefs.power_factor_ph_b.name,
        ElectricalMeasurement.AttributeDefs.power_factor_ph_c.name,
        ElectricalMeasurement.AttributeDefs.rms_current.name,
        ElectricalMeasurement.AttributeDefs.rms_current_ph_b.name,
        ElectricalMeasurement.AttributeDefs.rms_current_ph_c.name,
        ElectricalMeasurement.AttributeDefs.rms_current_max.name,
        ElectricalMeasurement.AttributeDefs.rms_current_max_ph_b.name,
        ElectricalMeasurement.AttributeDefs.rms_current_max_ph_c.name,
        ElectricalMeasurement.AttributeDefs.rms_voltage.name,
        ElectricalMeasurement.AttributeDefs.rms_voltage_ph_b.name,
        ElectricalMeasurement.AttributeDefs.rms_voltage_ph_c.name,
        ElectricalMeasurement.AttributeDefs.rms_voltage_max.name,
        ElectricalMeasurement.AttributeDefs.rms_voltage_max_ph_b.name,
        ElectricalMeasurement.AttributeDefs.rms_voltage_max_ph_c.name,
    ]
    ZCL_INIT_ATTRS = {
        ElectricalMeasurement.AttributeDefs.ac_frequency_divisor.name: True,
        ElectricalMeasurement.AttributeDefs.ac_frequency_max.name: True,
        ElectricalMeasurement.AttributeDefs.ac_frequency_multiplier.name: True,
        ElectricalMeasurement.AttributeDefs.active_power_max.name: True,
        ElectricalMeasurement.AttributeDefs.active_power_max_ph_b.name: True,
        ElectricalMeasurement.AttributeDefs.active_power_max_ph_c.name: True,
        ElectricalMeasurement.AttributeDefs.measurement_type.name: True,
        ElectricalMeasurement.AttributeDefs.power_factor.name: True,
        ElectricalMeasurement.AttributeDefs.power_factor_ph_b.name: True,
        ElectricalMeasurement.AttributeDefs.power_factor_ph_c.name: True,
        ElectricalMeasurement.AttributeDefs.rms_current_max.name: True,
        ElectricalMeasurement.AttributeDefs.rms_current_max_ph_b.name: True,
        ElectricalMeasurement.AttributeDefs.rms_current_max_ph_c.name: True,
        ElectricalMeasurement.AttributeDefs.rms_voltage_max.name: True,
        ElectricalMeasurement.AttributeDefs.rms_voltage_max_ph_b.name: True,
        ElectricalMeasurement.AttributeDefs.rms_voltage_max_ph_c.name: True,
    }

    async def async_update(self):
        """Retrieve latest state."""
        self.debug("async_update")

        # This is a polling cluster handler. Don't allow cache.
        attrs = [
            attr
            for attr in self.ZCL_POLLING_ATTRS
            if attr not in self.cluster.unsupported_attributes
        ]
        await self.get_attributes(attrs, from_cache=False, only_cache=False)

    @property
    def ac_current_divisor(self) -> int:
        """Return ac current divisor."""
        return (
            self.cluster.get(
                ElectricalMeasurement.AttributeDefs.ac_current_divisor.name
            )
            or 1
        )

    @property
    def ac_current_multiplier(self) -> int:
        """Return ac current multiplier."""
        return (
            self.cluster.get(
                ElectricalMeasurement.AttributeDefs.ac_current_multiplier.name
            )
            or 1
        )

    @property
    def ac_voltage_divisor(self) -> int:
        """Return ac voltage divisor."""
        return (
            self.cluster.get(
                ElectricalMeasurement.AttributeDefs.ac_voltage_divisor.name
            )
            or 1
        )

    @property
    def ac_voltage_multiplier(self) -> int:
        """Return ac voltage multiplier."""
        return (
            self.cluster.get(
                ElectricalMeasurement.AttributeDefs.ac_voltage_multiplier.name
            )
            or 1
        )

    @property
    def ac_frequency_divisor(self) -> int:
        """Return ac frequency divisor."""
        return (
            self.cluster.get(
                ElectricalMeasurement.AttributeDefs.ac_frequency_divisor.name
            )
            or 1
        )

    @property
    def ac_frequency_multiplier(self) -> int:
        """Return ac frequency multiplier."""
        return (
            self.cluster.get(
                ElectricalMeasurement.AttributeDefs.ac_frequency_multiplier.name
            )
            or 1
        )

    @property
    def ac_power_divisor(self) -> int:
        """Return active power divisor."""
        return self.cluster.get(
            ElectricalMeasurement.AttributeDefs.ac_power_divisor.name,
            self.cluster.get(ElectricalMeasurement.AttributeDefs.power_divisor.name)
            or 1,
        )

    @property
    def ac_power_multiplier(self) -> int:
        """Return active power divisor."""
        return self.cluster.get(
            ElectricalMeasurement.AttributeDefs.ac_power_multiplier.name,
            self.cluster.get(ElectricalMeasurement.AttributeDefs.power_multiplier.name)
            or 1,
        )

    @property
    def measurement_type(self) -> str | None:
        """Return Measurement type."""
        if (
            meas_type := self.cluster.get(
                ElectricalMeasurement.AttributeDefs.measurement_type.name
            )
        ) is None:
            return None

        meas_type = self.MeasurementType(meas_type)
        return ", ".join(
            m.name
            for m in self.MeasurementType
            if m in meas_type and m.name is not None
        )


@registries.CLUSTER_HANDLER_REGISTRY.register(MeterIdentification.cluster_id)
class MeterIdentificationClusterHandler(ClusterHandler):
    """Metering Identification cluster handler."""
