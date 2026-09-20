"""Test the ZHA event platform."""

from typing import Any

import pytest
from zigpy.profiles import zha
from zigpy.zcl.clusters import general

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityStateChangedEvent
from zha.application.platforms.event import (
    BaseEvent,
    EntityEventTriggeredEvent,
    EventState,
    TriggeredEvent,
)
from zha.application.platforms.event.const import (
    ATTR_MULTI_PRESS_COUNT,
    ButtonEventType,
    EventDeviceClass,
)
from zha.zigbee.device import Device


class FakeEvent(BaseEvent):
    """Event entity with a fixed set of event types."""

    _unique_id_suffix = "fake"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [
        ButtonEventType.PRESS_END,
        ButtonEventType.MULTI_PRESS_END,
    ]

    def trigger(
        self, event_type: str, event_attributes: dict[str, Any] | None = None
    ) -> None:
        """Trigger an event, as a concrete subclass would."""
        self._trigger_event(event_type, event_attributes)


class FakeDoorbellEvent(FakeEvent):
    """Doorbell event entity that cannot ring."""

    _attr_device_class = EventDeviceClass.DOORBELL


@pytest.fixture
async def zha_device(zha_gateway: Gateway) -> Device:
    """Return a joined device to attach event entities to."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [general.OnOff.cluster_id],
                SIG_EP_TYPE: zha.DeviceType.NON_COLOR_CONTROLLER,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )
    return await join_zigpy_device(zha_gateway, zigpy_device)


def create_event_entity(zha_device: Device, entity_class: type[FakeEvent]) -> FakeEvent:
    """Create an event entity on the first endpoint of a device."""
    endpoint = zha_device.endpoints[1]

    return entity_class(
        endpoint=endpoint,
        device=zha_device,
        cluster=endpoint.zigpy_endpoint.out_clusters[general.OnOff.cluster_id],
    )


@pytest.fixture
def entity(zha_device: Device) -> FakeEvent:
    """Return an event entity for a joined device."""
    return create_event_entity(zha_device, FakeEvent)


async def test_event_state(entity: FakeEvent) -> None:
    """Test that the state of an event entity only describes its capabilities."""
    assert entity.PLATFORM == Platform.EVENT
    assert entity.device_class == EventDeviceClass.BUTTON
    assert entity.event_types == ["press_end", "multi_press_end"]

    state = entity.state
    assert isinstance(state, EventState)
    assert state.event_types == ["press_end", "multi_press_end"]


async def test_trigger_event(entity: FakeEvent) -> None:
    """Test triggering events."""
    events: list[EntityEventTriggeredEvent] = []
    unsub = entity.on_event(EntityEventTriggeredEvent.event, events.append)

    # Nothing is delivered until an event is actually triggered
    assert events == []

    entity.trigger(ButtonEventType.MULTI_PRESS_END, {ATTR_MULTI_PRESS_COUNT: 2})
    assert events == [
        EntityEventTriggeredEvent(
            platform=Platform.EVENT,
            unique_id=entity.unique_id,
            device_ieee=entity.device.ieee,
            endpoint_id=1,
            triggered=TriggeredEvent(
                event_type="multi_press_end",
                event_attributes={"multi_press_count": 2},
            ),
        )
    ]

    # An event identical to the previous one is still delivered
    entity.trigger(ButtonEventType.MULTI_PRESS_END, {ATTR_MULTI_PRESS_COUNT: 2})
    assert len(events) == 2
    assert events[0] == events[1]

    # Event attributes are optional
    entity.trigger(ButtonEventType.PRESS_END)
    assert events[-1].triggered == TriggeredEvent(
        event_type="press_end", event_attributes={}
    )

    unsub()
    entity.trigger(ButtonEventType.PRESS_END)
    assert len(events) == 3


async def test_trigger_event_does_not_change_state(entity: FakeEvent) -> None:
    """Test that triggering an event is not a state change."""
    state_changes: list[EntityStateChangedEvent] = []
    entity.subscribe_state(state_changes.append)
    assert len(state_changes) == 1

    entity.trigger(ButtonEventType.PRESS_END)
    assert len(state_changes) == 1


async def test_doorbell_must_ring(zha_device: Device) -> None:
    """Test that a doorbell event entity has to support the ring event type."""
    with pytest.raises(ValueError, match="does not support the 'ring' event type"):
        create_event_entity(zha_device, FakeDoorbellEvent)


async def test_trigger_unsupported_event(entity: FakeEvent) -> None:
    """Test that triggering an unsupported event type fails."""
    events: list[EntityEventTriggeredEvent] = []
    entity.on_event(EntityEventTriggeredEvent.event, events.append)

    with pytest.raises(ValueError, match="Invalid event type long_press_end"):
        entity.trigger(ButtonEventType.LONG_PRESS_END)

    assert events == []
