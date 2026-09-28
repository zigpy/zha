"""Test the ZHA valve platform."""

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
from zha.application.platforms.valve import BaseValve, ValveEntityState
from zha.application.platforms.valve.const import ValveDeviceClass, ValveEntityFeature
from zha.zigbee.device import Device


class FakeValve(BaseValve):
    """Valve entity that only opens and closes."""

    _unique_id_suffix = "fake"
    _attr_device_class = ValveDeviceClass.WATER

    _closed: bool | None = None

    @property
    def is_closed(self) -> bool | None:
        """Return if the valve is closed."""
        return self._closed

    async def async_open_valve(self) -> None:
        """Open the valve."""
        self._closed = False
        self.maybe_emit_state_changed_event()

    async def async_close_valve(self) -> None:
        """Close the valve."""
        self._closed = True
        self.maybe_emit_state_changed_event()


class FakePositionValve(FakeValve):
    """Valve entity that reports and sets its position."""

    _attr_reports_position = True
    _attr_supported_features = (
        ValveEntityFeature.OPEN
        | ValveEntityFeature.CLOSE
        | ValveEntityFeature.SET_POSITION
    )

    _position: int | None = None

    @property
    def current_valve_position(self) -> int | None:
        """Return the current position of the valve."""
        return self._position

    async def async_set_valve_position(self, position: int) -> None:
        """Move the valve to a specific position."""
        self._position = position
        self.maybe_emit_state_changed_event()


@pytest.fixture
async def zha_device(zha_gateway: Gateway) -> Device:
    """Return a joined device to attach valve entities to."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_OUTPUT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )
    return await join_zigpy_device(zha_gateway, zigpy_device)


def create_valve_entity(zha_device: Device, entity_class: type[FakeValve]) -> FakeValve:
    """Create a valve entity on the first endpoint of a device."""
    endpoint = zha_device.endpoints[1]

    return entity_class(
        endpoint=endpoint,
        device=zha_device,
        cluster=endpoint.zigpy_endpoint.in_clusters[general.OnOff.cluster_id],
    )


async def test_valve_state(zha_device: Device) -> None:
    """Test the state of a valve that only opens and closes."""
    entity = create_valve_entity(zha_device, FakeValve)
    state_changes: list[EntityStateChangedEvent] = []
    entity.subscribe_state(state_changes.append)

    assert entity.PLATFORM == Platform.VALVE
    assert entity.primary_weight == 10
    assert entity.device_class == ValveDeviceClass.WATER
    assert entity.supported_features == (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )

    state = entity.state
    assert isinstance(state, ValveEntityState)
    assert state.device_class == "water"
    assert state.reports_position is False
    assert state.current_position is None
    assert state.is_opening is None
    assert state.is_closing is None
    assert state.is_closed is None
    assert state.supported_features == (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )

    await entity.async_close_valve()
    assert entity.state.is_closed is True

    await entity.async_open_valve()
    assert entity.state.is_closed is False
    assert len(state_changes) == 3

    with pytest.raises(NotImplementedError):
        await entity.async_set_valve_position(50)

    with pytest.raises(NotImplementedError):
        await entity.async_stop_valve()


async def test_position_valve_state(zha_device: Device) -> None:
    """Test the state of a valve that reports its position."""
    entity = create_valve_entity(zha_device, FakePositionValve)

    state = entity.state
    assert state.reports_position is True
    assert state.current_position is None
    assert state.supported_features == (
        ValveEntityFeature.OPEN
        | ValveEntityFeature.CLOSE
        | ValveEntityFeature.SET_POSITION
    )

    await entity.async_set_valve_position(40)
    assert entity.state.current_position == 40
