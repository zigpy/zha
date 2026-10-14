"""Child devices: logical parts of a device, such as the gangs of a wall switch."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Final

from zigpy.typing import UNDEFINED
from zigpy.zcl.clusters.general import (
    Basic,
    DeviceTemperature,
    Identify,
    Ota,
    PollControl,
    PowerConfiguration,
    Time,
)
from zigpy.zcl.clusters.homeautomation import Diagnostic

from zha.application import Platform

if TYPE_CHECKING:
    from zha.application.platforms import PlatformEntity

_LOGGER = logging.getLogger(__name__)

# Entities of these clusters describe the whole device (battery, firmware, signal
# strength, ...), so they always stay on the main device, whatever endpoint they are on
DEVICE_LEVEL_CLUSTERS: Final[frozenset[int]] = frozenset(
    {
        Basic.cluster_id,
        PowerConfiguration.cluster_id,
        DeviceTemperature.cluster_id,
        Identify.cluster_id,
        Time.cluster_id,
        Ota.cluster_id,
        PollControl.cluster_id,
        Diagnostic.cluster_id,
    }
)

# Platforms whose entities represent an independently controllable output unit. An
# endpoint is split into its own child device when it carries such an entity and
# a sibling endpoint carries one of the same platform.
OUTPUT_PLATFORMS: Final[frozenset[Platform]] = frozenset(
    {
        Platform.CLIMATE,
        Platform.COVER,
        Platform.FAN,
        Platform.LIGHT,
        Platform.LOCK,
        Platform.SWITCH,
        Platform.VALVE,
    }
)

CHILD_DEVICE_TRANSLATION_KEY_CHANNEL: Final = "channel"


@dataclass(frozen=True, kw_only=True)
class ChildDevice:
    """A logical part of a device that is exposed as its own (child) device.

    Entities on one of `endpoint_ids` belong to the child device, except entities of
    device-level clusters (see `DEVICE_LEVEL_CLUSTERS`). Single entities can be
    assigned to a child device, or kept on the main device, explicitly instead.
    """

    # Identifies the child device within its device. It must stay stable, as
    # consumers derive the child device's identity from it.
    id: str
    endpoint_ids: frozenset[int] = frozenset()
    translation_key: str | None = None
    translation_placeholders: Mapping[str, str] | None = field(default=None, hash=False)
    fallback_name: str

    def __post_init__(self) -> None:
        """Validate the child device."""
        if not self.id:
            raise ValueError("A child device needs a non-empty id")


@dataclass(frozen=True, kw_only=True)
class ChildDeviceMatch:
    """Selects devices whose output endpoints are split into child devices."""

    models: frozenset[str]
    # `None` matches any manufacturer, for generic models such as Tuya's `TS0002`
    manufacturers: frozenset[str] | None = None

    def matches(self, manufacturer: str, model: str) -> bool:
        """Return whether the device matches."""
        return model in self.models and (
            self.manufacturers is None or manufacturer in self.manufacturers
        )


# Devices whose output endpoints are split into child devices automatically, see
# `compute_output_child_devices`. Splitting changes how existing entities are
# presented, so devices are opted in one by one, after checking their diagnostics.
# Quirks can define child devices themselves instead, which takes precedence.
CHILD_DEVICE_ALLOWLIST: Final[tuple[ChildDeviceMatch, ...]] = (
    # Tuya multi-gang wall switches and relays
    ChildDeviceMatch(models=frozenset({"TS0002", "TS0003", "TS0004"})),
    ChildDeviceMatch(models=frozenset({"TS0012", "TS0013", "TS0014"})),
    # Tuya power strips and multi-socket plugs
    ChildDeviceMatch(models=frozenset({"TS011F", "TS0115"})),
    # Tuya dual cover and dual dimmer modules
    ChildDeviceMatch(models=frozenset({"TS130F", "TS110E"})),
    # Aqara / Xiaomi multi-channel relays and wall switches
    ChildDeviceMatch(
        manufacturers=frozenset({"LUMI", "Aqara"}),
        models=frozenset(
            {
                "lumi.relay.c2acn01",
                "lumi.switch.acn047",
                "lumi.switch.b2naus01",
                "lumi.switch.b2nc01",
                "lumi.switch.l2aeu1",
            }
        ),
    ),
    ChildDeviceMatch(manufacturers=frozenset({"AEOTEC"}), models=frozenset({"ZGA004"})),
    ChildDeviceMatch(
        manufacturers=frozenset({"Aurora"}), models=frozenset({"DoubleSocket50AU"})
    ),
    ChildDeviceMatch(
        manufacturers=frozenset({"eWeLink"}), models=frozenset({"ZB-SW02"})
    ),
    ChildDeviceMatch(
        manufacturers=frozenset({"Sunricher"}), models=frozenset({"ON/OFF(2CH)"})
    ),
)


def is_child_device_allowlisted(manufacturer: str, model: str) -> bool:
    """Return whether the device's output endpoints are split into child devices."""
    return any(match.matches(manufacturer, model) for match in CHILD_DEVICE_ALLOWLIST)


def _entity_kind(entity: PlatformEntity) -> tuple[object, ...]:
    """Return what makes entities on different endpoints "the same" entity."""
    return (
        entity.PLATFORM,
        type(entity),
        entity.cluster.cluster_id,
        entity._unique_id_suffix,  # noqa: SLF001
    )


def compute_output_child_devices(
    entities: Iterable[PlatformEntity],
) -> tuple[tuple[ChildDevice, ...], dict[PlatformEntity, ChildDevice]]:
    """Split the output endpoints of a device into child devices.

    An endpoint is an output endpoint when it carries an enabled-by-default entity of
    an output platform (e.g. a switch), without an entity category, and a sibling
    endpoint carries one of the same platform. Each output endpoint becomes a child
    device named "Channel <n>", numbered in endpoint order.

    Only entities that are repeated on another output endpoint move to the child
    device. Everything else, such as a meter for the whole device that is only on the
    first endpoint or a device-wide setting, stays on the main device.
    """
    entities = list(entities)

    output_platform_endpoints: defaultdict[Platform, set[int]] = defaultdict(set)
    for entity in entities:
        if entity.PLATFORM in OUTPUT_PLATFORMS and entity.entity_category is None:
            output_platform_endpoints[entity.PLATFORM].add(entity.endpoint.id)

    output_endpoints = sorted(
        {
            endpoint_id
            for endpoint_ids in output_platform_endpoints.values()
            if len(endpoint_ids) > 1
            for endpoint_id in endpoint_ids
        }
    )

    if not output_endpoints:
        return (), {}

    child_devices = {
        endpoint_id: ChildDevice(
            id=str(endpoint_id),
            endpoint_ids=frozenset({endpoint_id}),
            translation_key=CHILD_DEVICE_TRANSLATION_KEY_CHANNEL,
            translation_placeholders={"index": str(index)},
            fallback_name=f"Channel {index}",
        )
        for index, endpoint_id in enumerate(output_endpoints, start=1)
    }

    kind_endpoints: defaultdict[tuple[object, ...], set[int]] = defaultdict(set)
    for entity in entities:
        if entity.endpoint.id in child_devices:
            kind_endpoints[_entity_kind(entity)].add(entity.endpoint.id)

    assignments: dict[PlatformEntity, ChildDevice] = {}
    for entity in entities:
        child_device = child_devices.get(entity.endpoint.id)

        if (
            child_device is None
            or entity.cluster.cluster_id in DEVICE_LEVEL_CLUSTERS
            or len(kind_endpoints[_entity_kind(entity)]) < 2
        ):
            continue

        assignments[entity] = child_device

    return tuple(child_devices.values()), assignments


def assign_endpoint_child_devices(
    child_devices: Iterable[ChildDevice],
    entities: Iterable[PlatformEntity],
) -> dict[PlatformEntity, ChildDevice]:
    """Assign entities to explicitly defined (e.g. by a quirk) child devices.

    All entities on an endpoint of a child device belong to it, except entities of
    device-level clusters.
    """
    by_endpoint: dict[int, ChildDevice] = {}
    for child_device in child_devices:
        for endpoint_id in child_device.endpoint_ids:
            if endpoint_id in by_endpoint:
                raise ValueError(
                    f"Endpoint {endpoint_id} is assigned to both child device"
                    f" {by_endpoint[endpoint_id].id!r} and {child_device.id!r}"
                )
            by_endpoint[endpoint_id] = child_device

    assignments: dict[PlatformEntity, ChildDevice] = {}
    for entity in entities:
        endpoint_child_device = by_endpoint.get(entity.endpoint.id)

        if (
            endpoint_child_device is not None
            and entity.cluster.cluster_id not in DEVICE_LEVEL_CLUSTERS
        ):
            assignments[entity] = endpoint_child_device

    return assignments


def apply_explicit_child_devices(
    child_devices: Iterable[ChildDevice],
    assignments: Mapping[PlatformEntity, ChildDevice],
    entities: Iterable[PlatformEntity],
) -> dict[PlatformEntity, ChildDevice]:
    """Apply the explicit child device assignments of entities (e.g. from a quirk)."""
    by_id = {child_device.id: child_device for child_device in child_devices}
    result = dict(assignments)

    for entity in entities:
        child_device_id = entity.explicit_child_device_id

        if child_device_id is UNDEFINED:
            continue

        if child_device_id is None:
            result.pop(entity, None)
            continue

        if (child_device := by_id.get(child_device_id)) is None:
            _LOGGER.warning(
                "Entity %s refers to unknown child device %r, keeping it on the main"
                " device",
                entity,
                child_device_id,
            )
            result.pop(entity, None)
            continue

        result[entity] = child_device

    return result
