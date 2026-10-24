"""Tests for ZHA Green Power devices."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from zigpy.device import (
    GreenPowerCommandReceived,
    GreenPowerDevice as ZigpyGreenPowerDevice,
)
from zigpy.profiles import zha
from zigpy.types import EUI64
from zigpy.zcl.clusters.general import Basic, OnOff
from zigpy.zgp.types import ApplicationID, DeviceID, GPDCommandID, SrcID

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
)
from zha.application import Platform
from zha.application.const import (
    UNKNOWN_MANUFACTURER,
    UNKNOWN_MODEL,
    ZHA_DEVICE_CONFIGURED_EVENT,
    ZHA_DEVICE_ENTITY_ADDED_EVENT,
    ZHA_DEVICE_ENTITY_REMOVED_EVENT,
    ZHA_GW_MSG_RAW_INIT,
)
from zha.application.gateway import Gateway
from zha.application.helpers import async_is_bindable_target, get_matched_clusters
from zha.application.platforms import PlatformEntity
from zha.application.platforms.event import (
    BaseEvent,
    EntityEventTriggeredEvent,
    TriggeredEvent,
)
from zha.exceptions import ZHAException
from zha.quirks import (
    DEVICE_REGISTRY,
    QUIRK_REGISTRY_ENTRY_ATTR,
    GreenPowerDeviceMatch,
    GreenPowerQuirkRegistryEntry,
)
from zha.zigbee.device import (
    DeviceEntityAddedEvent,
    DeviceEntityRemovedEvent,
    GreenPowerDevice,
)


def make_zigpy_gpd(zha_gateway: Gateway) -> ZigpyGreenPowerDevice:
    """Create a commissioned zigpy GPD on the test application."""
    zigpy_gpd = ZigpyGreenPowerDevice(
        zha_gateway.application_controller,
        application_id=ApplicationID.SrcID,
        src_id=SrcID(0x12345678),
    )
    zigpy_gpd.device_id = DeviceID.OnOffSwitch
    zigpy_gpd.commands = [
        GPDCommandID.Toggle,
        GPDCommandID.Press1of1,
        GPDCommandID.Release1of1,
    ]

    zha_gateway.application_controller.devices[zigpy_gpd.ieee] = zigpy_gpd
    return zigpy_gpd


async def test_green_power_device_creation(zha_gateway: Gateway) -> None:
    """Test that a zigpy GPD is wrapped in the ZHA Green Power device class."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)

    assert isinstance(zha_device, GreenPowerDevice)
    assert zha_device.device is zigpy_gpd
    assert zha_gateway.devices[zigpy_gpd.ieee] is zha_device


async def test_green_power_device_properties(zha_gateway: Gateway) -> None:
    """Test the Green Power device property surface."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)

    assert zha_device.available is True
    assert zha_device.is_mains_powered is False
    assert zha_device.is_active_coordinator is False
    assert zha_device.device_type == "GreenPower"
    assert zha_device.manufacturer == UNKNOWN_MANUFACTURER
    assert zha_device.model == UNKNOWN_MODEL
    assert zha_device.manufacturer_code is None
    assert zha_device.skip_configuration is False
    assert zha_device.is_groupable is False
    assert zha_device.async_get_std_clusters() == {}
    assert zha_device.signature["device_id"] == DeviceID.OnOffSwitch
    assert zha_device.signature["src_id"] == 0x12345678
    assert zha_device.signature["commands"] == [
        GPDCommandID.Toggle,
        GPDCommandID.Press1of1,
        GPDCommandID.Release1of1,
    ]

    # A GPD has no heartbeat: the availability check never flips it
    await zha_device._check_available()
    assert zha_device.available is True


async def test_green_power_device_identifiers(zha_gateway: Gateway) -> None:
    """Test manufacturer and model resolution from commissioning identifiers."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zigpy_gpd.gpd_manufacturer_id = 0x1234
    zigpy_gpd.gpd_model_id = 0x0007

    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)

    assert zha_device.manufacturer == "0x1234"
    assert zha_device.model == "0x0007"
    assert zha_device.manufacturer_code == 0x1234
    assert zha_device.name == "0x1234 0x0007"


async def test_green_power_device_info(zha_gateway: Gateway) -> None:
    """Test device info, extended device info, and diagnostics."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)

    device_info = zha_device.device_info
    assert device_info.ieee == zigpy_gpd.ieee
    assert device_info.device_type == "GreenPower"
    assert device_info.signature["device_id"] == 0x02

    extended_info = zha_device.extended_device_info
    assert extended_info.active_coordinator is False
    assert extended_info.entities == {}
    assert extended_info.neighbors == []
    assert extended_info.routes == []
    assert extended_info.endpoint_names == []

    zigpy_gpd.last_seen = datetime(2026, 1, 1, tzinfo=UTC)
    diagnostics = zha_device.get_diagnostics_json()
    assert diagnostics["ieee"] == str(zigpy_gpd.ieee)
    assert diagnostics["last_seen"] == "2026-01-01T00:00:00+00:00"
    assert diagnostics["active_coordinator"] is False
    assert diagnostics["device_type"] == "GreenPower"
    assert diagnostics["signature"]["device_id"] == 0x02


async def test_green_power_device_quirk_passthrough(zha_gateway: Gateway) -> None:
    """Test that the quirk registry passes GP devices through untouched."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    assert DEVICE_REGISTRY.resolve(zigpy_gpd) is zigpy_gpd


async def test_green_power_device_initialize(zha_gateway: Gateway) -> None:
    """Test that a Green Power device initializes without entities."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)

    await zha_device.async_initialize(from_cache=True)
    assert zha_device.platform_entities == {}


async def test_green_power_device_match(zha_gateway: Gateway) -> None:
    """Test the Green Power quirk matching criteria."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zigpy_gpd.gpd_manufacturer_id = 0x1234

    assert GreenPowerDeviceMatch().matches(zigpy_gpd)
    assert GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch).matches(zigpy_gpd)
    assert not GreenPowerDeviceMatch(device_id=DeviceID.GenericSwitch).matches(
        zigpy_gpd
    )
    assert GreenPowerDeviceMatch(manufacturer_id=0x1234).matches(zigpy_gpd)
    assert not GreenPowerDeviceMatch(manufacturer_id=0x5678).matches(zigpy_gpd)
    assert not GreenPowerDeviceMatch(model_id=0x0001).matches(zigpy_gpd)

    assert GreenPowerDeviceMatch(src_id_ranges=((0x12000000, 0x12FFFFFF),)).matches(
        zigpy_gpd
    )
    assert not GreenPowerDeviceMatch(src_id_ranges=((0x00, 0xFF),)).matches(zigpy_gpd)

    # The synthetic IEEE of a SrcID-addressed GPD carries no vendor prefix
    assert not GreenPowerDeviceMatch(ieee_prefixes=(bytes([0x04, 0xCD]),)).matches(
        zigpy_gpd
    )

    assert GreenPowerDeviceMatch(
        filters=(lambda device: GPDCommandID.Toggle in device.commands,)
    ).matches(zigpy_gpd)
    assert not GreenPowerDeviceMatch(
        filters=(lambda device: GPDCommandID.Off in device.commands,)
    ).matches(zigpy_gpd)


async def test_green_power_device_match_ieee(zha_gateway: Gateway) -> None:
    """Test matching an IEEE-addressed GPD by address prefix."""
    zigpy_gpd = ZigpyGreenPowerDevice(
        zha_gateway.application_controller,
        application_id=ApplicationID.IEEE,
        ieee=EUI64.convert("04:cd:15:00:11:22:33:44"),
    )

    assert GreenPowerDeviceMatch(ieee_prefixes=(bytes([0x04, 0xCD, 0x15]),)).matches(
        zigpy_gpd
    )
    assert not GreenPowerDeviceMatch(
        ieee_prefixes=(bytes([0x04, 0xCD, 0x16]),)
    ).matches(zigpy_gpd)

    # Either identity criterion is sufficient when both are declared
    assert GreenPowerDeviceMatch(
        src_id_ranges=((0x00, 0xFF),),
        ieee_prefixes=(bytes([0x04, 0xCD, 0x15]),),
    ).matches(zigpy_gpd)


async def test_green_power_quirk_resolution(zha_gateway: Gateway) -> None:
    """Test that a registered Green Power quirk resolves and builds the ZHA device."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)

    class QuirkedGreenPowerDevice(GreenPowerDevice):
        """Quirk-supplied device class."""

    generic_entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch),
    )
    entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(
            device_id=DeviceID.OnOffSwitch,
            src_id_ranges=((0x12000000, 0x12FFFFFF),),
        ),
        zha_device_factory=QuirkedGreenPowerDevice,
    )

    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(entry)
        DEVICE_REGISTRY.register(generic_entry)

        # The more specific entry wins regardless of registration order
        assert DEVICE_REGISTRY.match_green_power_entry(zigpy_gpd) is entry

        resolved = DEVICE_REGISTRY.resolve(zigpy_gpd)
        assert resolved is zigpy_gpd
        assert getattr(resolved, QUIRK_REGISTRY_ENTRY_ATTR) is entry

        zha_device = zha_gateway.get_or_create_device(resolved)
        assert isinstance(zha_device, QuirkedGreenPowerDevice)
        assert zha_device.quirk_applied


async def test_green_power_quirk_specificity(zha_gateway: Gateway) -> None:
    """Test that Green Power quirks are ranked by specificity, then recency."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zigpy_gpd.gpd_manufacturer_id = 0x1234

    device_id_entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch),
    )
    two_field_entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(
            device_id=DeviceID.OnOffSwitch, manufacturer_id=0x1234
        ),
    )
    src_id_entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(src_id_ranges=((0x12000000, 0x12FFFFFF),)),
    )
    later_device_id_entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(
            device_id=DeviceID.OnOffSwitch, filters=(lambda device: True,)
        ),
    )

    # Equally specific entries fall back to the most recently registered one
    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(device_id_entry)
        DEVICE_REGISTRY.register(later_device_id_entry)
        assert DEVICE_REGISTRY.match_green_power_entry(zigpy_gpd) is (
            later_device_id_entry
        )

    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(two_field_entry)
        DEVICE_REGISTRY.register(device_id_entry)
        assert DEVICE_REGISTRY.match_green_power_entry(zigpy_gpd) is two_field_entry

    # An identity criterion outranks any number of signature fields
    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(src_id_entry)
        DEVICE_REGISTRY.register(two_field_entry)
        assert DEVICE_REGISTRY.match_green_power_entry(zigpy_gpd) is src_id_entry


async def test_green_power_device_not_zigbee(zha_gateway: Gateway) -> None:
    """Test that Zigbee-only helpers reject or skip a Green Power device."""
    zha_device = zha_gateway.get_or_create_device(make_zigpy_gpd(zha_gateway))

    remote_zha_device = await join_zigpy_device(
        zha_gateway,
        create_mock_zigpy_device(
            zha_gateway,
            {
                1: {
                    SIG_EP_INPUT: [Basic.cluster_id],
                    SIG_EP_OUTPUT: [OnOff.cluster_id],
                    SIG_EP_TYPE: zha.DeviceType.REMOTE_CONTROL,
                    SIG_EP_PROFILE: zha.PROFILE_ID,
                }
            },
        ),
    )

    assert not async_is_bindable_target(remote_zha_device, zha_device)
    assert not async_is_bindable_target(zha_device, remote_zha_device)
    assert await get_matched_clusters(remote_zha_device, zha_device) == []
    assert await get_matched_clusters(zha_device, remote_zha_device) == []

    with pytest.raises(ZHAException, match="is not a Zigbee device"):
        zha_gateway.get_zigbee_device(zha_device.ieee)


async def test_green_power_device_raw_initialized(zha_gateway: Gateway) -> None:
    """Test the raw init event for a GPD, which has no model or manufacturer."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)

    events = []
    zha_gateway.on_event(ZHA_GW_MSG_RAW_INIT, events.append)
    zha_gateway.raw_device_initialized(zigpy_gpd)

    assert len(events) == 1
    assert events[0].device_info.ieee == zigpy_gpd.ieee
    assert events[0].device_info.model == UNKNOWN_MODEL
    assert events[0].device_info.manufacturer == UNKNOWN_MANUFACTURER


async def test_green_power_device_recommissioned(zha_gateway: Gateway) -> None:
    """Test that a re-commissioned GPD rebuilds the existing ZHA device."""
    zha_device = zha_gateway.get_or_create_device(make_zigpy_gpd(zha_gateway))

    events = []
    zha_device.on_event(ZHA_DEVICE_CONFIGURED_EVENT, events.append)

    new_zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_gateway.application_controller.listener_event(
        "device_reinterviewed", new_zigpy_gpd
    )
    await zha_gateway.async_block_till_done()

    assert zha_gateway.devices[new_zigpy_gpd.ieee] is zha_device
    assert zha_device.device is new_zigpy_gpd
    assert len(events) == 1


# Mimics the zhaquirks `GreenPowerQuirkBuilder` until a released quirk replaces it
class ToggleEvent(BaseEvent):
    """Event entity firing when the GPD sends a toggle command."""

    _attr_event_types = ["toggle"]

    def on_add(self) -> None:
        """Subscribe to the commands sent by the device."""
        super().on_add()
        self._on_remove_callbacks.append(
            self.device.device.on_event(
                GreenPowerCommandReceived.event_type, self._handle_gp_command
            )
        )

    def _handle_gp_command(self, event: GreenPowerCommandReceived) -> None:
        if event.command_id == GPDCommandID.Toggle:
            self._trigger_event("toggle")


class QuirkGreenPowerDevice(GreenPowerDevice):
    """Quirk device exposing a single event entity."""

    def discover_entities(self) -> Iterator[PlatformEntity]:
        """Yield the quirk's entities."""
        yield from super().discover_entities()
        yield ToggleEvent(
            self,
            unique_id=str(self.ieee),
            from_quirk=True,
            unique_id_suffix="toggle",
            fallback_name="Toggle",
        )


def send_toggle(zigpy_gpd: ZigpyGreenPowerDevice) -> None:
    """Emit a received toggle command from the zigpy GPD."""
    zigpy_gpd.emit(
        GreenPowerCommandReceived.event_type,
        GreenPowerCommandReceived(
            device_ieee=str(zigpy_gpd.ieee),
            endpoint_id=None,
            command_id=GPDCommandID.Toggle,
            command=None,
        ),
    )


async def test_green_power_quirk_entity_lifecycle(zha_gateway: Gateway) -> None:
    """Test a quirk entity on a GPD through initialization and recommissioning."""
    entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch),
        zha_device_factory=QuirkGreenPowerDevice,
    )

    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(entry)

        zigpy_gpd = DEVICE_REGISTRY.resolve(make_zigpy_gpd(zha_gateway))
        zha_device = zha_gateway.get_or_create_device(zigpy_gpd)
        assert isinstance(zha_device, QuirkGreenPowerDevice)

        await zha_device.async_initialize(from_cache=True)

        unique_id = f"{zigpy_gpd.ieee}-toggle"
        entity = zha_device.get_platform_entity(Platform.EVENT, unique_id)
        assert list(zha_device.platform_entities) == [(Platform.EVENT, unique_id)]
        assert entity.state.available is True
        assert entity.state.event_types == ["toggle"]
        assert zha_device.extended_device_info.entities == {unique_id: entity.state}

        triggered = []
        entity.on_event(EntityEventTriggeredEvent.event, triggered.append)
        send_toggle(zigpy_gpd)
        assert [event.triggered for event in triggered] == [
            TriggeredEvent(event_type="toggle", event_attributes={})
        ]

        entity_events = []
        zha_device.on_event(ZHA_DEVICE_ENTITY_REMOVED_EVENT, entity_events.append)
        zha_device.on_event(ZHA_DEVICE_ENTITY_ADDED_EVENT, entity_events.append)

        # Recommissioning replaces the zigpy device and recreates the entity
        new_zigpy_gpd = DEVICE_REGISTRY.resolve(make_zigpy_gpd(zha_gateway))
        zha_gateway.application_controller.listener_event(
            "device_reinterviewed", new_zigpy_gpd
        )
        await zha_gateway.async_block_till_done()

        assert zha_gateway.devices[new_zigpy_gpd.ieee] is zha_device
        assert zha_device.device is new_zigpy_gpd
        assert entity_events == [
            DeviceEntityRemovedEvent(platform=Platform.EVENT, unique_id=unique_id),
            DeviceEntityAddedEvent(platform=Platform.EVENT, unique_id=unique_id),
        ]

        new_entity = zha_device.get_platform_entity(Platform.EVENT, unique_id)
        assert new_entity is not entity
        assert list(zha_device.platform_entities) == [(Platform.EVENT, unique_id)]

        # The old entity is unsubscribed from the old zigpy device
        new_triggered = []
        new_entity.on_event(EntityEventTriggeredEvent.event, new_triggered.append)
        send_toggle(zigpy_gpd)
        assert len(triggered) == 1
        assert new_triggered == []

        send_toggle(new_zigpy_gpd)
        assert len(triggered) == 1
        assert [event.triggered for event in new_triggered] == [
            TriggeredEvent(event_type="toggle", event_attributes={})
        ]
