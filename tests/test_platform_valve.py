"""Test the ZHA valve platform."""

from datetime import UTC, datetime, timedelta
from unittest.mock import call, patch

from freezegun import freeze_time
import pytest
from zigpy.profiles import zha
from zigpy.zcl.clusters import general
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
    send_attributes_report,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityStateChangedEvent
from zha.application.platforms.valve import BaseValve, OnOffValve, ValveState
from zha.application.platforms.valve.const import ValveDeviceClass, ValveEntityFeature
from zha.exceptions import ZHAException
from zha.zigbee.device import Device

NOW = datetime(2000, 1, 2, tzinfo=UTC)


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


def create_valve_entity[T: BaseValve](zha_device: Device, entity_class: type[T]) -> T:
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
    assert entity.device_class == ValveDeviceClass.WATER
    assert entity.supported_features == (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )

    state = entity.state
    assert isinstance(state, ValveState)
    assert state.device_class == "water"
    assert state.reports_position is False
    assert state.current_position is None
    assert state.is_opening is None
    assert state.is_closing is None
    assert state.is_closed is None
    assert state.auto_close_at is None
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

    with pytest.raises(NotImplementedError):
        await entity.async_open_valve_for(timedelta(minutes=1))


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


@pytest.fixture
def on_off_valve(zha_device: Device) -> OnOffValve:
    """Return an On/Off valve entity for a joined device."""
    entity = create_valve_entity(zha_device, OnOffValve)
    entity.on_add()
    return entity


async def test_on_off_valve_open_close(
    zha_gateway: Gateway, on_off_valve: OnOffValve
) -> None:
    """Test opening and closing an On/Off valve."""
    cluster = on_off_valve.cluster
    assert on_off_valve.supported_features == (
        ValveEntityFeature.OPEN
        | ValveEntityFeature.CLOSE
        | ValveEntityFeature.OPEN_TIMED
    )
    assert on_off_valve.state.is_closed is None

    # Changes on the device
    await send_attributes_report(zha_gateway, cluster, {0x0000: 1})
    assert on_off_valve.state.is_closed is False

    await send_attributes_report(zha_gateway, cluster, {0x0000: 0})
    assert on_off_valve.state.is_closed is True

    # Commands from the client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x01, zcl_f.Status.SUCCESS],
    ):
        await on_off_valve.async_open_valve()
        assert on_off_valve.state.is_closed is False
        assert cluster.request.mock_calls == [
            call(
                False,
                general.OnOff.ServerCommandDefs.on.id,
                general.OnOff.ServerCommandDefs.on.schema,
                expect_reply=True,
                manufacturer=None,
            )
        ]

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await on_off_valve.async_close_valve()
        assert on_off_valve.state.is_closed is True
        assert cluster.request.mock_calls == [
            call(
                False,
                general.OnOff.ServerCommandDefs.off.id,
                general.OnOff.ServerCommandDefs.off.schema,
                expect_reply=True,
                manufacturer=None,
            )
        ]

    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x01, zcl_f.Status.FAILURE],
        ),
        pytest.raises(ZHAException, match="Failed to open"),
    ):
        await on_off_valve.async_open_valve()

    assert on_off_valve.state.is_closed is True


async def test_on_off_valve_open_for(
    zha_gateway: Gateway, on_off_valve: OnOffValve
) -> None:
    """Test a timed open of an On/Off valve."""
    cluster = on_off_valve.cluster

    with (
        freeze_time(NOW),
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x42, zcl_f.Status.SUCCESS],
        ),
    ):
        await on_off_valve.async_open_valve_for(timedelta(minutes=5))
        assert cluster.request.mock_calls == [
            call(
                False,
                general.OnOff.ServerCommandDefs.on_with_timed_off.id,
                general.OnOff.ServerCommandDefs.on_with_timed_off.schema,
                on_off_control=0,
                on_time=3000,
                off_wait_time=0,
                expect_reply=True,
                manufacturer=None,
            )
        ]

    assert on_off_valve.state.is_closed is False
    assert on_off_valve.state.auto_close_at == NOW + timedelta(minutes=5)

    # A shorter timed open does not shorten the running timer
    with (
        freeze_time(NOW + timedelta(minutes=1)),
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x42, zcl_f.Status.SUCCESS],
        ),
    ):
        await on_off_valve.async_open_valve_for(timedelta(minutes=1))

    assert on_off_valve.state.auto_close_at == NOW + timedelta(minutes=5)

    # A plain open does not cancel the timer
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x01, zcl_f.Status.SUCCESS],
    ):
        await on_off_valve.async_open_valve()

    assert on_off_valve.state.auto_close_at == NOW + timedelta(minutes=5)

    # The remaining on time from the device replaces the local estimate
    with freeze_time(NOW + timedelta(minutes=2)):
        await send_attributes_report(zha_gateway, cluster, {0x4001: 600})

    assert on_off_valve.state.auto_close_at == NOW + timedelta(minutes=3)

    # The device closes the valve by itself
    await send_attributes_report(zha_gateway, cluster, {0x0000: 0})
    assert on_off_valve.state.is_closed is True
    assert on_off_valve.state.auto_close_at is None


@pytest.mark.parametrize("on_time", [0x0000, 0xFFFF])
async def test_on_off_valve_no_timer(
    zha_gateway: Gateway, on_off_valve: OnOffValve, on_time: int
) -> None:
    """Test that an on time of 0 or 0xFFFF clears the auto close time."""
    cluster = on_off_valve.cluster

    await send_attributes_report(zha_gateway, cluster, {0x0000: 1, 0x4001: 600})
    assert on_off_valve.state.auto_close_at is not None

    await send_attributes_report(zha_gateway, cluster, {0x4001: on_time})
    assert on_off_valve.state.is_closed is False
    assert on_off_valve.state.auto_close_at is None


async def test_on_off_valve_close_clears_timer(on_off_valve: OnOffValve) -> None:
    """Test that closing the valve clears the auto close time."""
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x42, zcl_f.Status.SUCCESS],
    ):
        await on_off_valve.async_open_valve_for(timedelta(minutes=5))

    assert on_off_valve.state.auto_close_at is not None

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await on_off_valve.async_close_valve()

    assert on_off_valve.state.is_closed is True
    assert on_off_valve.state.auto_close_at is None
