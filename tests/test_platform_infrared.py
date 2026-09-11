"""Test the ZHA infrared platform."""

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
from zha.application.platforms.infrared import (
    BaseInfraredEmitter,
    BaseInfraredReceiver,
    EntityInfraredSignalReceivedEvent,
    InfraredReceiverState,
    InfraredSignal,
)
from zha.application.platforms.infrared.const import InfraredDeviceClass
from zha.zigbee.device import Device


class FakeEmitter(BaseInfraredEmitter):
    """Emitter that records what it was asked to transmit."""

    _unique_id_suffix = "fake_emitter"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the fake emitter."""
        super().__init__(*args, **kwargs)
        self.sent: list[InfraredSignal] = []

    async def async_send_command(self, signal: InfraredSignal) -> None:
        """Record the signal instead of transmitting it."""
        self.sent.append(signal)


class FakeReceiver(BaseInfraredReceiver):
    """Receiver that records the receive mode requests it was given."""

    _unique_id_suffix = "fake_receiver"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the fake receiver."""
        super().__init__(*args, **kwargs)
        self.requests: list[str] = []

    async def _async_start_receiving(self) -> None:
        """Record the request to enter receive mode."""
        self.requests.append("start")

    async def _async_stop_receiving(self) -> None:
        """Record the request to leave receive mode."""
        self.requests.append("stop")

    def receive(self, signal: InfraredSignal) -> None:
        """Capture a signal, as a concrete subclass would."""
        self._handle_received_signal(signal)

    def time_out(self) -> None:
        """Report the device's own receive timeout lapsing."""
        self._handle_receive_mode_ended()


class FakeOneShotReceiver(FakeReceiver):
    """Receiver whose device leaves receive mode as soon as it captures a signal."""

    def receive(self, signal: InfraredSignal) -> None:
        """Capture a signal and leave receive mode."""
        super().receive(signal)
        self._handle_receive_mode_ended()


@pytest.fixture
async def zha_device(zha_gateway: Gateway) -> Device:
    """Return a joined device to attach infrared entities to."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [general.OnOff.cluster_id],
                SIG_EP_TYPE: zha.DeviceType.REMOTE_CONTROL,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )
    return await join_zigpy_device(zha_gateway, zigpy_device)


def create_infrared_entity[T: BaseInfraredEmitter | BaseInfraredReceiver](
    zha_device: Device, entity_class: type[T]
) -> T:
    """Create an infrared entity on the first endpoint of a device."""
    endpoint = zha_device.endpoints[1]

    return entity_class(
        endpoint=endpoint,
        device=zha_device,
        cluster=endpoint.zigpy_endpoint.on_off,
    )


@pytest.fixture
def emitter(zha_device: Device) -> FakeEmitter:
    """Return an infrared emitter entity for a joined device."""
    return create_infrared_entity(zha_device, FakeEmitter)


@pytest.fixture
def receiver(zha_device: Device) -> FakeReceiver:
    """Return an infrared receiver entity for a joined device."""
    return create_infrared_entity(zha_device, FakeReceiver)


async def test_emitter(emitter: FakeEmitter) -> None:
    """Test that an emitter transmits raw signals."""
    assert emitter.PLATFORM == Platform.INFRARED
    assert emitter.device_class == InfraredDeviceClass.EMITTER

    signal = InfraredSignal(timings=[9000, -4500, 560, -1690], modulation=38000)
    await emitter.async_send_command(signal)
    assert emitter.sent == [signal]


async def test_receiver_state(receiver: FakeReceiver) -> None:
    """Test the state of a receiver entity."""
    assert receiver.PLATFORM == Platform.INFRARED
    assert receiver.device_class == InfraredDeviceClass.RECEIVER

    state = receiver.state
    assert isinstance(state, InfraredReceiverState)
    assert state.receiving is False


async def test_start_and_stop_receiving(receiver: FakeReceiver) -> None:
    """Test entering and leaving receive mode."""
    state_changes: list[EntityStateChangedEvent] = []
    receiver.subscribe_state(state_changes.append)
    assert len(state_changes) == 1

    await receiver.async_start_receiving()
    assert receiver.requests == ["start"]
    assert receiver.receiving is True
    assert state_changes[-1].state_diff == {"receiving": True}

    await receiver.async_stop_receiving()
    assert receiver.requests == ["start", "stop"]
    assert receiver.receiving is False
    assert state_changes[-1].state_diff == {"receiving": False}


async def test_stop_receiving_when_idle(receiver: FakeReceiver) -> None:
    """Test that stopping when not receiving does not reach the device."""
    await receiver.async_stop_receiving()
    assert receiver.requests == []
    assert receiver.receiving is False


async def test_receive_mode_ended_by_device(receiver: FakeReceiver) -> None:
    """Test the device leaving receive mode on its own timeout."""
    await receiver.async_start_receiving()

    receiver.time_out()
    assert receiver.receiving is False

    # The device stopped on its own, so it is not asked to
    assert receiver.requests == ["start"]


async def test_received_signal(receiver: FakeReceiver) -> None:
    """Test capturing signals."""
    signals: list[EntityInfraredSignalReceivedEvent] = []
    unsub = receiver.on_event(EntityInfraredSignalReceivedEvent.event, signals.append)

    # Nothing is delivered until a signal is actually captured
    assert signals == []

    await receiver.async_start_receiving()
    receiver.receive(InfraredSignal(timings=[9000, -4500], modulation=38000))
    assert signals == [
        EntityInfraredSignalReceivedEvent(
            platform=Platform.INFRARED,
            unique_id=receiver.unique_id,
            device_ieee=receiver.device.ieee,
            endpoint_id=1,
            signal=InfraredSignal(timings=[9000, -4500], modulation=38000),
        )
    ]

    # An identical signal is still delivered
    receiver.receive(InfraredSignal(timings=[9000, -4500], modulation=38000))
    assert len(signals) == 2
    assert signals[0] == signals[1]

    # Modulation is optional: devices need not report a carrier
    receiver.receive(InfraredSignal(timings=[9000, -4500]))
    assert signals[-1].signal == InfraredSignal(timings=[9000, -4500])

    unsub()
    receiver.receive(InfraredSignal(timings=[9000, -4500]))
    assert len(signals) == 3


async def test_capturing_signal_does_not_change_state(receiver: FakeReceiver) -> None:
    """Test that capturing a signal is not a state change."""
    await receiver.async_start_receiving()

    state_changes: list[EntityStateChangedEvent] = []
    receiver.subscribe_state(state_changes.append)
    assert len(state_changes) == 1

    receiver.receive(InfraredSignal(timings=[9000, -4500]))
    assert len(state_changes) == 1


async def test_receive_mode_ends_on_capture(zha_device: Device) -> None:
    """Test a device that leaves receive mode once it captures a signal."""
    receiver = create_infrared_entity(zha_device, FakeOneShotReceiver)

    signals: list[EntityInfraredSignalReceivedEvent] = []
    receiver.on_event(EntityInfraredSignalReceivedEvent.event, signals.append)

    await receiver.async_start_receiving()
    receiver.receive(InfraredSignal(timings=[9000, -4500]))

    assert len(signals) == 1
    assert receiver.receiving is False
    assert receiver.requests == ["start"]
