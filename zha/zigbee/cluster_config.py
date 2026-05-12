"""Cluster configuration aggregation for ZHA entities."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING

import zigpy.exceptions
import zigpy.util
import zigpy.zcl
from zigpy.typing import UNDEFINED
from zigpy.zcl import ReportingConfig

from zha.application.platforms import AttrConfig
from zha.zigbee.cluster_handlers.const import CLUSTER_READS_PER_REQ

if TYPE_CHECKING:
    from collections.abc import Iterable

    from zha.application.platforms import BaseEntity

_LOGGER = logging.getLogger(__name__)
RETRYABLE_REQUEST_DECORATOR = zigpy.util.retryable_request(tries=3)


@dataclass
class AggregatedAttrConfig:
    """Aggregated attribute configuration from multiple entities."""

    read_on_startup: bool = False
    reporting: tuple[int, int, int | float] | None = None

    def merge(self, config: AttrConfig) -> None:
        """Merge another attribute config (fresh read and tightest reporting win)."""
        self.read_on_startup = self.read_on_startup or config.read_on_startup

        if config.reporting is not None:
            if self.reporting is None:
                self.reporting = config.reporting
            else:
                self.reporting = (
                    min(self.reporting[0], config.reporting[0]),
                    min(self.reporting[1], config.reporting[1]),
                    min(self.reporting[2], config.reporting[2]),
                )


@dataclass
class AggregatedClusterConfig:
    """Aggregated cluster configuration from multiple entities."""

    cluster: zigpy.zcl.Cluster
    bind: bool = False
    attributes: dict[str, AggregatedAttrConfig] = field(default_factory=dict)


def aggregate_cluster_configs(
    entities: Iterable[BaseEntity],
) -> dict[tuple[int, int], AggregatedClusterConfig]:
    """Aggregate cluster configurations from entities.

    Returns a dict keyed by (endpoint_id, cluster_id) with merged configs.
    """
    result: dict[tuple[int, int], AggregatedClusterConfig] = {}

    for entity in entities:
        if not hasattr(entity, "_server_cluster_config"):
            continue

        if not entity._server_cluster_config and not entity._client_cluster_config:
            continue

        for cluster_id, config in entity._server_cluster_config.items():
            cluster = entity.endpoint.zigpy_endpoint.in_clusters.get(cluster_id)
            if cluster is None:
                continue

            key = (entity.endpoint.id, cluster_id)
            if key not in result:
                result[key] = AggregatedClusterConfig(cluster=cluster)

            agg = result[key]
            agg.bind = agg.bind or config.bind

            for attr_def, attr_config in config.attributes.items():
                if attr_def.name not in agg.attributes:
                    agg.attributes[attr_def.name] = AggregatedAttrConfig()
                agg.attributes[attr_def.name].merge(attr_config)

        for cluster_id, config in entity._client_cluster_config.items():
            cluster = entity.endpoint.zigpy_endpoint.out_clusters.get(cluster_id)
            if cluster is None:
                continue

            key = (entity.endpoint.id, cluster_id)
            if key not in result:
                result[key] = AggregatedClusterConfig(cluster=cluster)

            agg = result[key]
            agg.bind = agg.bind or config.bind

            for attr_def, attr_config in config.attributes.items():
                if attr_def.name not in agg.attributes:
                    agg.attributes[attr_def.name] = AggregatedAttrConfig()
                agg.attributes[attr_def.name].merge(attr_config)

    return result


async def configure_cluster_configs(
    configs: dict[tuple[int, int], AggregatedClusterConfig],
    manufacturer_code: int | None,
) -> None:
    """Execute binding and reporting configuration from aggregated configs."""
    for agg in configs.values():
        if agg.bind:
            try:
                res = await RETRYABLE_REQUEST_DECORATOR(agg.cluster.bind)()
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

        reporting_attrs = {}
        for attr_name, attr_config in agg.attributes.items():
            if attr_config.reporting is None:
                continue
            attr_def = agg.cluster.find_attribute(attr_name)
            reporting_attrs[attr_def] = ReportingConfig(
                min_interval=attr_config.reporting[0],
                max_interval=attr_config.reporting[1],
                reportable_change=attr_config.reporting[2],
            )

        if not reporting_attrs:
            continue

        try:
            res = await RETRYABLE_REQUEST_DECORATOR(
                agg.cluster.configure_reporting_multiple
            )(reporting_attrs)
            _LOGGER.debug(
                "[%s] Configured reporting for %s on cluster %s: %s",
                agg.cluster.endpoint.device.ieee,
                list(reporting_attrs.keys()),
                agg.cluster.ep_attribute,
                res,
            )
        except Exception as ex:
            _LOGGER.debug(
                "[%s] Failed to configure reporting on cluster %s: %s",
                agg.cluster.endpoint.device.ieee,
                agg.cluster.ep_attribute,
                ex,
            )


async def _read_attributes_chunked(
    cluster: zigpy.zcl.Cluster,
    attrs: list[str],
    *,
    allow_cache: bool,
    only_cache: bool,
) -> None:
    """Read attributes in chunks, matching legacy cluster handler behavior."""
    chunk = attrs[:CLUSTER_READS_PER_REQ]
    rest = attrs[CLUSTER_READS_PER_REQ:]
    while chunk:
        try:
            await cluster.read_attributes(
                chunk,
                allow_cache=allow_cache,
                only_cache=only_cache,
                manufacturer=UNDEFINED,
            )
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.debug(
                "[%s] Failed to read attributes %s from cluster %s: %s",
                cluster.endpoint.device.ieee,
                chunk,
                cluster.ep_attribute,
                ex,
            )
        chunk = rest[:CLUSTER_READS_PER_REQ]
        rest = rest[CLUSTER_READS_PER_REQ:]


async def initialize_cluster_configs(
    configs: dict[tuple[int, int], AggregatedClusterConfig],
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
            await _read_attributes_chunked(
                agg.cluster,
                cached_attrs,
                allow_cache=True,
                only_cache=from_cache,
            )

        if fresh_attrs:
            await _read_attributes_chunked(
                agg.cluster,
                fresh_attrs,
                allow_cache=from_cache,
                only_cache=from_cache,
            )
