"""Test the ZHA event platform."""

from typing import Any

import pytest
from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl.clusters import general

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    zigpy_device_from_json,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityStateChangedEvent, ZclPlatformEntity
from zha.application.platforms.event import (
    BaseEvent,
    EntityEventTriggeredEvent,
    EventState,
    TriggeredEvent,
    ZhaEventButton,
    ZhaEventMatch,
    _event_data_matches,
)
from zha.application.platforms.event.const import (
    ATTR_PRESS_COUNT,
    ButtonEventType,
    EventDeviceClass,
)
from zha.zigbee.device import Device


class FakeEvent(BaseEvent, ZclPlatformEntity):
    """ZCL-backed event entity with a fixed set of event types."""

    _unique_id_suffix = "fake"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = [
        ButtonEventType.PRESS_END,
        ButtonEventType.SINGLE_PRESS,
        ButtonEventType.MULTI_PRESS,
    ]

    def trigger(
        self, event_type: str, event_attributes: dict[str, Any] | None = None
    ) -> None:
        """Trigger an event, as a concrete subclass would."""
        self._trigger_event(event_type, event_attributes)


class FakeDoorbellEvent(FakeEvent):
    """Doorbell event entity that cannot ring."""

    _attr_device_class = EventDeviceClass.DOORBELL


class FakeMultiPressOnlyEvent(FakeEvent):
    """Button event entity with a multi press but no single press."""

    _attr_event_types = [ButtonEventType.PRESS_END, ButtonEventType.MULTI_PRESS]


class FakeMultiPressExtraEvent(FakeEvent):
    """Event entity without a device class using `multi_press` as its own type."""

    _attr_device_class = None
    _attr_event_types = [ButtonEventType.MULTI_PRESS]


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
    assert entity.event_types == ["press_end", "single_press", "multi_press"]

    state = entity.state
    assert isinstance(state, EventState)
    assert state.event_types == ["press_end", "single_press", "multi_press"]


async def test_trigger_event(entity: FakeEvent) -> None:
    """Test triggering events."""
    events: list[EntityEventTriggeredEvent] = []
    unsub = entity.on_event(EntityEventTriggeredEvent.event, events.append)

    # Nothing is delivered until an event is actually triggered
    assert events == []

    entity.trigger(ButtonEventType.MULTI_PRESS, {ATTR_PRESS_COUNT: 2})
    assert events == [
        EntityEventTriggeredEvent(
            platform=Platform.EVENT,
            unique_id=entity.unique_id,
            device_ieee=entity.device.ieee,
            endpoint_id=1,
            triggered=TriggeredEvent(
                event_type="multi_press",
                event_attributes={"press_count": 2},
            ),
        )
    ]

    # An event identical to the previous one is still delivered
    entity.trigger(ButtonEventType.MULTI_PRESS, {ATTR_PRESS_COUNT: 2})
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


async def test_multi_press_requires_single_press(zha_device: Device) -> None:
    """Test that a button only declares `multi_press` together with `single_press`."""
    with pytest.raises(
        ValueError,
        match="supports the 'multi_press' event type without 'single_press'",
    ):
        create_event_entity(zha_device, FakeMultiPressOnlyEvent)


@pytest.mark.parametrize(
    "event_attributes",
    [
        None,
        {},
        {ATTR_PRESS_COUNT: 1},
        {ATTR_PRESS_COUNT: 0},
        {ATTR_PRESS_COUNT: "2"},
        {ATTR_PRESS_COUNT: True},
        {ATTR_PRESS_COUNT: 2.0},
    ],
)
async def test_multi_press_requires_press_count(
    entity: FakeEvent, event_attributes: dict[str, Any] | None
) -> None:
    """Test that a button `multi_press` carries a press count of at least 2."""
    events: list[EntityEventTriggeredEvent] = []
    entity.on_event(EntityEventTriggeredEvent.event, events.append)

    with pytest.raises(ValueError, match="Invalid press_count"):
        entity.trigger(ButtonEventType.MULTI_PRESS, event_attributes)

    assert events == []


async def test_multi_press_rules_only_apply_to_buttons(zha_device: Device) -> None:
    """Test that the button rules leave other event entities alone."""
    entity = create_event_entity(zha_device, FakeMultiPressExtraEvent)

    events: list[EntityEventTriggeredEvent] = []
    entity.on_event(EntityEventTriggeredEvent.event, events.append)
    entity.trigger(ButtonEventType.MULTI_PRESS)

    assert [event.triggered.event_type for event in events] == ["multi_press"]


TOGGLE = {"cluster_id": general.OnOff.cluster_id, "command": "toggle"}
MOVE_UP = {
    "cluster_id": general.LevelControl.cluster_id,
    "command": "move",
    "params": {"move_mode": general.LevelControl.MoveMode.Up},
}
STOP = {"cluster_id": general.LevelControl.cluster_id, "command": "stop"}


def create_event_button(
    zha_device: Device, event_matches: list[ZhaEventMatch]
) -> ZhaEventButton:
    """Create a `zha_event` button entity on the first endpoint of a device."""
    endpoint = zha_device.endpoints[1]
    entity = ZhaEventButton(
        endpoint=endpoint,
        device=zha_device,
        cluster=endpoint.zigpy_endpoint.out_clusters[general.OnOff.cluster_id],
        event_matches=event_matches,
        from_quirk=True,
        unique_id_suffix="button",
        translation_key="button",
        fallback_name="Button",
    )
    entity.on_add()
    return entity


def fired_event_types(entity: ZhaEventButton) -> list[str]:
    """Collect the event types an entity fires from now on."""
    event_types: list[str] = []
    entity.on_event(
        EntityEventTriggeredEvent.event,
        lambda event: event_types.append(event.triggered.event_type),
    )
    return event_types


def emit_zha_event(zha_device: Device, data: dict[str, Any]) -> None:
    """Emit a `zha_event` from the first endpoint of a device."""
    zha_device.endpoints[1].emit_zha_event(data)


@pytest.mark.parametrize(
    ("expected", "data", "matches"),
    [
        ({"command": "on"}, {"command": "on", "cluster_id": 6}, True),
        ({"command": "on"}, {"command": "off", "cluster_id": 6}, False),
        ({"command": "on", "endpoint_id": 2}, {"command": "on"}, False),
        # Nested mappings only need to contain the expected keys
        (
            {"params": {"button": 1}},
            {"params": {"button": 1, "press_type": 0}},
            True,
        ),
        ({"params": {"button": 1}}, {"params": {"button": 2}}, False),
        ({"params": {"button": 1}}, {"params": [1]}, False),
        ({"args": {"value": 1}}, {"args": {"attribute_id": 85, "value": 1}}, True),
        # Sequences have to be equal, lists and tuples alike
        ({"args": (1, 2)}, {"args": [1, 2]}, True),
        ({"args": [1, 2]}, {"args": (1, 2)}, True),
        ({"args": [1]}, {"args": [1, 2]}, False),
        ({"args": []}, {"args": []}, True),
        ({"args": [1, 2]}, {"args": "12"}, False),
        # Nested sequences and mappings inside sequences, as frozen by quirks
        ({"args": ((1, 2),)}, {"args": [[1, 2]]}, True),
        ({"args": ((1, 2),)}, {"args": [[1, 3]]}, False),
        ({"args": ({"a": 1},)}, {"args": [{"a": 1, "b": 2}]}, True),
        ({"args": ({"a": 1},)}, {"args": [{"b": 2}]}, False),
    ],
)
def test_event_data_matches(
    expected: dict[str, Any], data: dict[str, Any], matches: bool
) -> None:
    """Test matching `zha_event` data like a device automation trigger."""
    assert _event_data_matches(expected, data) is matches


async def test_zha_event_button(zha_gateway: Gateway) -> None:
    """Test a button event entity firing for the commands a remote sends."""
    zigpy_dev = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/innr-rc-250-0x21086500.json",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)

    entity = create_event_button(
        zha_device,
        [
            ZhaEventMatch(event_type=ButtonEventType.PRESS_END, event_data=TOGGLE),
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_START, event_data=MOVE_UP
            ),
            ZhaEventMatch(event_type=ButtonEventType.LONG_PRESS_END, event_data=STOP),
        ],
    )
    assert entity.device_class == EventDeviceClass.BUTTON
    assert entity.event_types == ["press_end", "long_press_start", "long_press_end"]
    assert entity.unique_id == f"{zha_device.ieee}-1-button"

    events: list[EntityEventTriggeredEvent] = []
    entity.on_event(EntityEventTriggeredEvent.event, events.append)

    def send(tsn: int, cluster_id: int, payload: bytes) -> None:
        zigpy_dev.packet_received(
            zigpy.types.ZigbeePacket(
                src_ep=1,
                dst_ep=1,
                tsn=tsn,
                profile_id=zha.PROFILE_ID,
                cluster_id=cluster_id,
                data=zigpy.types.SerializableBytes(payload),
            )
        )

    # OnOff toggle: the `attribute_updated` zha_event in front of it matches nothing
    send(1, general.OnOff.cluster_id, b"\x01\x01\x02")
    # LevelControl move(Up, 50), move(Down, 50) and stop
    send(2, general.LevelControl.cluster_id, b"\x01\x02\x01\x00\x32")
    send(3, general.LevelControl.cluster_id, b"\x01\x03\x01\x01\x32")
    send(4, general.LevelControl.cluster_id, b"\x01\x04\x03")

    assert [event.triggered for event in events] == [
        TriggeredEvent(event_type="press_end", event_attributes={}),
        TriggeredEvent(event_type="long_press_start", event_attributes={}),
        TriggeredEvent(event_type="long_press_end", event_attributes={}),
    ]
    assert {event.unique_id for event in events} == {entity.unique_id}

    # The entity stops listening once it is removed
    await entity.on_remove()
    send(5, general.OnOff.cluster_id, b"\x01\x05\x02")
    assert len(events) == 3


async def test_zha_event_button_first_match_fires(zha_device: Device) -> None:
    """Test that one `zha_event` fires at most one event type."""
    entity = create_event_button(
        zha_device,
        [
            ZhaEventMatch(
                event_type=ButtonEventType.SINGLE_PRESS,
                event_data={"command": "press", "params": {"count": 1}},
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.MULTI_PRESS,
                event_data={"command": "press", "params": {"count": 2}},
                event_attributes={ATTR_PRESS_COUNT: 2},
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.PRESS_END, event_data={"command": "press"}
            ),
        ],
    )
    events: list[EntityEventTriggeredEvent] = []
    entity.on_event(EntityEventTriggeredEvent.event, events.append)

    emit_zha_event(zha_device, {"command": "press", "params": {"count": 2}})
    emit_zha_event(zha_device, {"command": "press", "params": {"count": 1}})
    emit_zha_event(zha_device, {"command": "press", "params": {"count": 3}})
    emit_zha_event(zha_device, {"command": "release"})

    assert [event.triggered for event in events] == [
        TriggeredEvent(event_type="multi_press", event_attributes={"press_count": 2}),
        TriggeredEvent(event_type="single_press", event_attributes={}),
        TriggeredEvent(event_type="press_end", event_attributes={}),
    ]


async def test_zha_event_button_repeated_hold(zha_device: Device) -> None:
    """Test that a hold the device repeats fires `long_press_start` once."""
    entity = create_event_button(
        zha_device,
        [
            ZhaEventMatch(
                event_type=ButtonEventType.PRESS_END, event_data={"command": "release"}
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_START,
                event_data={"command": "hold"},
                repeats=True,
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_END,
                event_data={"command": "long_release"},
            ),
        ],
    )
    event_types = fired_event_types(entity)

    for command in (
        "hold",
        "hold",
        "hold",
        "long_release",
        "hold",
        "hold",
        "release",  # a release of another kind ends the hold as well
        "hold",
        "unknown",  # a `zha_event` that does not match changes nothing
        "hold",
    ):
        emit_zha_event(zha_device, {"command": command})

    assert event_types == [
        "long_press_start",
        "long_press_end",
        "long_press_start",
        "press_end",
        "long_press_start",
    ]


async def test_zha_event_button_release_while_held(zha_device: Device) -> None:
    """Test that a release the device does not classify ends a hold if one started."""
    entity = create_event_button(
        zha_device,
        [
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_START,
                event_data={"command": "hold"},
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_END,
                event_data={"command": "release"},
                while_held=True,
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.PRESS_END, event_data={"command": "release"}
            ),
        ],
    )
    event_types = fired_event_types(entity)

    for command in ("release", "hold", "release", "release", "hold", "hold"):
        emit_zha_event(zha_device, {"command": command})

    assert event_types == [
        "press_end",
        "long_press_start",
        "long_press_end",
        "press_end",
        "long_press_start",
        "long_press_start",
    ]


async def test_zha_event_button_release_while_held_any_order(
    zha_device: Device,
) -> None:
    """Test that a release while held wins over a release listed before it."""
    entity = create_event_button(
        zha_device,
        [
            ZhaEventMatch(
                event_type=ButtonEventType.PRESS_END, event_data={"command": "release"}
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_START,
                event_data={"command": "hold"},
            ),
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_END,
                event_data={"command": "release"},
                while_held=True,
            ),
        ],
    )
    event_types = fired_event_types(entity)
    assert entity.event_types == ["press_end", "long_press_start", "long_press_end"]

    for command in ("release", "hold", "release", "release"):
        emit_zha_event(zha_device, {"command": command})

    assert event_types == [
        "press_end",
        "long_press_start",
        "long_press_end",
        "press_end",
    ]


async def test_zha_event_button_error_keeps_zha_event(
    zha_device: Device, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that an error in an event listener does not keep the zha_event from others."""
    entity = create_event_button(
        zha_device,
        [ZhaEventMatch(event_type=ButtonEventType.PRESS_END, event_data=TOGGLE)],
    )

    def fail(event: EntityEventTriggeredEvent) -> None:
        raise RuntimeError("listener failed")

    entity.on_event(EntityEventTriggeredEvent.event, fail)

    zha_events: list[Any] = []
    zha_device.on_all_events(zha_events.append)

    emit_zha_event(zha_device, TOGGLE)

    assert len(zha_events) == 1
    assert "Error calling listener" in caplog.text
    assert "listener failed" in caplog.text


async def test_zha_event_button_matching_error_keeps_zha_event(
    zha_device: Device,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that an error while firing an event does not keep the zha_event from others."""
    entity = create_event_button(
        zha_device,
        [ZhaEventMatch(event_type=ButtonEventType.PRESS_END, event_data=TOGGLE)],
    )

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("trigger failed")

    monkeypatch.setattr(entity, "_trigger_event", fail)

    zha_events: list[Any] = []
    zha_device.on_all_events(zha_events.append)

    emit_zha_event(zha_device, TOGGLE)

    assert len(zha_events) == 1
    assert "Failed to handle zha_event" in caplog.text
    assert "trigger failed" in caplog.text


async def test_zha_event_button_release_of_held_button(zha_device: Device) -> None:
    """Test that a release shared by two buttons only ends the hold of the held one."""
    left, right = (
        create_event_button(
            zha_device,
            [
                ZhaEventMatch(
                    event_type=ButtonEventType.LONG_PRESS_START,
                    event_data={"command": "hold", "params": {"button": button}},
                ),
                ZhaEventMatch(
                    event_type=ButtonEventType.LONG_PRESS_END,
                    event_data={"command": "release"},
                    while_held=True,
                ),
            ],
        )
        for button in ("left", "right")
    )
    left_event_types = fired_event_types(left)
    right_event_types = fired_event_types(right)

    emit_zha_event(zha_device, {"command": "release"})
    emit_zha_event(zha_device, {"command": "hold", "params": {"button": "left"}})
    emit_zha_event(zha_device, {"command": "release"})
    emit_zha_event(zha_device, {"command": "release"})
    emit_zha_event(zha_device, {"command": "hold", "params": {"button": "right"}})
    emit_zha_event(zha_device, {"command": "release"})

    assert left_event_types == ["long_press_start", "long_press_end"]
    assert right_event_types == ["long_press_start", "long_press_end"]


async def test_zha_event_button_hold_without_repeats(zha_device: Device) -> None:
    """Test that a hold match that does not repeat fires for every event."""
    entity = create_event_button(
        zha_device,
        [
            ZhaEventMatch(
                event_type=ButtonEventType.LONG_PRESS_START,
                event_data={"command": "hold"},
            ),
        ],
    )
    event_types = fired_event_types(entity)

    emit_zha_event(zha_device, {"command": "hold"})
    emit_zha_event(zha_device, {"command": "hold"})

    assert event_types == ["long_press_start", "long_press_start"]


async def test_zha_event_button_ignores_other_devices(
    zha_gateway: Gateway, zha_device: Device
) -> None:
    """Test that an entity only listens to the `zha_event`s of its own device."""
    other_device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            {
                1: {
                    SIG_EP_INPUT: [general.Basic.cluster_id],
                    SIG_EP_OUTPUT: [general.OnOff.cluster_id],
                    SIG_EP_TYPE: zha.DeviceType.NON_COLOR_CONTROLLER,
                    SIG_EP_PROFILE: zha.PROFILE_ID,
                }
            },
            ieee="01:2d:6f:00:0a:90:69:e8",
        ),
    )
    entity = create_event_button(
        zha_device,
        [ZhaEventMatch(event_type=ButtonEventType.PRESS_END, event_data=TOGGLE)],
    )
    event_types = fired_event_types(entity)

    emit_zha_event(other_device, TOGGLE)
    assert event_types == []

    emit_zha_event(zha_device, TOGGLE)
    assert event_types == ["press_end"]


@pytest.mark.parametrize(
    ("event_matches", "error"),
    [
        ([], "has no events"),
        (
            [
                ZhaEventMatch(
                    event_type=ButtonEventType.SINGLE_PRESS,
                    event_data={"command": "single"},
                ),
                ZhaEventMatch(
                    event_type=ButtonEventType.MULTI_PRESS,
                    event_data={"command": "double"},
                ),
            ],
            "Invalid press_count None for 'multi_press'",
        ),
        (
            [
                ZhaEventMatch(
                    event_type=ButtonEventType.SINGLE_PRESS,
                    event_data={"command": "single"},
                ),
                ZhaEventMatch(
                    event_type=ButtonEventType.MULTI_PRESS,
                    event_data={"command": "double"},
                    event_attributes={ATTR_PRESS_COUNT: 1},
                ),
            ],
            "Invalid press_count 1 for 'multi_press'",
        ),
        (
            [
                ZhaEventMatch(
                    event_type=ButtonEventType.MULTI_PRESS,
                    event_data={"command": "double"},
                    event_attributes={ATTR_PRESS_COUNT: 2},
                ),
            ],
            "supports the 'multi_press' event type without 'single_press'",
        ),
        (
            [
                ZhaEventMatch(
                    event_type=ButtonEventType.LONG_PRESS_END,
                    event_data={"command": "release"},
                    while_held=True,
                ),
            ],
            "matches while held without 'long_press_start'",
        ),
        (
            [
                ZhaEventMatch(
                    event_type=ButtonEventType.LONG_PRESS_START,
                    event_data={"command": "hold"},
                    repeats=True,
                ),
            ],
            "repeats 'long_press_start' without other event types",
        ),
    ],
)
async def test_zha_event_button_invalid(
    zha_device: Device, event_matches: list[ZhaEventMatch], error: str
) -> None:
    """Test that invalid event matches are rejected when creating the entity."""
    with pytest.raises(ValueError, match=error):
        create_event_button(zha_device, event_matches)


def test_zha_event_match_invalid() -> None:
    """Test that invalid event matches are rejected."""
    with pytest.raises(ValueError, match="matches every zha_event"):
        ZhaEventMatch(event_type=ButtonEventType.PRESS_END, event_data={})

    with pytest.raises(ValueError, match="Only 'long_press_start' can repeat"):
        ZhaEventMatch(
            event_type=ButtonEventType.PRESS_END,
            event_data={"command": "release"},
            repeats=True,
        )

    with pytest.raises(ValueError, match="Only 'long_press_end' can match while held"):
        ZhaEventMatch(
            event_type=ButtonEventType.PRESS_END,
            event_data={"command": "release"},
            while_held=True,
        )
