"""Device discovery functions for Zigbee Home Automation."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import astuple
import functools
import itertools
import logging
from typing import TYPE_CHECKING

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
from zigpy.zcl import ClusterType

from zha.application import Platform, const as zha_const
from zha.application.platforms import (  # noqa: F401 pylint: disable=unused-import
    ENTITY_REGISTRY,
    GROUP_ENTITY_REGISTRY,
    BaseEntity,
    ClusterHandlerMatch,
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
)

# importing cluster handlers updates registries
from zha.zigbee.cluster_handlers import (  # noqa: F401 pylint: disable=unused-import
    AttrReportConfig,
    ClientClusterHandler,
    ClusterHandler,
    closures,
    general,
    homeautomation,
    hvac,
    lighting,
    lightlink,
    manufacturerspecific,
    measurement,
    protocol,
    security,
    smartenergy,
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

        if cluster_type is ClusterType.Server:
            cluster_handler = endpoint.all_cluster_handlers.get(
                f"{endpoint.id}:0x{cluster.cluster_id:04x}"
            )
        else:
            cluster_handler = endpoint.client_cluster_handlers.get(
                f"{endpoint.id}:0x{cluster.cluster_id:04x}_client"
            )

        assert cluster_handler

        # flags to determine if we need to claim/bind the cluster handler
        attribute_initialization_found: bool = False
        reporting_found: bool = False

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

            # process the entity metadata for ZCL_INIT_ATTRS and REPORT_CONFIG
            if attr_name := getattr(entity_metadata, "attribute_name", None):
                # TODO: ignore "attribute write buttons"? currently, we claim ch
                # if the entity has a reporting config, add it to the cluster handler
                if rep_conf := getattr(entity_metadata, "reporting_config", None):
                    # if attr is already in REPORT_CONFIG, remove it first
                    cluster_handler.REPORT_CONFIG = tuple(
                        filter(
                            lambda cfg: cfg["attr"] != attr_name,
                            cluster_handler.REPORT_CONFIG,
                        )
                    )
                    # tuples are immutable and we re-set the REPORT_CONFIG here,
                    # so no need to check for an instance variable
                    cluster_handler.REPORT_CONFIG += (
                        AttrReportConfig(attr=attr_name, config=astuple(rep_conf)),
                    )
                    # mark cluster handler for claiming and binding later
                    reporting_found = True

                # not in REPORT_CONFIG, add to ZCL_INIT_ATTRS if it not already in
                elif attr_name not in cluster_handler.ZCL_INIT_ATTRS:
                    # copy existing ZCL_INIT_ATTRS into instance variable once,
                    # so we don't modify other instances of the same cluster handler
                    if zha_const.ZCL_INIT_ATTRS not in cluster_handler.__dict__:
                        cluster_handler.ZCL_INIT_ATTRS = (
                            cluster_handler.ZCL_INIT_ATTRS.copy()
                        )
                    # add the attribute to the guaranteed instance variable
                    cluster_handler.ZCL_INIT_ATTRS[attr_name] = (
                        entity_metadata.attribute_initialized_from_cache
                    )
                    # mark cluster handler for claiming later, but not binding
                    attribute_initialization_found = True

            yield entity_class(
                cluster_handlers=[cluster_handler],
                endpoint=endpoint,
                device=device,
                entity_metadata=entity_metadata,
                legacy_discovery_unique_id=f"{device.ieee}-{endpoint.id}",
            )

            _LOGGER.debug(
                "'%s' platform -> '%s' using %s",
                platform,
                entity_class.__name__,
                [cluster_handler.name],
            )

        # if the cluster handler is unclaimed, claim it and set BIND accordingly,
        # so ZHA configures the cluster handler: reporting + reads attributes
        if (attribute_initialization_found or reporting_found) and (
            cluster_handler not in endpoint.claimed_cluster_handlers.values()
        ):
            endpoint.claim_cluster_handlers([cluster_handler])
            # BIND is True by default, so only set to False if no reporting found.
            # We can safely do this, since quirks v2 entities are initialized last,
            # so if the cluster handler wasn't claimed by endpoint probing so far,
            # only v2 entities need it.
            if not reporting_found:
                cluster_handler.BIND = False


def discover_entities_for_endpoint(endpoint: Endpoint) -> Iterator[PlatformEntity]:
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
            list[tuple[ClusterHandlerMatch, type[PlatformEntity]]],
        ],
    ] = defaultdict(lambda: defaultdict(list))

    for cluster in itertools.chain(
        endpoint.zigpy_endpoint.in_clusters.values(),
        endpoint.zigpy_endpoint.out_clusters.values(),
    ):
        # To speed up lookups, we key ENTITY_REGISTRY by cluster ID. First, we find all
        # compatible entities and their matching criteria.
        for entity_class in ENTITY_REGISTRY.get(cluster.cluster_id, []):
            match = entity_class._cluster_handler_match
            if match is None:
                continue

            if not match.cluster_handlers.issubset(
                endpoint.cluster_handlers_by_name.keys()
            ):
                continue

            if not match.client_cluster_handlers.issubset(
                endpoint.client_cluster_handlers_by_name.keys()
            ):
                continue

            if (
                match.exposed_features is not None
                and not match.exposed_features & device.exposes_features
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
            if (
                match.profile_device_types is not None
                and profile_device_type not in match.profile_device_types
            ):
                continue

            if (
                match.not_profile_device_types is not None
                and profile_device_type in match.not_profile_device_types
            ):
                continue

            if match.feature_priority is not None:
                feature, priority = match.feature_priority
            else:
                feature = None
                priority = 0

            # Finally, account for `platform_override` by boosting the priority of
            # matching platforms
            if (
                platform_override is not None
                and platform_override == entity_class.PLATFORM
            ):
                priority += 1000

            matches_by_feature_and_priority[feature][priority].append(
                (match, entity_class)
            )

    # Then, we process the matches and discard entities with lower weights (when
    # feature groups are used)
    for feature, matches_by_priority in matches_by_feature_and_priority.items():
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

        for match, entity_class in matches_by_priority[highest_priority]:
            server_handlers = set(match.cluster_handlers)

            for optional in match.optional_cluster_handlers:
                if optional in endpoint.cluster_handlers_by_name:
                    server_handlers.add(optional)

            client_handlers = set(match.client_cluster_handlers)

            server_cluster_handlers = [
                endpoint.cluster_handlers_by_name[name] for name in server_handlers
            ]
            client_cluster_handlers = [
                endpoint.client_cluster_handlers_by_name[name]
                for name in client_handlers
            ]

            # Claim on endpoint
            endpoint.claim_cluster_handlers(server_cluster_handlers)
            endpoint.claim_cluster_handlers(client_cluster_handlers)

            _LOGGER.debug(
                "'%s' platform -> '%s' using %s + %s",
                entity_class.PLATFORM,
                entity_class.__name__,
                [ch.name for ch in server_cluster_handlers],
                [ch.name for ch in client_cluster_handlers],
            )

            # XXX: Combining server and client cluster handlers should not be done
            cluster_handlers: list[ClusterHandler | ClientClusterHandler] = (
                server_cluster_handlers + client_cluster_handlers  # type: ignore[operator]
            )

            yield entity_class(
                cluster_handlers=cluster_handlers,
                endpoint=endpoint,
                device=device,
            )
