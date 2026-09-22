"""Events on Zigbee Home Automation networks."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Final

from zigpy.types.named import EUI64
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.clusters.lighting import Color
from zigpy.zcl.foundation import CommandSchema

from zha.application import Platform
from zha.application.platforms import (
    BaseEntityState,
    ClusterMatch,
    PlatformEntity,
    register_entity,
)
from zha.application.platforms.event.const import DoorbellEventType, EventDeviceClass

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


@dataclasses.dataclass(frozen=True, kw_only=True)
class EventState(BaseEntityState):
    """State for event entities."""

    event_types: list[str]


@dataclasses.dataclass(frozen=True, kw_only=True)
class TriggeredEvent:
    """The event an event entity fired."""

    event_type: str
    event_attributes: dict[str, Any]


@dataclasses.dataclass(frozen=True, kw_only=True)
class EntityEventTriggeredEvent:
    """Event for when an event entity fires."""

    event_type: Final[str] = "entity"
    event: Final[str] = "event_triggered"
    platform: str
    unique_id: str
    device_ieee: EUI64 | None = None
    endpoint_id: int | None = None
    group_id: int | None = None
    triggered: TriggeredEvent


class BaseEvent(PlatformEntity):
    """Base representation of a ZHA event entity."""

    PLATFORM = Platform.EVENT

    _attr_device_class: EventDeviceClass | None = None
    _attr_event_types: list[str]

    def __init__(self, endpoint: Endpoint, device: Device, **kwargs: Any) -> None:
        """Initialize the event entity."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)

        # Doorbells are expected to ring: the `doorbell.rang` trigger matches on it
        if (
            self.device_class == EventDeviceClass.DOORBELL
            and DoorbellEventType.RING not in self.event_types
        ):
            raise ValueError(
                f"Doorbell event entity {self.unique_id} does not support the"
                f" '{DoorbellEventType.RING}' event type"
            )

    @property
    def event_types(self) -> list[str]:
        """Return the event types this entity can trigger."""
        return self._attr_event_types

    @property
    def state(self) -> EventState:
        """Return the state of the event entity."""
        return EventState(**super().state.__dict__, event_types=self.event_types)

    def _trigger_event(
        self, event_type: str, event_attributes: dict[str, Any] | None = None
    ) -> None:
        """Trigger an event, to be called by subclasses."""
        if event_type not in self.event_types:
            raise ValueError(f"Invalid event type {event_type} for {self.unique_id}")

        self.emit(
            EntityEventTriggeredEvent.event,
            EntityEventTriggeredEvent(
                **self.identifiers.__dict__,
                triggered=TriggeredEvent(
                    event_type=event_type,
                    event_attributes=event_attributes or {},
                ),
            ),
        )


class ClusterCommandEvent(BaseEvent):
    """Event entity driven by commands received on its bound client cluster."""

    def on_add(self) -> None:
        """Listen for commands on the bound client cluster."""
        super().on_add()
        self._cluster.add_listener(self)
        self._on_remove_callbacks.append(lambda: self._cluster.remove_listener(self))

    def cluster_command(self, tsn: int, command_id: int, args: Any) -> None:
        """Trigger an event for an incoming client cluster command."""
        if (command := self._cluster.server_commands.get(command_id)) is None:
            return

        event_attributes = (
            args.as_dict(skip_missing=True, recursive=True)
            if isinstance(args, CommandSchema)
            else {}
        )
        self._trigger_event(command.name, event_attributes)


@register_entity(LevelControl.cluster_id)
class LevelControlEvent(ClusterCommandEvent):
    """Representation of a ZHA entity with level control events."""

    _attr_translation_key = "level_control"
    _attr_event_types = [
        "step",
        "step_with_on_off",
        "stop",
        "move",
        "move_with_on_off",
        "move_to_level",
        "move_to_level_with_on_off",
    ]
    _cluster_match = ClusterMatch(
        client_clusters=frozenset({LevelControl.cluster_id}),
    )


@register_entity(OnOff.cluster_id)
class OnOffEvent(ClusterCommandEvent):
    """Representation of a ZHA entity with on/off events."""

    _attr_translation_key = "on_off"
    _attr_event_types = [
        "off",
        "on",
        "toggle",
        "off_with_effect",
        "on_with_recall_global_scene",
        "on_with_timed_off",
    ]
    _cluster_match = ClusterMatch(
        client_clusters=frozenset({OnOff.cluster_id}),
    )


@register_entity(Color.cluster_id)
class ColorEvent(ClusterCommandEvent):
    """Representation of a ZHA entity with color cluster events."""

    _attr_translation_key = "color"
    _attr_event_types = [
        "move_to_hue",
        "move_hue",
        "step_hue",
        "move_to_saturation",
        "move_saturation",
        "step_saturation",
        "move_to_hue_and_saturation",
        "move_to_color",
        "move_color",
        "step_color",
        "move_to_color_temp",
        "enhanced_move_to_hue",
        "enhanced_move_hue",
        "enhanced_step_hue",
        "enhanced_move_to_hue_and_saturation",
        "color_loop_set",
        "stop_move_step",
        "move_color_temp",
        "step_color_temp",
    ]
    _cluster_match = ClusterMatch(
        client_clusters=frozenset({Color.cluster_id}),
    )
