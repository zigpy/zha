"""Events on Zigbee Home Automation networks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import dataclasses
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from zigpy.types.named import EUI64

from zha.application import Platform
from zha.application.const import ZHA_EVENT
from zha.application.platforms import BaseEntityState, PlatformEntity, ZclPlatformEntity
from zha.application.platforms.event.const import (
    ATTR_PRESS_COUNT,
    ButtonEventType,
    DoorbellEventType,
    EventDeviceClass,
)

if TYPE_CHECKING:
    from zha.zigbee.device import Device, ZHAEvent
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


def _event_data_matches(expected: Mapping[str, Any], data: Mapping[str, Any]) -> bool:
    """Return whether `zha_event` data contains the expected data.

    This follows the matching of ZHA device automation triggers: every expected key
    has to be present with an equal value, and nested mappings (such as `params`)
    only need to contain the expected keys. Lists and tuples compare equal when
    their items are equal, at any depth, as quirks store frozen trigger data.
    """
    return all(
        key in data and _event_value_matches(value, data[key])
        for key, value in expected.items()
    )


def _event_value_matches(expected: Any, actual: Any) -> bool:
    """Return whether a `zha_event` value matches the expected value."""
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and _event_data_matches(expected, actual)

    if isinstance(expected, list | tuple) and isinstance(actual, list | tuple):
        return len(expected) == len(actual) and all(
            _event_value_matches(item, actual_item)
            for item, actual_item in zip(expected, actual, strict=True)
        )

    return bool(actual == expected)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ZhaEventMatch:
    """An event type fired when the device sends a matching `zha_event`.

    `event_data` is matched like the data of a ZHA device automation trigger, so a
    trigger's data can be reused as is: the event fires for the `zha_event`s that the
    trigger's data matches.
    """

    event_type: str
    event_data: Mapping[str, Any]
    event_attributes: Mapping[str, Any] = dataclasses.field(
        default_factory=lambda: MappingProxyType({})
    )

    # The device repeats this event while the button is held. Only the first one
    # fires, until any other event of the entity fires. If the device's release is
    # lost, the whole next hold is taken for repeats, until its release.
    repeats: bool = False

    # Only match while the button is held, after a `long_press_start` of the entity
    # and before any other event of it, ahead of the entity's other matches. This
    # classifies a release the device does not tell apart, by button or from a
    # short press, as the end of the hold. If the release ending a hold is lost, the
    # next such release is taken for the end of the hold once.
    while_held: bool = False

    def __post_init__(self) -> None:
        """Validate the match."""
        if not self.event_data:
            raise ValueError(f"Event type {self.event_type} matches every zha_event")

        if self.repeats and self.event_type != ButtonEventType.LONG_PRESS_START:
            raise ValueError(
                f"Only '{ButtonEventType.LONG_PRESS_START}' can repeat, not"
                f" '{self.event_type}'"
            )

        if self.while_held and self.event_type != ButtonEventType.LONG_PRESS_END:
            raise ValueError(
                f"Only '{ButtonEventType.LONG_PRESS_END}' can match while held, not"
                f" '{self.event_type}'"
            )


class ZhaEventButton(BaseEvent, ZclPlatformEntity):
    """Button event entity firing standard event types for the device's `zha_event`s.

    Remotes report button presses as cluster commands, which ZHA relays as
    `zha_event`s. This entity maps them to event types: the first match for a
    `zha_event` fires, so one event from the device fires at most one event type.
    The only state it keeps is whether the button is held, to fire a repeated
    `long_press_start` once and to classify releases (`repeats`, `while_held`).
    """

    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        event_matches: Sequence[ZhaEventMatch],
        **kwargs: Any,
    ) -> None:
        """Initialize the event entity."""
        # Matches only applying while held go first, so they win over an
        # unconditional match on the same data in any order
        self._event_matches: tuple[ZhaEventMatch, ...] = tuple(
            sorted(event_matches, key=lambda match: not match.while_held)
        )
        self._attr_event_types = list(
            dict.fromkeys(match.event_type for match in event_matches)
        )
        self._held: bool = False

        super().__init__(endpoint=endpoint, device=device, **kwargs)

        if not self._event_matches:
            raise ValueError(f"Button event entity {self.unique_id} has no events")

        # A repeated hold is only fired again after another event of the entity
        if any(match.repeats for match in self._event_matches) and set(
            self.event_types
        ) == {ButtonEventType.LONG_PRESS_START}:
            raise ValueError(
                f"Button event entity {self.unique_id} repeats"
                f" '{ButtonEventType.LONG_PRESS_START}' without other event types"
            )

        if (
            any(match.while_held for match in self._event_matches)
            and ButtonEventType.LONG_PRESS_START not in self.event_types
        ):
            raise ValueError(
                f"Button event entity {self.unique_id} matches while held without"
                f" '{ButtonEventType.LONG_PRESS_START}'"
            )

        for match in self._event_matches:
            if match.event_type == ButtonEventType.MULTI_PRESS:
                press_count = match.event_attributes.get(ATTR_PRESS_COUNT)
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

    @property
    def event_matches(self) -> tuple[ZhaEventMatch, ...]:
        """Return the `zha_event` matches of this entity."""
        return self._event_matches

    def on_add(self) -> None:
        """Listen to the `zha_event`s of the device."""
        super().on_add()
        self._on_remove_callbacks.append(
            self.device.on_event(ZHA_EVENT, self._handle_zha_event)
        )

    def _handle_zha_event(self, event: ZHAEvent) -> None:
        """Fire the event type of the first match for a `zha_event`."""
        # `emit()` keeps the `zha_event` flowing to the device's other listeners
        # either way. Catching here logs the error with this entity and the event
        try:
            self._fire_first_match(event)
        except Exception:  # pylint: disable=broad-except
            self.error("Failed to handle zha_event %s", event.data, exc_info=True)

    def _fire_first_match(self, event: ZHAEvent) -> None:
        """Fire the event type of the first match for a `zha_event`."""
        for match in self._event_matches:
            if match.while_held and not self._held:
                continue

            if _event_data_matches(match.event_data, event.data):
                break
        else:
            return

        if match.repeats and self._held:
            return

        self._held = match.event_type == ButtonEventType.LONG_PRESS_START
        self._trigger_event(match.event_type, dict(match.event_attributes))
