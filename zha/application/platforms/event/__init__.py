"""Events on Zigbee Home Automation networks."""

from __future__ import annotations

import dataclasses
from typing import Any, Final

from zigpy.types.named import EUI64

from zha.application import Platform
from zha.application.platforms import BaseEntityState, PlatformEntity
from zha.application.platforms.event.const import (
    ATTR_PRESS_COUNT,
    ButtonEventType,
    DoorbellEventType,
    EventDeviceClass,
)


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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the event entity."""
        super().__init__(*args, **kwargs)

        # Doorbells are expected to ring: the `doorbell.rang` trigger matches on it
        if (
            self.device_class == EventDeviceClass.DOORBELL
            and DoorbellEventType.RING not in self.event_types
        ):
            raise ValueError(
                f"Doorbell event entity {self.unique_id} does not support the"
                f" '{DoorbellEventType.RING}' event type"
            )

        # `multi_press` keeps `button.pressed` exclusive only next to `single_press`
        if (
            self.device_class == EventDeviceClass.BUTTON
            and ButtonEventType.MULTI_PRESS in self.event_types
            and ButtonEventType.SINGLE_PRESS not in self.event_types
        ):
            raise ValueError(
                f"Button event entity {self.unique_id} supports the"
                f" '{ButtonEventType.MULTI_PRESS}' event type without"
                f" '{ButtonEventType.SINGLE_PRESS}'"
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

        if (
            self.device_class == EventDeviceClass.BUTTON
            and event_type == ButtonEventType.MULTI_PRESS
        ):
            press_count = (event_attributes or {}).get(ATTR_PRESS_COUNT)
            if (
                not isinstance(press_count, int)
                or isinstance(press_count, bool)
                or press_count < 2
            ):
                raise ValueError(
                    f"Invalid {ATTR_PRESS_COUNT} {press_count!r} for"
                    f" '{ButtonEventType.MULTI_PRESS}' on {self.unique_id}:"
                    " it must be an integer of at least 2"
                )

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
