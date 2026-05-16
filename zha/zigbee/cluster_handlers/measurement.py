"""Measurement cluster handlers module for Zigbee Home Automation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import zigpy.zcl
from zigpy.zcl.clusters.measurement import (
    IlluminanceLevelSensing,
    OccupancySensing,
)

from zha.zigbee.cluster_handlers import AttrReportConfig, ClusterHandler, registries
from zha.zigbee.cluster_handlers.const import (
    REPORT_CONFIG_DEFAULT,
    REPORT_CONFIG_IMMEDIATE,
)
from zha.zigbee.cluster_handlers.helpers import (
    is_hue_motion_sensor,
    is_sonoff_presence_sensor,
)

if TYPE_CHECKING:
    from zha.zigbee.endpoint import Endpoint


@registries.CLUSTER_HANDLER_REGISTRY.register(IlluminanceLevelSensing.cluster_id)
class IlluminanceLevelSensingClusterHandler(ClusterHandler):
    """Illuminance Level Sensing cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=IlluminanceLevelSensing.AttributeDefs.level_status.name,
            config=REPORT_CONFIG_DEFAULT,
        ),
    )


@registries.CLUSTER_HANDLER_REGISTRY.register(OccupancySensing.cluster_id)
class OccupancySensingClusterHandler(ClusterHandler):
    """Occupancy Sensing cluster handler."""

    REPORT_CONFIG = (
        AttrReportConfig(
            attr=OccupancySensing.AttributeDefs.occupancy.name,
            config=REPORT_CONFIG_IMMEDIATE,
        ),
    )
    ZCL_INIT_ATTRS = {
        "pir_o_to_u_delay": True,
        "pir_u_to_o_delay": True,
    }

    def __init__(self, cluster: zigpy.zcl.Cluster, endpoint: Endpoint) -> None:
        """Initialize Occupancy cluster handler."""
        super().__init__(cluster, endpoint)
        if is_hue_motion_sensor(self):
            self.ZCL_INIT_ATTRS = self.ZCL_INIT_ATTRS.copy()
            self.ZCL_INIT_ATTRS["sensitivity"] = True
        if is_sonoff_presence_sensor(self):
            self.ZCL_INIT_ATTRS = self.ZCL_INIT_ATTRS.copy()
            self.ZCL_INIT_ATTRS["ultrasonic_o_to_u_delay"] = True
            self.ZCL_INIT_ATTRS["ultrasonic_u_to_o_threshold"] = True
