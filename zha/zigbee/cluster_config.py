"""Cluster configuration aggregation for ZHA entities."""

from __future__ import annotations

from dataclasses import dataclass, field
import functools
import logging
from typing import TYPE_CHECKING

import zigpy.exceptions
import zigpy.util
import zigpy.zcl
from zigpy.zcl import (
    AttributeReportingConfiguredEvent,
    AttributeUnsupportedEvent,
    ReportingConfig,
)
from zigpy.zcl.foundation import Status, ZCLAttributeDef

from zha.application.const import (
    ZHA_CLUSTER_BIND_EVENT,
    ZHA_CLUSTER_CONFIGURE_REPORTING_EVENT,
)
from zha.application.platforms import AttrConfig, ZclPlatformEntity
from zha.zigbee.applied_config import (
    AppliedConfigRecorder,
    ConfigResult,
    quirk_replaces,
)

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
    reporting_override: bool = False

    def merge(self, config: AttrConfig) -> None:
        """Merge another attribute config.

        A fresh read wins over a cached one. For reporting, the tightest config wins,
        except that overriding configs (`AttrConfig.reporting_override`) replace
        non-overriding ones entirely and are only merged with other overriding configs.
        """
        self.read_on_startup = self.read_on_startup or config.read_on_startup

        if config.reporting is None:
            return

        if config.reporting_override and not self.reporting_override:
            # First overriding config: discard whatever the defaults merged to
            self.reporting = config.reporting
            self.reporting_override = True
        elif self.reporting_override and not config.reporting_override:
            # Non-overriding configs cannot tighten an override
            return
        elif self.reporting is None:
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
        if not isinstance(entity, ZclPlatformEntity):
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


def _note_announced(
    announced: dict[tuple[int, int | None], Status],
    status: Status,
    event: AttributeReportingConfiguredEvent | AttributeUnsupportedEvent,
) -> None:
    """Collect an attribute outcome zigpy announces while configuring reporting."""
    announced[(event.attribute_id, event.manufacturer_code)] = status


def _effective_manufacturer_code(
    cluster: zigpy.zcl.Cluster, attr_def: ZCLAttributeDef
) -> int | None:
    """Return the manufacturer code zigpy configures an attribute's reporting with."""
    return cluster._get_effective_manufacturer_code(attr_def)  # noqa: SLF001


def _record_binding(
    recorder: AppliedConfigRecorder,
    device: Device,
    endpoint_id: int,
    agg: AggregatedClusterConfig,
    is_server: bool,
    result: ConfigResult,
) -> None:
    """Record ZHA's bind of a cluster. A failure is logged, never raised."""
    if not recorder.enabled:
        return

    try:
        # The destination zigpy's bind uses, unless a quirk replaces it
        destination = device.device.application.get_dst_address(agg.cluster)
    except Exception:  # pylint: disable=broad-except
        recorder.note_incomplete()
        _LOGGER.exception(
            "[%s] Failed to resolve the binding destination of cluster %s",
            agg.cluster.endpoint.device.ieee,
            agg.cluster.ep_attribute,
        )
        return

    try:
        recorder.record_binding(
            endpoint_id=endpoint_id,
            cluster_id=agg.cluster.cluster_id,
            destination=destination,
            operation="bind",
            origin="zha",
            result=result,
            side="server" if is_server else "client",
            quirk_handler=quirk_replaces(agg.cluster, "bind"),
        )
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception(
            "[%s] Failed to record binding of cluster %s",
            agg.cluster.endpoint.device.ieee,
            agg.cluster.ep_attribute,
        )


def _record_reporting(
    recorder: AppliedConfigRecorder,
    agg: AggregatedClusterConfig,
    reporting_attrs: dict[ZCLAttributeDef, ReportingConfig],
    manufacturer_codes: dict[ZCLAttributeDef, int | None],
    results: dict[ZCLAttributeDef, ConfigResult],
) -> None:
    """Record ZHA's reporting configuration of a cluster, one attribute at a time.

    A failure is logged and does not stop the other attributes. An attribute whose
    manufacturer code could not be determined has no key and is not recorded, and the
    run then marks nothing stale.
    """
    if not recorder.enabled:
        return

    quirk_handler = quirk_replaces(
        agg.cluster, "configure_reporting_multiple", "_configure_reporting"
    )

    for attr_def, cfg in reporting_attrs.items():
        if attr_def not in manufacturer_codes:
            recorder.note_incomplete()
            continue

        try:
            recorder.record_reporting(
                cluster=agg.cluster,
                attr_def=attr_def,
                manufacturer_code=manufacturer_codes[attr_def],
                desired=cfg,
                result=results[attr_def],
                quirk_handler=quirk_handler,
            )
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "[%s] Failed to record reporting configuration of %s on cluster %s",
                agg.cluster.endpoint.device.ieee,
                attr_def.name,
                agg.cluster.ep_attribute,
            )


async def configure_cluster_configs(
    device: Device,
    configs: dict[tuple[int, int, bool], AggregatedClusterConfig],
    *,
    mark_stale: bool = True,
) -> None:
    """Execute binding, reporting, and post-bind hooks from aggregated configs.

    Emits `ClusterBindEvent` and `ClusterConfigureReportingEvent` on `device`
    so listeners (HA Core diagnostics, reconfigure dialog) can observe the
    per-cluster outcomes, and records each binding and reporting configuration with
    its status in the device's store (`zha.zigbee.applied_config`). Recording never
    fails the configuration. Pass `mark_stale=False` when `configs` may be incomplete
    (an entity failed to be created), so missing items are not marked stale.
    """
    # Imported lazily to avoid a circular import.
    from zha.zigbee.device import ClusterBindEvent, ClusterConfigureReportingEvent  # noqa: PLC0415

    recorder = AppliedConfigRecorder(device.device)

    for (endpoint_id, _cluster_id, is_server), agg in configs.items():
        if agg.bind:
            try:
                res = await agg.cluster.bind()
                success = res[0] == 0
                result = ConfigResult.from_status(res[0])
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
                result = ConfigResult.from_exception(ex)

            _record_binding(recorder, device, endpoint_id, agg, is_server, result)

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

            results: dict[ZCLAttributeDef, ConfigResult] = {}
            manufacturer_codes: dict[ZCLAttributeDef, int | None] = {}

            for attr_def in reporting_attrs:
                try:
                    manufacturer_codes[attr_def] = _effective_manufacturer_code(
                        agg.cluster, attr_def
                    )
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.debug(
                        "[%s] No manufacturer code for %s",
                        agg.cluster.endpoint.device.ieee,
                        attr_def.name,
                        exc_info=True,
                    )

            # zigpy sends one request per manufacturer code (and more if they do not
            # fit in one frame) and, once a manufacturer code's requests are done,
            # announces each attribute it configured and each the device reported as
            # unsupported. When a later request raises, the announcements tell what
            # the earlier requests achieved. Other per-attribute statuses are not
            # announced. The same attribute ID can occur under several manufacturer
            # codes, so announcements are matched on both. The listeners are attached
            # only around the request; zigpy also announces unsupported attributes
            # found by a read, so a read of this cluster running concurrently could
            # still be taken for the outcome of an attribute whose request raised.
            announced: dict[tuple[int, int | None], Status] = {}
            unsubscribes = [
                agg.cluster.on_event(
                    AttributeReportingConfiguredEvent.event_type,
                    functools.partial(_note_announced, announced, Status.SUCCESS),
                ),
                agg.cluster.on_event(
                    AttributeUnsupportedEvent.event_type,
                    functools.partial(
                        _note_announced, announced, Status.UNSUPPORTED_ATTRIBUTE
                    ),
                ),
            ]

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

                for attr_def in reporting_attrs:
                    results[attr_def] = (
                        ConfigResult.from_status(res[attr_def])
                        if res and attr_def in res
                        else ConfigResult(error="NoStatus")
                    )
            except Exception as ex:
                _LOGGER.debug(
                    "[%s] Failed to configure reporting on cluster %s: %s",
                    agg.cluster.endpoint.device.ieee,
                    agg.cluster.ep_attribute,
                    ex,
                )
                for attr_def in reporting_attrs:
                    key = (attr_def.id, manufacturer_codes.get(attr_def))

                    if attr_def in manufacturer_codes and key in announced:
                        event_data[attr_def.name]["status"] = announced[key].name
                        results[attr_def] = ConfigResult.from_status(announced[key])
                    else:
                        event_data[attr_def.name]["status"] = Status.FAILURE.name
                        results[attr_def] = ConfigResult.from_exception(ex)
            finally:
                for unsubscribe in unsubscribes:
                    unsubscribe()

            _record_reporting(
                recorder, agg, reporting_attrs, manufacturer_codes, results
            )

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

    if mark_stale:
        try:
            recorder.mark_stale()
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception(
                "[%s] Failed to mark stale configuration records", device.ieee
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
