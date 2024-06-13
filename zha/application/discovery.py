"""Device discovery functions for Zigbee Home Automation."""

from __future__ import annotations

from collections import Counter
import logging
from typing import TYPE_CHECKING, cast

from zigpy.quirks.v2 import (
    BinarySensorMetadata,
    CustomDeviceV2,
    EntityType,
    NumberMetadata,
    SwitchMetadata,
    WriteAttributeButtonMetadata,
    ZCLCommandButtonMetadata,
    ZCLEnumMetadata,
    ZCLSensorMetadata,
)
from zigpy.state import State
from zigpy.zcl import ClusterType
from zigpy.zcl.clusters.general import Ota

from zha.application import Platform, const as zha_const
from zha.application.helpers import DeviceOverridesConfiguration
from zha.application.platforms import (  # noqa: F401 pylint: disable=unused-import
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
from zha.application.registries import (
    DEVICE_CLASS,
    PLATFORM_ENTITIES,
    REMOTE_DEVICE_TYPES,
    SINGLE_INPUT_CLUSTER_DEVICE_CLASS,
    SINGLE_OUTPUT_CLUSTER_DEVICE_CLASS,
)

# importing cluster handlers updates registries
from zha.zigbee.cluster_handlers import (  # noqa: F401 pylint: disable=unused-import
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
from zha.zigbee.cluster_handlers.registries import (
    CLUSTER_HANDLER_ONLY_CLUSTERS,
    CLUSTER_HANDLER_REGISTRY,
)
from zha.zigbee.group import Group

if TYPE_CHECKING:
    from zha.application.gateway import Gateway
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
    (
        Platform.BUTTON,
        WriteAttributeButtonMetadata,
        EntityType.CONFIG,
    ): button.WriteAttributeButton,
    (
        Platform.BUTTON,
        WriteAttributeButtonMetadata,
        EntityType.STANDARD,
    ): button.WriteAttributeButton,
    (Platform.BUTTON, ZCLCommandButtonMetadata, EntityType.CONFIG): button.Button,
    (
        Platform.BUTTON,
        ZCLCommandButtonMetadata,
        EntityType.DIAGNOSTIC,
    ): button.Button,
    (Platform.BUTTON, ZCLCommandButtonMetadata, EntityType.STANDARD): button.Button,
    (
        Platform.BINARY_SENSOR,
        BinarySensorMetadata,
        EntityType.CONFIG,
    ): binary_sensor.BinarySensor,
    (
        Platform.BINARY_SENSOR,
        BinarySensorMetadata,
        EntityType.DIAGNOSTIC,
    ): binary_sensor.BinarySensor,
    (
        Platform.BINARY_SENSOR,
        BinarySensorMetadata,
        EntityType.STANDARD,
    ): binary_sensor.BinarySensor,
    (Platform.SENSOR, ZCLEnumMetadata, EntityType.DIAGNOSTIC): sensor.EnumSensor,
    (Platform.SENSOR, ZCLEnumMetadata, EntityType.STANDARD): sensor.EnumSensor,
    (Platform.SENSOR, ZCLSensorMetadata, EntityType.DIAGNOSTIC): sensor.Sensor,
    (Platform.SENSOR, ZCLSensorMetadata, EntityType.STANDARD): sensor.Sensor,
    (Platform.SELECT, ZCLEnumMetadata, EntityType.CONFIG): select.ZCLEnumSelectEntity,
    (Platform.SELECT, ZCLEnumMetadata, EntityType.STANDARD): select.ZCLEnumSelectEntity,
    (
        Platform.SELECT,
        ZCLEnumMetadata,
        EntityType.DIAGNOSTIC,
    ): select.ZCLEnumSelectEntity,
    (
        Platform.NUMBER,
        NumberMetadata,
        EntityType.CONFIG,
    ): number.NumberConfigurationEntity,
    (Platform.NUMBER, NumberMetadata, EntityType.DIAGNOSTIC): number.Number,
    (Platform.NUMBER, NumberMetadata, EntityType.STANDARD): number.Number,
    (
        Platform.SWITCH,
        SwitchMetadata,
        EntityType.CONFIG,
    ): switch.SwitchConfigurationEntity,
    (Platform.SWITCH, SwitchMetadata, EntityType.STANDARD): switch.Switch,
}


class DeviceProbe:
    """Probe to discover entities for a device."""

    def __init__(self) -> None:
        """Initialize instance."""
        self._gateway: Gateway

    def initialize(self, gateway: Gateway) -> None:
        """Initialize the group probe."""
        self._gateway = gateway

    def discover_device_entities(self, device: Device) -> None:
        """Discover entities for a ZHA device."""
        _LOGGER.debug(
            "Discovering entities for device: %s-%s",
            str(device.ieee),
            device.name,
        )

        if device.is_active_coordinator:
            self.discover_coordinator_device_entities(device)
            return

        self.discover_quirks_v2_entities(device)
        PLATFORM_ENTITIES.clean_up()

    def discover_quirks_v2_entities(self, device: Device) -> None:
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

            cluster_handler_id = f"{endpoint.id}:0x{cluster.cluster_id:04x}"
            cluster_handler = (
                endpoint.all_cluster_handlers.get(cluster_handler_id)
                if cluster_type is ClusterType.Server
                else endpoint.client_cluster_handlers.get(cluster_handler_id)
            )
            assert cluster_handler

            for entity_metadata in entity_metadata_list:
                platform = Platform(entity_metadata.entity_platform.value)
                metadata_type = type(entity_metadata)
                entity_class = QUIRKS_ENTITY_META_TO_ENTITY_CLASS.get(
                    (platform, metadata_type, entity_metadata.entity_type)
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

                # automatically add the attribute to ZCL_INIT_ATTRS for the cluster
                # handler if it is not already in the list
                if (
                    hasattr(entity_metadata, "attribute_name")
                    and entity_metadata.attribute_name
                    not in cluster_handler.ZCL_INIT_ATTRS
                ):
                    init_attrs = cluster_handler.ZCL_INIT_ATTRS.copy()
                    init_attrs[entity_metadata.attribute_name] = (
                        entity_metadata.attribute_initialized_from_cache
                    )
                    cluster_handler.__dict__[zha_const.ZCL_INIT_ATTRS] = init_attrs

                endpoint.async_new_entity(
                    platform=platform,
                    entity_class=entity_class,
                    unique_id=endpoint.unique_id,
                    cluster_handlers=[cluster_handler],
                    entity_metadata=entity_metadata,
                )

                _LOGGER.debug(
                    "'%s' platform -> '%s' using %s",
                    platform,
                    entity_class.__name__,
                    [cluster_handler.name],
                )

    def discover_coordinator_device_entities(self, device: Device) -> None:
        """Discover entities for the coordinator device."""
        _LOGGER.debug(
            "Discovering entities for coordinator device: %s-%s",
            str(device.ieee),
            device.name,
        )
        state: State = device.gateway.application_controller.state
        platforms: dict[Platform, list] = self._gateway.config.platforms

        def process_counters(counter_groups: str) -> None:
            for counter_group, counters in getattr(state, counter_groups).items():
                for counter in counters:
                    platforms[Platform.SENSOR].append(
                        (
                            sensor.DeviceCounterSensor,
                            (
                                device,
                                counter_groups,
                                counter_group,
                                counter,
                            ),
                            {},
                        )
                    )
                    _LOGGER.debug(
                        "'%s' platform -> '%s' using %s",
                        Platform.SENSOR,
                        sensor.DeviceCounterSensor.__name__,
                        f"counter groups[{counter_groups}] counter group[{counter_group}] counter[{counter}]",
                    )

        process_counters("counters")
        process_counters("broadcast_counters")
        process_counters("device_counters")
        process_counters("group_counters")


class EndpointProbe:
    """All discovered cluster handlers and entities of an endpoint."""

    def __init__(self) -> None:
        """Initialize instance."""
        self._device_configs: dict[str, DeviceOverridesConfiguration] = {}

    def discover_entities(self, endpoint: Endpoint) -> None:
        """Process an endpoint on a zigpy device."""
        _LOGGER.debug(
            "Discovering entities for endpoint: %s-%s",
            str(endpoint.device.ieee),
            endpoint.id,
        )
        self.discover_by_device_type(endpoint)
        self.discover_multi_entities(endpoint)
        self.discover_by_cluster_id(endpoint)
        self.discover_multi_entities(endpoint, config_diagnostic_entities=True)
        PLATFORM_ENTITIES.clean_up()

    def discover_by_device_type(self, endpoint: Endpoint) -> None:
        """Process an endpoint on a zigpy device."""

        unique_id = endpoint.unique_id

        platform: str | None = None
        if unique_id in self._device_configs:
            platform = self._device_configs.get(unique_id).type
        if platform is None:
            ep_profile_id = endpoint.zigpy_endpoint.profile_id
            ep_device_type = endpoint.zigpy_endpoint.device_type
            platform = DEVICE_CLASS[ep_profile_id].get(ep_device_type)

        if platform and platform in PLATFORMS:
            platform = cast(Platform, platform)

            cluster_handlers = endpoint.unclaimed_cluster_handlers()
            platform_entity_class, claimed = PLATFORM_ENTITIES.get_entity(
                platform,
                endpoint.device.manufacturer,
                endpoint.device.model,
                cluster_handlers,
                endpoint.device.quirk_id,
            )
            if platform_entity_class is None:
                return
            endpoint.claim_cluster_handlers(claimed)
            endpoint.async_new_entity(
                platform, platform_entity_class, unique_id, claimed
            )

    def discover_by_cluster_id(self, endpoint: Endpoint) -> None:
        """Process an endpoint on a zigpy device."""

        items = SINGLE_INPUT_CLUSTER_DEVICE_CLASS.items()
        single_input_clusters = {
            cluster_class: match
            for cluster_class, match in items
            if not isinstance(cluster_class, int)
        }
        remaining_cluster_handlers = endpoint.unclaimed_cluster_handlers()
        for cluster_handler in remaining_cluster_handlers:
            if cluster_handler.cluster.cluster_id in CLUSTER_HANDLER_ONLY_CLUSTERS:
                endpoint.claim_cluster_handlers([cluster_handler])
                continue

            platform = SINGLE_INPUT_CLUSTER_DEVICE_CLASS.get(
                cluster_handler.cluster.cluster_id
            )
            if platform is None:
                for cluster_class, match in single_input_clusters.items():
                    if isinstance(cluster_handler.cluster, cluster_class):
                        platform = match
                        break

            self.probe_single_cluster(platform, cluster_handler, endpoint)

        # until we can get rid of registries
        self.handle_on_off_output_cluster_exception(endpoint)

    @staticmethod
    def probe_single_cluster(
        platform: Platform | None,
        cluster_handler: ClusterHandler,
        endpoint: Endpoint,
    ) -> None:
        """Probe specified cluster for specific platform."""
        if platform is None or platform not in PLATFORMS:
            return
        cluster_handler_list = [cluster_handler]
        unique_id = f"{endpoint.unique_id}-{cluster_handler.cluster.cluster_id}"

        entity_class, claimed = PLATFORM_ENTITIES.get_entity(
            platform,
            endpoint.device.manufacturer,
            endpoint.device.model,
            cluster_handler_list,
            endpoint.device.quirk_id,
        )
        if entity_class is None:
            return
        endpoint.claim_cluster_handlers(claimed)
        endpoint.async_new_entity(platform, entity_class, unique_id, claimed)

    def handle_on_off_output_cluster_exception(self, endpoint: Endpoint) -> None:
        """Process output clusters of the endpoint."""

        profile_id = endpoint.zigpy_endpoint.profile_id
        device_type = endpoint.zigpy_endpoint.device_type
        if device_type in REMOTE_DEVICE_TYPES.get(profile_id, []):
            return

        for cluster_id, cluster in endpoint.zigpy_endpoint.out_clusters.items():
            platform = SINGLE_OUTPUT_CLUSTER_DEVICE_CLASS.get(cluster.cluster_id)
            if platform is None:
                continue

            cluster_handler_classes = CLUSTER_HANDLER_REGISTRY.get(
                cluster_id, {None: ClusterHandler}
            )

            quirk_id = (
                endpoint.device.quirk_id
                if endpoint.device.quirk_id in cluster_handler_classes
                else None
            )

            cluster_handler_class = cluster_handler_classes.get(
                quirk_id, ClusterHandler
            )

            cluster_handler = cluster_handler_class(cluster, endpoint)
            self.probe_single_cluster(platform, cluster_handler, endpoint)

    @staticmethod
    def discover_multi_entities(
        endpoint: Endpoint,
        config_diagnostic_entities: bool = False,
    ) -> None:
        """Process an endpoint on and discover multiple entities."""

        ep_profile_id = endpoint.zigpy_endpoint.profile_id
        ep_device_type = endpoint.zigpy_endpoint.device_type
        cmpt_by_dev_type = DEVICE_CLASS[ep_profile_id].get(ep_device_type)

        if config_diagnostic_entities:
            cluster_handlers = list(endpoint.all_cluster_handlers.values())
            ota_handler_id = f"{endpoint.id}:0x{Ota.cluster_id:04x}"
            if ota_handler_id in endpoint.client_cluster_handlers:
                cluster_handlers.append(
                    endpoint.client_cluster_handlers[ota_handler_id]
                )
            matches, claimed = PLATFORM_ENTITIES.get_config_diagnostic_entity(
                endpoint.device.manufacturer,
                endpoint.device.model,
                cluster_handlers,
                endpoint.device.quirk_id,
            )
        else:
            matches, claimed = PLATFORM_ENTITIES.get_multi_entity(
                endpoint.device.manufacturer,
                endpoint.device.model,
                endpoint.unclaimed_cluster_handlers(),
                endpoint.device.quirk_id,
            )

        endpoint.claim_cluster_handlers(claimed)
        for platform, ent_n_handler_list in matches.items():
            for entity_and_handler in ent_n_handler_list:
                _LOGGER.debug(
                    "'%s' platform -> '%s' using %s",
                    platform,
                    entity_and_handler.entity_class.__name__,
                    [ch.name for ch in entity_and_handler.claimed_cluster_handlers],
                )

                if platform == cmpt_by_dev_type:
                    # for well known device types,
                    # like thermostats we'll take only 1st class
                    endpoint.async_new_entity(
                        platform,
                        entity_and_handler.entity_class,
                        endpoint.unique_id,
                        entity_and_handler.claimed_cluster_handlers,
                    )
                    break
                first_ch = entity_and_handler.claimed_cluster_handlers[0]
                endpoint.async_new_entity(
                    platform,
                    entity_and_handler.entity_class,
                    f"{endpoint.unique_id}-{first_ch.cluster.cluster_id}",
                    entity_and_handler.claimed_cluster_handlers,
                )

    def initialize(self, gateway: Gateway) -> None:
        """Update device overrides config."""
        if overrides := gateway.config.config.device_overrides:
            self._device_configs.update(overrides)


class GroupProbe:
    """Determine the appropriate platform for a group."""

    def __init__(self) -> None:
        """Initialize instance."""
        self._gateway: Gateway

    def initialize(self, gateway: Gateway) -> None:
        """Initialize the group probe."""
        self._gateway = gateway

    def discover_group_entities(self, group: Group) -> None:
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

        assert self._gateway
        entity_platforms = GroupProbe.determine_entity_platforms(group)

        if not entity_platforms:
            _LOGGER.info("No entity platforms discovered for group %s", group.name)
            return

        for platform in entity_platforms:
            entity_class = PLATFORM_ENTITIES.get_group_entity(platform)
            if entity_class is None:
                continue
            _LOGGER.info("Creating entity : %s for group %s", entity_class, group.name)
            entity_class(group)

    @staticmethod
    def determine_entity_platforms(group: Group) -> list[Platform]:
        """Determine the entity platforms for this group."""
        entity_domains: list[Platform] = []
        all_platform_occurrences = []
        for member in group.members:
            if member.device.is_coordinator:
                continue
            entities = member.associated_entities
            all_platform_occurrences.extend(
                [
                    entity.PLATFORM
                    for entity in entities
                    if entity.PLATFORM in GROUP_PLATFORMS
                ]
            )
        if not all_platform_occurrences:
            return entity_domains
        # get all platforms we care about if there are more than 2 entities of this platform
        counts = Counter(all_platform_occurrences)
        entity_platforms = [
            platform[0] for platform in counts.items() if platform[1] >= 2
        ]
        _LOGGER.debug(
            "The entity platforms are: %s for group: %s:0x%04x",
            entity_platforms,
            group.name,
            group.group_id,
        )
        return entity_platforms


DEVICE_PROBE = DeviceProbe()
ENDPOINT_PROBE = EndpointProbe()
GROUP_PROBE = GroupProbe()
