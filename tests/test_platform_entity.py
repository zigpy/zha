"""Test base platform entity state subscriptions."""

import dataclasses

from tests.common import (
    get_entity,
    join_zigpy_device,
    send_attributes_report,
    zigpy_device_from_json,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityStateChangedEvent
from zha.application.platforms.binary_sensor import Occupancy
from zha.event import suppress_events


async def test_subscribe_state(zha_gateway: Gateway) -> None:
    """Test that subscribing delivers the full state as the first event."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-snzb-06p-0x00001006.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, Platform.BINARY_SENSOR, entity_type=Occupancy)

    events: list[EntityStateChangedEvent] = []
    unsub = entity.subscribe_state(events.append)

    # The full current state is delivered synchronously as the first event
    assert len(events) == 1
    assert events[0].state_diff == vars(entity.state)
    assert events[0].state_diff["is_on"] is False

    # Subsequent changes arrive as granular diffs
    cluster = zigpy_device.endpoints[1].occupancy
    await send_attributes_report(zha_gateway, cluster, {"occupancy": 1})
    assert len(events) == 2
    assert events[1].state_diff == {"is_on": True}

    unsub()
    await send_attributes_report(zha_gateway, cluster, {"occupancy": 0})
    assert len(events) == 2


async def test_subscribe_state_flushes_pending_diff(zha_gateway: Gateway) -> None:
    """Test that subscribing flushes a pending diff to existing subscribers."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-snzb-06p-0x00001006.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, Platform.BINARY_SENSOR, entity_type=Occupancy)

    first_events: list[EntityStateChangedEvent] = []
    second_events: list[EntityStateChangedEvent] = []
    entity.subscribe_state(first_events.append)

    # Change state without an emit: the diff is now pending
    entity.enabled = False

    # A new subscription first flushes the pending diff to existing
    # subscribers, so its baseline is coherent with the diff stream
    entity.subscribe_state(second_events.append)

    assert first_events[-1].state_diff == {"enabled": False}
    assert second_events[0].state_diff == vars(entity.state)
    assert second_events[0].state_diff["enabled"] is False


async def test_suppress_events_advances_baseline(zha_gateway: Gateway) -> None:
    """Test that a suppressed emit stays silent but advances the diff baseline."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-snzb-06p-0x00001006.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, Platform.BINARY_SENSOR, entity_type=Occupancy)

    events: list[EntityStateChangedEvent] = []
    entity.subscribe_state(events.append)
    assert len(events) == 1

    with suppress_events():
        entity.enabled = False
        entity.maybe_emit_state_changed_event()

    # Nothing was emitted, and the baseline advanced: the change is not
    # re-emitted afterwards either
    assert len(events) == 1
    entity.maybe_emit_state_changed_event()
    assert len(events) == 1

    # A new subscriber's baseline does reflect the suppressed change
    second_events: list[EntityStateChangedEvent] = []
    entity.subscribe_state(second_events.append)
    assert second_events[0].state_diff["enabled"] is False


async def test_state_diff_round_trip(zha_gateway: Gateway) -> None:
    """Test that state reconstructed from diffs alone matches the entity state."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/sonoff-snzb-06p-0x00001006.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    entity = get_entity(zha_device, Platform.BINARY_SENSOR, entity_type=Occupancy)

    events: list[EntityStateChangedEvent] = []
    entity.subscribe_state(events.append)

    cluster = zigpy_device.endpoints[1].occupancy
    await send_attributes_report(zha_gateway, cluster, {"occupancy": 1})
    entity.enabled = False
    entity.maybe_emit_state_changed_event()
    await send_attributes_report(zha_gateway, cluster, {"occupancy": 0})

    # A consumer that only ever saw the event stream reconstructs the state
    client_state = type(entity.state)(**events[0].state_diff)
    for event in events[1:]:
        client_state = dataclasses.replace(client_state, **event.state_diff)

    assert client_state == entity.state
