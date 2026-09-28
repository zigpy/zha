"""Events on Zigbee Home Automation networks."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Final

from zigpy.types.named import EUI64

from zha.application import Platform
from zha.application.platforms import BaseEntityState, PlatformEntity
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
