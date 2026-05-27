"""Cluster configuration aggregation for ZHA entities."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

import zigpy.exceptions
import zigpy.util
import zigpy.zcl
from zigpy.zcl import ReportingConfig
from zigpy.zcl.foundation import Status, ZCLAttributeDef

from zha.application.const import (
    ZHA_CLUSTER_BIND_EVENT,
    ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT,
)
from zha.application.platforms import AttrConfig, PlatformEntity

if TYPE_CHECKING:
    from collections.abc import Iterable

    from zha.application.platforms import BaseEntity
    from zha.zigbee.device import Device

_LOGGER = logging.getLogger(__name__)


@dataclass
class AggregatedAttrConfig:
    """Aggregated attribute configuration from multiple entities."""

    read_on_startup: bool = False
    reporting: ReportingConfig | None = None

    def merge(self, config: AttrConfig) -> None:
        """Merge another attribute config (fresh read and tightest reporting win)."""
        self.read_on_startup = self.read_on_startup or config.read_on_startup

        if config.reporting is not None:
            if self.reporting is None:
                self.reporting = config.reporting
            else:
                self.reporting = ReportingConfig(
                    min_interval=min(
                        self.reporting.min_interval, config.reporting.min_interval
                    ),
                    max_interval=min(
                        self.reporting.max_interval, config.reporting.max_interval
                    ),
                    reportable_change=min(
                        self.reporting.reportable_change,
                        config.reporting.reportable_change,
                    ),
                )


@dataclass
class AggregatedClusterConfig:
    """Aggregated cluster configuration from multiple entities."""

    cluster: zigpy.zcl.Cluster
    bind: bool = False
    attributes: dict[str, AggregatedAttrConfig] = field(default_factory=dict)
    entities: list[BaseEntity] = field(default_factory=list)


def aggregate_cluster_configs(
    entities: Iterable[BaseEntity],
) -> dict[tuple[int, int, bool], AggregatedClusterConfig]:
    """Aggregate cluster configurations from entities.

    Returns a dict keyed by (endpoint_id, cluster_id) with merged configs.
    """
    result: dict[tuple[int, int, bool], AggregatedClusterConfig] = {}

    for entity in entities:
        if not isinstance(entity, PlatformEntity):
            continue

        if not entity._server_cluster_config and not entity._client_cluster_config:
            continue

        for cluster_id, config in entity._server_cluster_config.items():
            cluster = entity.endpoint.zigpy_endpoint.in_clusters.get(cluster_id)
            if cluster is None:
                continue

            key = (entity.endpoint.id, cluster_id, True)
            if key not in result:
                result[key] = AggregatedClusterConfig(cluster=cluster)

            agg = result[key]
            agg.bind = agg.bind or config.bind
            agg.entities.append(entity)

            for attr_def, attr_config in config.attributes.items():
                attr_name = (
                    attr_def.name if isinstance(attr_def, ZCLAttributeDef) else attr_def
                )
                if attr_name not in agg.attributes:
                    agg.attributes[attr_name] = AggregatedAttrConfig()
                agg.attributes[attr_name].merge(attr_config)

        for cluster_id, config in entity._client_cluster_config.items():
            cluster = entity.endpoint.zigpy_endpoint.out_clusters.get(cluster_id)
            if cluster is None:
                continue

            key = (entity.endpoint.id, cluster_id, False)
            if key not in result:
                result[key] = AggregatedClusterConfig(cluster=cluster)

            agg = result[key]
            agg.bind = agg.bind or config.bind
            agg.entities.append(entity)

            for attr_def, attr_config in config.attributes.items():
                attr_name = (
                    attr_def.name if isinstance(attr_def, ZCLAttributeDef) else attr_def
                )
                if attr_name not in agg.attributes:
                    agg.attributes[attr_name] = AggregatedAttrConfig()
                agg.attributes[attr_name].merge(attr_config)

    return result


async def configure_cluster_configs(
    device: Device,
    configs: dict[tuple[int, int, bool], AggregatedClusterConfig],
) -> None:
    """Execute binding, reporting, and post-bind hooks from aggregated configs.

    Emits `ClusterBindEvent` and `ClusterConfigureReportingEvent` on `device`
    so listeners (HA Core diagnostics, reconfigure dialog) can observe the
    per-cluster outcomes.
    """
    # Imported lazily to avoid a circular import.
    from zha.zigbee.device import (  # noqa: PLC0415
        ClusterBindEvent,
        ClusterConfigureReportingEvent,
    )

    for (endpoint_id, _cluster_id, _is_server), agg in configs.items():
        if agg.bind:
            try:
                res = await agg.cluster.bind()
                success = res[0] == 0
                _LOGGER.debug(
                    "[%s] Bound cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    agg.cluster.ep_attribute,
                    res[0],
                )
            except (zigpy.exceptions.ZigbeeException, TimeoutError) as ex:
                _LOGGER.debug(
                    "[%s] Failed to bind cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    agg.cluster.ep_attribute,
                    ex,
                )
                success = False

            device.emit(
                ZHA_CLUSTER_BIND_EVENT,
                ClusterBindEvent(
                    device_ieee=device.ieee,
                    endpoint_id=endpoint_id,
                    cluster_id=agg.cluster.cluster_id,
                    cluster_name=agg.cluster.name,
                    success=success,
                ),
            )

        reporting_attrs = {}
        for attr_name, attr_config in agg.attributes.items():
            if attr_config.reporting is None:
                continue
            attr_def = agg.cluster.find_attribute(attr_name)
            reporting_attrs[attr_def] = attr_config.reporting

        if reporting_attrs:
            event_data = {
                attr_def.name: {
                    "min": cfg.min_interval,
                    "max": cfg.max_interval,
                    "id": attr_def.id,
                    "name": attr_def.name,
                    "change": cfg.reportable_change,
                    "status": None,
                }
                for attr_def, cfg in reporting_attrs.items()
            }

            try:
                res = await agg.cluster.configure_reporting_multiple(reporting_attrs)
                _LOGGER.debug(
                    "[%s] Configured reporting for %s on cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    list(reporting_attrs.keys()),
                    agg.cluster.ep_attribute,
                    res,
                )
                if not res:
                    for attr_def in reporting_attrs:
                        event_data[attr_def.name]["status"] = Status.FAILURE.name
                else:
                    for attr_def, status in res.items():
                        event_data[attr_def.name]["status"] = status.name
            except Exception as ex:
                _LOGGER.debug(
                    "[%s] Failed to configure reporting on cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    agg.cluster.ep_attribute,
                    ex,
                )
                for attr_def in reporting_attrs:
                    event_data[attr_def.name]["status"] = Status.FAILURE.name

            device.emit(
                ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT,
                ClusterConfigureReportingEvent(
                    device_ieee=device.ieee,
                    endpoint_id=endpoint_id,
                    cluster_id=agg.cluster.cluster_id,
                    cluster_name=agg.cluster.name,
                    attributes=event_data,
                ),
            )

        for entity in agg.entities:
            try:
                await entity.async_configure_cluster(agg.cluster)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug(
                    "[%s] async_configure_cluster on %s raised",
                    agg.cluster.endpoint.device.ieee,
                    type(entity).__name__,
                    exc_info=True,
                )


async def initialize_cluster_configs(
    configs: dict[tuple[int, int, bool], AggregatedClusterConfig],
    from_cache: bool,
) -> None:
    """Read initial attribute values from aggregated configs."""
    for agg in configs.values():
        cached_attrs = [
            attr_name
            for attr_name, attr_config in agg.attributes.items()
            if not attr_config.read_on_startup
        ]
        fresh_attrs = [
            attr_name
            for attr_name, attr_config in agg.attributes.items()
            if attr_config.read_on_startup
        ]

        if cached_attrs:
            try:
                await agg.cluster.read_attributes(
                    cached_attrs, allow_cache=True, only_cache=from_cache
                )
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.debug(
                    "[%s] Failed to read attributes %s from cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    cached_attrs,
                    agg.cluster.ep_attribute,
                    ex,
                )

        if fresh_attrs:
            try:
                await agg.cluster.read_attributes(
                    fresh_attrs, allow_cache=from_cache, only_cache=from_cache
                )
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.debug(
                    "[%s] Failed to read attributes %s from cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    fresh_attrs,
                    agg.cluster.ep_attribute,
                    ex,
                )

        for entity in agg.entities:
            try:
                await entity.async_initialize_cluster(agg.cluster)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.debug(
                    "[%s] async_initialize_cluster on %s raised",
                    agg.cluster.endpoint.device.ieee,
                    type(entity).__name__,
                    exc_info=True,
                )
