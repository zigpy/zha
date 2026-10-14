"""Test child devices."""

from unittest.mock import patch

import pytest
from zigpy.typing import UNDEFINED
from zigpy.zcl.clusters.general import Basic, OnOff
from zigpy.zcl.clusters.smartenergy import Metering

from tests.common import join_zigpy_device, zigpy_device_from_json
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.const import STATE_CHANGED
from zha.zigbee.child_device import (
    DEVICE_LEVEL_CLUSTERS,
    ChildDevice,
    ChildDeviceMatch,
    is_child_device_allowlisted,
)
from zha.zigbee.device import Device


async def _join_device(zha_gateway: Gateway, path: str) -> Device:
    """Join a device from a diagnostics file."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller, path
    )
    return await join_zigpy_device(zha_gateway, zigpy_device)


def _entities(
    device: Device, platform: Platform, cluster_id: int | None = None
) -> list[PlatformEntity]:
    """Return the entities of a platform (and cluster), sorted by endpoint."""
    return sorted(
        (
            entity
            for entity in device.platform_entities.values()
            if platform == entity.PLATFORM
            and (cluster_id is None or entity.cluster.cluster_id == cluster_id)
        ),
        key=lambda entity: entity.endpoint.id,
    )


def _child_device_ids(device: Device) -> dict[str, str | None]:
    """Return the child device id of each entity, by unique id."""
    return {
        entity.unique_id: entity.state.child_device_id
        for entity in device.platform_entities.values()
    }


def test_child_device_requires_id() -> None:
    """Test a child device needs an id."""
    with pytest.raises(ValueError, match="non-empty id"):
        ChildDevice(id="", fallback_name="Nothing")


def test_child_device_match() -> None:
    """Test matching devices for the automatic split."""
    any_manufacturer = ChildDeviceMatch(models=frozenset({"TS0002"}))
    assert any_manufacturer.matches("_TZ3000_abcdefgh", "TS0002")
    assert not any_manufacturer.matches("_TZ3000_abcdefgh", "TS0001")

    one_manufacturer = ChildDeviceMatch(
        manufacturers=frozenset({"LUMI"}), models=frozenset({"lumi.relay.c2acn01"})
    )
    assert one_manufacturer.matches("LUMI", "lumi.relay.c2acn01")
    assert not one_manufacturer.matches("Other", "lumi.relay.c2acn01")

    assert is_child_device_allowlisted("_TZ3000_abcdefgh", "TS0003")
    assert not is_child_device_allowlisted("_TZ3000_abcdefgh", "TS0601")


async def test_allowlisted_device_split(zha_gateway: Gateway) -> None:
    """Test the outputs of an allowlisted device are split into child devices."""
    device = await _join_device(
        zha_gateway, "tests/data/devices/tz3000-mw1pqqqt-ts0003-0x0000004a.json"
    )

    assert list(device.child_devices) == ["1", "2", "3"]
    assert device.child_devices["2"] == ChildDevice(
        id="2",
        endpoint_ids=frozenset({2}),
        translation_key="channel",
        translation_placeholders={"index": "2"},
        fallback_name="Channel 2",
    )
    assert device.extended_device_info.child_devices == list(
        device.child_devices.values()
    )

    # Each output gets its own child device and is its primary entity
    lights = _entities(device, Platform.LIGHT)
    assert [light.state.child_device_id for light in lights] == ["1", "2", "3"]
    assert [light.child_device for light in lights] == list(
        device.child_devices.values()
    )
    assert all(light.primary for light in lights)

    # The meter of the whole device and the device-wide settings, which only exist on
    # the first endpoint, and device-level entities stay on the main device
    for entity in device.platform_entities.values():
        if entity.PLATFORM != Platform.LIGHT:
            assert entity.child_device is None, entity
            assert not entity.primary, entity

    assert _entities(device, Platform.SENSOR, Metering.cluster_id)
    assert {
        entity.translation_key for entity in _entities(device, Platform.SELECT)
    } == {
        "backlight_mode",
        "power_on_state",
    }

    # Child devices are part of the diagnostics
    diagnostics = device.get_diagnostics_json()
    assert diagnostics["child_devices"][0] == {
        "id": "1",
        "endpoint_ids": [1],
        "translation_key": "channel",
        "translation_placeholders": {"index": "1"},
        "fallback_name": "Channel 1",
    }


async def test_allowlisted_device_per_output_meters(zha_gateway: Gateway) -> None:
    """Test entities repeated on each output move to its child device."""
    device = await _join_device(
        zha_gateway, "tests/data/devices/tz3000-uwkja6z1-ts011f.json"
    )

    assert list(device.child_devices) == ["1", "2"]

    meters = _entities(device, Platform.SENSOR, Metering.cluster_id)
    assert [meter.state.child_device_id for meter in meters] == ["1", "2"]

    for entity in _entities(device, Platform.SENSOR, Basic.cluster_id):
        assert entity.child_device is None

    # The main device is left without an output entity, so it has no primary entity
    assert device.primary_entity is None


async def test_not_allowlisted_device(zha_gateway: Gateway) -> None:
    """Test a device that is not allowlisted is not split."""
    with patch("zha.zigbee.device.is_child_device_allowlisted", return_value=False):
        device = await _join_device(
            zha_gateway, "tests/data/devices/tz3000-mw1pqqqt-ts0003-0x0000004a.json"
        )

    assert device.child_devices == {}
    assert set(_child_device_ids(device).values()) == {None}
    assert device.get_diagnostics_json()["child_devices"] == []

    # The identical outputs tie, so there is no primary entity
    assert not any(entity.primary for entity in device.platform_entities.values())


async def test_single_output_not_split(zha_gateway: Gateway) -> None:
    """Test an allowlisted model with a single output is not split."""
    device = await _join_device(
        zha_gateway, "tests/data/devices/tz3000-2putqrmw-ts011f.json"
    )
    assert is_child_device_allowlisted(device.manufacturer, device.model)

    assert device.child_devices == {}
    assert set(_child_device_ids(device).values()) == {None}


async def test_quirk_child_devices(zha_gateway: Gateway) -> None:
    """Test child devices defined by a quirk."""
    child_devices = (
        ChildDevice(
            id="fan",
            endpoint_ids=frozenset({2}),
            translation_key="fan",
            fallback_name="Fan",
        ),
        ChildDevice(id="unused", endpoint_ids=frozenset({3}), fallback_name="Unused"),
    )

    with patch.object(Device, "_quirk_child_devices", return_value=child_devices):
        device = await _join_device(
            zha_gateway, "tests/data/devices/inovelli-vzm36.json"
        )

    # A child device without entities is left out
    assert list(device.child_devices) == ["fan"]

    for entity in device.platform_entities.values():
        if (
            entity.endpoint.id == 2
            and entity.cluster.cluster_id not in DEVICE_LEVEL_CLUSTERS
        ):
            assert entity.state.child_device_id == "fan", entity
        else:
            # Entities of device-level clusters stay on the main device, wherever
            # they are
            assert entity.child_device is None, entity

    (fan,) = _entities(device, Platform.FAN)
    assert fan.child_device is device.child_devices["fan"]

    # The main device keeps electing its primary entity among its output entities
    assert device.primary_entity is _entities(device, Platform.LIGHT)[0]


async def test_quirk_no_child_devices(zha_gateway: Gateway) -> None:
    """Test a quirk can disable the automatic split of an allowlisted device."""
    with patch.object(Device, "_quirk_child_devices", return_value=()):
        device = await _join_device(
            zha_gateway, "tests/data/devices/tz3000-mw1pqqqt-ts0003-0x0000004a.json"
        )

    assert device.child_devices == {}
    assert set(_child_device_ids(device).values()) == {None}


async def test_quirk_overlapping_child_devices(
    zha_gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    """Test child devices sharing an endpoint are rejected."""
    child_devices = (
        ChildDevice(id="a", endpoint_ids=frozenset({1, 2}), fallback_name="A"),
        ChildDevice(id="b", endpoint_ids=frozenset({2}), fallback_name="B"),
    )

    with (
        patch.object(Device, "_quirk_child_devices", return_value=child_devices),
        pytest.raises(ValueError, match="Endpoint 2 is assigned to both"),
    ):
        await _join_device(
            zha_gateway, "tests/data/devices/tz3000-mw1pqqqt-ts0003-0x0000004a.json"
        )


async def test_explicit_child_device_assignment(
    zha_gateway: Gateway, caplog: pytest.LogCaptureFixture
) -> None:
    """Test entities explicitly assigned to a child device or the main device."""
    device = await _join_device(
        zha_gateway, "tests/data/devices/tz3000-mw1pqqqt-ts0003-0x0000004a.json"
    )

    lights = _entities(device, Platform.LIGHT)
    (power_on_state,) = [
        entity
        for entity in _entities(device, Platform.SELECT)
        if entity.translation_key == "power_on_state"
    ]
    (meter, *_) = _entities(device, Platform.SENSOR, Metering.cluster_id)
    assert power_on_state.explicit_child_device_id is UNDEFINED

    # Keep the first output on the main device, move the device-wide setting to the
    # second child device, and refer to an unknown child device
    lights[0]._attr_child_device_id = None
    power_on_state._attr_child_device_id = "2"
    meter._attr_child_device_id = "unknown"

    changed: dict[str, dict] = {}
    for entity in (lights[0], power_on_state):
        entity.on_event(
            STATE_CHANGED,
            lambda event: changed.setdefault(event.unique_id, event.state_diff),
        )

    await device.recompute_entities()

    assert lights[0].child_device is None
    assert power_on_state.child_device is device.child_devices["2"]
    assert meter.child_device is None
    assert "refers to unknown child device 'unknown'" in caplog.text

    # The now empty child device is left out, and the first output is now the primary
    # entity of the main device
    assert list(device.child_devices) == ["2", "3"]
    assert device.primary_entity is lights[0]
    assert lights[0].primary

    # The changes are emitted to consumers
    assert changed[power_on_state.unique_id]["child_device_id"] == "2"
    assert changed[lights[0].unique_id] == {"child_device_id": None}


async def test_child_device_primary_reelection(zha_gateway: Gateway) -> None:
    """Test removing the primary entity of a child device."""
    device = await _join_device(
        zha_gateway, "tests/data/devices/tz3000-uwkja6z1-ts011f.json"
    )

    switch = _entities(device, Platform.SWITCH, OnOff.cluster_id)[1]
    assert switch.primary
    assert switch.child_device is device.child_devices["2"]

    await device._remove_entity(switch, remove=True)
    await device._add_pending_entities()

    assert (Platform.SWITCH, switch.unique_id) not in device.platform_entities
    assert not device.is_primary_entity(switch)

    # The other output alone no longer collides with anything, so it is not split
    assert device.child_devices == {}
    (remaining_switch,) = _entities(device, Platform.SWITCH, OnOff.cluster_id)
    assert remaining_switch.child_device is None
    assert remaining_switch.primary
