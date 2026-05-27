"""Device discovery functions for Zigbee Home Automation."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
import functools
import itertools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.quirks.v2 import (
    BinarySensorMetadata,
    CustomDeviceV2,
    NumberMetadata,
    SwitchMetadata,
    WriteAttributeButtonMetadata,
    ZCLCommandButtonMetadata,
    ZCLEnumMetadata,
    ZCLSensorMetadata,
)
from zigpy.state import State
from zigpy.zcl import Cluster, ClusterType, ReportingConfig

from zha.application import Platform, const as zha_const
from zha.application.platforms import (  # noqa: F401 pylint: disable=unused-import
    ENTITY_REGISTRY,
    GROUP_ENTITY_REGISTRY,
    AttrConfig,
    BaseEntity,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    PlatformFeatureGroup,
    alarm_control_panel,
    binary_sensor,
    button,
    climate,
    cover,
    device_tracker,
    fan,
    light,
    lock,
    number,
    select,
    sensor,
    siren,
    switch,
    update,
    virtual,
)
from zha.zigbee.group import Group

if TYPE_CHECKING:
    from zha.application.platforms import GroupEntity
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)

PLATFORMS = (
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.DEVICE_TRACKER,
    Platform.FAN,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SIREN,
    Platform.SWITCH,
    Platform.UPDATE,
)

GROUP_PLATFORMS = (
    Platform.FAN,
    Platform.LIGHT,
    Platform.SWITCH,
)


def _pick_primary_cluster(endpoint: Endpoint, match: ClusterMatch) -> Cluster | None:
    """Pick the primary cluster for an entity from a ClusterMatch."""
    if match.server_clusters:
        cluster_id = min(match.server_clusters)
        return endpoint.zigpy_endpoint.in_clusters.get(cluster_id)
    if match.client_clusters:
        cluster_id = min(match.client_clusters)
        return endpoint.zigpy_endpoint.out_clusters.get(cluster_id)
    for cluster_id in sorted(match.optional_server_clusters):
        if cluster_id in endpoint.zigpy_endpoint.in_clusters:
            return endpoint.zigpy_endpoint.in_clusters[cluster_id]
    for cluster_id in sorted(match.optional_client_clusters):
        if cluster_id in endpoint.zigpy_endpoint.out_clusters:
            return endpoint.zigpy_endpoint.out_clusters[cluster_id]
    return None


QUIRKS_ENTITY_META_TO_ENTITY_CLASS = {
    (Platform.BUTTON, WriteAttributeButtonMetadata): button.WriteAttributeButton,
    (Platform.BUTTON, ZCLCommandButtonMetadata): button.Button,
    (Platform.BINARY_SENSOR, BinarySensorMetadata): binary_sensor.BinarySensor,
    (Platform.SENSOR, ZCLEnumMetadata): sensor.EnumSensor,
    (Platform.SENSOR, ZCLSensorMetadata): sensor.Sensor,
    (Platform.SELECT, ZCLEnumMetadata): select.ZCLEnumSelectEntity,
    (Platform.NUMBER, NumberMetadata): number.NumberConfigurationEntity,
    (Platform.SWITCH, SwitchMetadata): switch.ConfigurableAttributeSwitch,
}


def ignore_exceptions_during_iteration[**P, T](
    func: Callable[P, Iterator[T]],
) -> Callable[P, Iterator[T]]:
    """Ignore exceptions during iteration for wrapped function."""

    @functools.wraps(func)
    def inner(*args: P.args, **kwargs: P.kwargs) -> Iterator[T]:
        iterator = func(*args, **kwargs)
        while True:
            try:
                yield next(iterator)
            except StopIteration:
                break
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Failed to create entity during discovery")

    return inner


@ignore_exceptions_during_iteration
def discover_device_entities(device: Device) -> Iterator[BaseEntity]:
    """Discover entities for a ZHA device."""
    _LOGGER.debug(
        "Discovering entities for device: %s-%s",
        str(device.ieee),
        device.name,
    )

    assert not device.is_active_coordinator

    for ep_id, endpoint in device.endpoints.items():
        if ep_id == 0:
            continue

        _LOGGER.debug(
            "Discovering entities for endpoint: %s-%s",
            str(endpoint.device.ieee),
            endpoint.id,
        )

        yield from discover_entities_for_endpoint(endpoint)

    yield from discover_quirks_v2_entities(device)


@ignore_exceptions_during_iteration
def discover_coordinator_device_entities(
    device: Device,
) -> Iterator[sensor.DeviceCounterSensor]:
    """Discover entities for the coordinator device."""
    _LOGGER.debug(
        "Discovering entities for coordinator device: %s-%s",
        str(device.ieee),
        device.name,
    )
    state: State = device.gateway.application_controller.state

    for counter_groups in (
        "counters",
        "broadcast_counters",
        "device_counters",
        "group_counters",
    ):
        for counter_group, counters in getattr(state, counter_groups).items():
            for counter in counters:
                yield sensor.DeviceCounterSensor(
                    zha_device=device,
                    counter_groups=counter_groups,
                    counter_group=counter_group,
                    counter=counter,
                )

                _LOGGER.debug(
                    "'%s' platform -> '%s' using %s",
                    Platform.SENSOR,
                    sensor.DeviceCounterSensor.__name__,
                    f"counter groups[{counter_groups}] counter group[{counter_group}] counter[{counter}]",
                )


@ignore_exceptions_during_iteration
def discover_group_entities(group: Group) -> Iterator[GroupEntity]:
    """Process a group and create any entities that are needed."""
    # only create a group entity if there are 2 or more members in a group
    if len(group.members) < 2:
        _LOGGER.debug(
            "Group: %s:0x%04x has less than 2 members - skipping entity discovery",
            group.name,
            group.group_id,
        )
        group.group_entities.clear()
        return

    # We only create groups with two or more devices
    platform_counts: Counter[Platform] = Counter()

    for member in group.members:
        if member.device.is_coordinator:
            continue

        for entity in member.associated_entities:
            platform_counts[entity.PLATFORM] += 1

    for platform, count in platform_counts.items():
        if count < 2:
            continue

        for group_entity_class in GROUP_ENTITY_REGISTRY:
            if platform != group_entity_class.PLATFORM:
                continue
            _LOGGER.info(
                "Creating group entity %s for group %s",
                group_entity_class,
                group.name,
            )
            yield group_entity_class(group)


def discover_quirks_v2_entities(device: Device) -> Iterator[PlatformEntity]:
    """Discover entities for a ZHA device exposed by quirks v2."""
    _LOGGER.debug(
        "Attempting to discover quirks v2 entities for device: %s-%s",
        str(device.ieee),
        device.name,
    )

    if not isinstance(device.device, CustomDeviceV2):
        _LOGGER.debug(
            "Device: %s-%s is not a quirks v2 device - skipping "
            "discover_quirks_v2_entities",
            str(device.ieee),
            device.name,
        )
        return

    zigpy_device: CustomDeviceV2 = device.device

    if not zigpy_device.exposes_metadata:
        _LOGGER.debug(
            "Device: %s-%s does not expose any quirks v2 entities",
            str(device.ieee),
            device.name,
        )
        return

    for (
        cluster_details,
        entity_metadata_list,
    ) in zigpy_device.exposes_metadata.items():
        endpoint_id, cluster_id, cluster_type = cluster_details

        if endpoint_id not in device.endpoints:
            _LOGGER.warning(
                "Device: %s-%s does not have an endpoint with id: %s - unable to "
                "create entity with cluster details: %s",
                str(device.ieee),
                device.name,
                endpoint_id,
                cluster_details,
            )
            continue

        endpoint: Endpoint = device.endpoints[endpoint_id]
        cluster = (
            endpoint.zigpy_endpoint.in_clusters.get(cluster_id)
            if cluster_type is ClusterType.Server
            else endpoint.zigpy_endpoint.out_clusters.get(cluster_id)
        )

        if cluster is None:
            _LOGGER.warning(
                "Device: %s-%s does not have a cluster with id: %s - "
                "unable to create entity with cluster details: %s",
                str(device.ieee),
                device.name,
                cluster_id,
                cluster_details,
            )
            continue

        for entity_metadata in entity_metadata_list:
            platform = Platform(entity_metadata.entity_platform.value)
            metadata_type = type(entity_metadata)
            entity_class = QUIRKS_ENTITY_META_TO_ENTITY_CLASS.get(
                (platform, metadata_type)
            )

            if entity_class is None:
                _LOGGER.warning(
                    "Device: %s-%s has an entity with details: %s that does not"
                    " have an entity class mapping - unable to create entity",
                    str(device.ieee),
                    device.name,
                    {
                        zha_const.CLUSTER_DETAILS: cluster_details,
                        zha_const.ENTITY_METADATA: entity_metadata,
                    },
                )
                continue

            entity = entity_class(
                endpoint=endpoint,
                device=device,
                cluster=cluster,
                entity_metadata=entity_metadata,
            )

            # Translate quirks v2 reporting/attribute-init metadata into a
            # per-instance cluster config that the cluster_config aggregator
            # picks up alongside the entity's normal (class-level) declarations.
            if attr_name := getattr(entity_metadata, "attribute_name", None):
                rep_conf = getattr(entity_metadata, "reporting_config", None)
                if rep_conf is not None:
                    attr_config = AttrConfig(
                        read_on_startup=False,
                        reporting=ReportingConfig(
                            min_interval=rep_conf.min_interval,
                            max_interval=rep_conf.max_interval,
                            reportable_change=rep_conf.reportable_change,
                        ),
                    )
                    bind = True
                else:
                    attr_config = AttrConfig(
                        read_on_startup=(
                            not entity_metadata.attribute_initialized_from_cache
                        ),
                    )
                    bind = False

                # Keep attr_name as a string here - quirks v2 entities can reference
                # attribute names that aren't part of the cluster's attribute schema
                # (e.g. manufacturer-specific extensions); aggregation/configure handle
                # both name and ZCLAttributeDef.
                config = {
                    cluster.cluster_id: ClusterConfig(
                        bind=bind,
                        attributes={attr_name: attr_config},
                    ),
                }

                if cluster_type is ClusterType.Server:
                    entity._server_cluster_config = config
                else:
                    entity._client_cluster_config = config

            yield entity

            _LOGGER.debug(
                "'%s' platform -> '%s' using cluster 0x%04x",
                platform,
                entity_class.__name__,
                cluster.cluster_id,
            )


def _is_renamed_cluster(cluster: Cluster) -> bool:
    """Return True if a quirk has renamed the cluster's ep_attribute."""
    standard = Cluster._registry.get(cluster.cluster_id)
    if standard is None:
        return False

    # Used to skip ClusterMatch entities for renamed clusters so the new cluster id
    # based matching behaves the same as the legacy handler-name matching (which never
    # found a handler under the standard name).
    return cluster.ep_attribute != standard.ep_attribute


def discover_entities_for_endpoint(endpoint: Endpoint) -> Iterator[PlatformEntity]:  # noqa: C901
    """Discover entities for an endpoint using the new registry-based discovery."""
    device = endpoint.device

    # TODO: deprecate device platform overrides. The only use case is to swap between
    # `light` and `switch` for devices whose device type is incorrect.
    platform_override: Platform | None = None

    if (
        device_override := device.gateway.config.config.device_overrides.get(
            f"{device.ieee}-{endpoint.id}"
        )
    ) is not None:
        platform_override = device_override.type

    matches_by_feature_and_priority: defaultdict[
        PlatformFeatureGroup | None,
        defaultdict[
            int,  # Weight
            list[tuple[ClusterMatch, type[PlatformEntity]]],
        ],
    ] = defaultdict(lambda: defaultdict(list))

    # Cluster IDs available to ClusterMatch (renamed quirked clusters excluded to
    # mirror the legacy handler-name based matching). Entities that opt into
    # `match_renamed_clusters=True` get the inclusive sets instead.
    in_cluster_ids = {
        cid
        for cid, cluster in endpoint.zigpy_endpoint.in_clusters.items()
        if not _is_renamed_cluster(cluster)
    }
    out_cluster_ids = {
        cid
        for cid, cluster in endpoint.zigpy_endpoint.out_clusters.items()
        if not _is_renamed_cluster(cluster)
    }
    in_cluster_ids_with_renamed = set(endpoint.zigpy_endpoint.in_clusters)
    out_cluster_ids_with_renamed = set(endpoint.zigpy_endpoint.out_clusters)

    for cluster in itertools.chain(
        endpoint.zigpy_endpoint.in_clusters.values(),
        endpoint.zigpy_endpoint.out_clusters.values(),
    ):
        # To speed up lookups, we key ENTITY_REGISTRY by cluster ID. First, we find all
        # compatible entities and their matching criteria.
        for entity_class in ENTITY_REGISTRY.get(cluster.cluster_id, []):
            if entity_class._cluster_match is None:
                continue
            match = entity_class._cluster_match

            if match.match_renamed_clusters:
                available_in = in_cluster_ids_with_renamed
                available_out = out_cluster_ids_with_renamed
            else:
                available_in = in_cluster_ids
                available_out = out_cluster_ids

            if not match.server_clusters.issubset(available_in):
                continue

            if not match.client_clusters.issubset(available_out):
                continue

            if (
                match.profile_ids is not None
                and endpoint.zigpy_endpoint.profile_id not in match.profile_ids
            ):
                continue

            if (
                match.exposed_features is not None
                and not match.exposed_features & device.exposes_features
            ):
                continue

            if (
                match.not_exposed_features is not None
                and match.not_exposed_features & device.exposes_features
            ):
                continue

            if (
                match.manufacturers is not None
                and device.manufacturer not in match.manufacturers
            ):
                continue

            if match.models is not None and device.model not in match.models:
                continue

            profile_device_type = (
                endpoint.zigpy_endpoint.profile_id,
                endpoint.zigpy_endpoint.device_type,
            )
            override_bypass = (
                platform_override is not None
                and platform_override == entity_class.PLATFORM
            )

            if (
                match.profile_device_types is not None
                and profile_device_type not in match.profile_device_types
                and not override_bypass
            ):
                continue

            if (
                match.not_profile_device_types is not None
                and profile_device_type in match.not_profile_device_types
                and not override_bypass
            ):
                continue

            if match.feature_priority is not None:
                feature, priority = match.feature_priority
            else:
                feature = None
                priority = 0

            matches_by_feature_and_priority[feature][priority].append(
                (match, entity_class)
            )

    # Then, we process the matches and discard entities with lower weights (when
    # feature groups are used)
    for feature, matches_by_priority in matches_by_feature_and_priority.items():
        # Use platform overrides to replace the results of the normal priority scoring
        # system when competing entities are part of the same feature group
        if platform_override is not None and feature is not None:
            override_by_priority: defaultdict[
                int,
                list[tuple[ClusterMatch, type[PlatformEntity]]],
            ] = defaultdict(list)

            for priority, priority_matches in matches_by_priority.items():
                platform_matches = [
                    (match, entity)
                    for match, entity in priority_matches
                    if platform_override == entity.PLATFORM
                ]
                if platform_matches:
                    override_by_priority[priority] = platform_matches

            # Replace matches with overrides
            if override_by_priority:
                matches_by_priority = override_by_priority

        highest_priority = max(matches_by_priority.keys())

        if _LOGGER.getEffectiveLevel() <= logging.DEBUG:
            ignored_matches = [
                (priority, matches)
                for priority, matches in matches_by_priority.items()
                if priority < highest_priority
            ]

            if ignored_matches:
                _LOGGER.debug(
                    "Ignored matches for feature '%s': %s",
                    feature,
                    ignored_matches,
                )

        selected_matches = matches_by_priority[highest_priority]

        # Use platform overrides to replace the results of the normal priority scoring
        # system when competing entities are part of the same feature group
        if platform_override is not None and feature is not None:
            override_matches = [
                (match, entity)
                for priority_matches in matches_by_priority.values()
                for match, entity in priority_matches
                if platform_override == entity.PLATFORM
            ]
            if override_matches:
                selected_matches = override_matches

        for match, entity_class in selected_matches:
            _LOGGER.debug(
                "'%s' platform -> '%s'",
                entity_class.PLATFORM,
                entity_class.__name__,
            )

            kwargs: dict[str, Any] = {}
            cluster = _pick_primary_cluster(endpoint, match)
            if cluster is not None:
                kwargs["cluster"] = cluster

            try:
                entity = entity_class(
                    endpoint=endpoint,
                    device=device,
                    **kwargs,
                )
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Failed to create %s entity", entity_class.__name__)
                continue
            yield entity
