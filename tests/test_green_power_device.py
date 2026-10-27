"""Tests for ZHA Green Power devices."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import zigpy.device
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
    ZhaJsonEncoder,
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
    ZHA_GW_MSG_DEVICE_FULL_INIT,
    ZHA_GW_MSG_DEVICE_JOINED,
    ZHA_GW_MSG_DEVICE_LEFT,
    ZHA_GW_MSG_DEVICE_REMOVED,
    ZHA_GW_MSG_RAW_INIT,
)
from zha.application.gateway import (
    DeviceFullInitEvent,
    DeviceJoinedEvent,
    DeviceLeftEvent,
    DevicePairingStatus,
    DeviceRemovedEvent,
    Gateway,
)
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
    DeviceMatch,
    DeviceRegistry,
    GreenPowerDeviceMatch,
    GreenPowerQuirkRegistryEntry,
    ModelInfo,
    QuirkRegistryEntry,
    QuirkSource,
)
from zha.zigbee.device import (
    BaseDevice,
    Device,
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

    # Specificity counts field presence, not value
    assert (
        GreenPowerDeviceMatch(device_id=0).specificity
        > GreenPowerDeviceMatch().specificity
    )


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
    assert not async_is_bindable_target(zha_device, zha_gateway.coordinator_zha_device)
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


async def test_green_power_device_diagnostics_entities(zha_gateway: Gateway) -> None:
    """Test that diagnostics serialize entities and skip virtual ones."""
    entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch),
        zha_device_factory=QuirkGreenPowerDevice,
    )

    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(entry)

        zigpy_gpd = DEVICE_REGISTRY.resolve(make_zigpy_gpd(zha_gateway))
        zigpy_gpd.last_seen = datetime(2026, 1, 1, tzinfo=UTC)
        zha_device = zha_gateway.get_or_create_device(zigpy_gpd)
        await zha_device.async_initialize(from_cache=True)

        unique_id = f"{zigpy_gpd.ieee}-toggle"
        event_entity = zha_device.get_platform_entity(Platform.EVENT, unique_id)

        # Virtual entities have no state surface and are left out of diagnostics
        zha_device.platform_entities[(Platform.VIRTUAL, "virtual")] = MagicMock(
            PLATFORM=Platform.VIRTUAL, unique_id="virtual", on_remove=AsyncMock()
        )

        diagnostics = json.loads(
            json.dumps(zha_device.get_diagnostics_json(), cls=ZhaJsonEncoder)
        )

    assert list(diagnostics["zha_lib_entities"]) == [Platform.EVENT]
    (state,) = diagnostics["zha_lib_entities"][Platform.EVENT]
    assert state["unique_id"] == event_entity.state.unique_id
    assert state["event_types"] == ["toggle"]
    assert state["device_ieee"] == str(zigpy_gpd.ieee)
    assert isinstance(state["migrate_unique_ids"], list)
    assert state["extra_state_attribute_names"] == sorted(
        state["extra_state_attribute_names"]
    )


async def test_green_power_base_device_defaults(zha_gateway: Gateway) -> None:
    """Test the `BaseDevice` defaults a GPD inherits."""
    zha_device = zha_gateway.get_or_create_device(make_zigpy_gpd(zha_gateway))

    assert zha_device.quirk_metadata is None
    assert zha_device.is_coordinator is False
    assert zha_device.device_alerts == []
    assert zha_device.device_automation_triggers == {
        ("device_offline", "device_offline"): {"device_event_type": "device_offline"}
    }
    assert zha_device.device_automation_commands == {}
    assert zha_device._quirk_exposes_features() == set()
    assert zha_device._quirk_skip_configuration() is False
    assert zha_device._quirk_device_automation_triggers() == {}
    assert zha_device.power_source == "Battery or Unknown"
    assert zha_device.gateway is zha_gateway


async def test_base_device_abstract_resolvers(zha_gateway: Gateway) -> None:
    """Test the `BaseDevice` hooks that subclasses must implement."""
    zha_device = zha_gateway.get_or_create_device(make_zigpy_gpd(zha_gateway))

    for method in (
        BaseDevice._resolve_manufacturer,
        BaseDevice._resolve_model,
    ):
        with pytest.raises(NotImplementedError):
            method(zha_device)

    for prop in (
        BaseDevice.manufacturer_code,
        BaseDevice.is_mains_powered,
        BaseDevice.device_type,
    ):
        with pytest.raises(NotImplementedError):
            prop.fget(zha_device)


async def test_green_power_device_join(zha_gateway: Gateway) -> None:
    """Test the join sequence of a GPD through the gateway."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)

    joined: list[DeviceJoinedEvent] = []
    raw: list = []
    full: list[DeviceFullInitEvent] = []
    zha_gateway.on_event(ZHA_GW_MSG_DEVICE_JOINED, joined.append)
    zha_gateway.on_event(ZHA_GW_MSG_RAW_INIT, raw.append)
    zha_gateway.on_event(ZHA_GW_MSG_DEVICE_FULL_INIT, full.append)

    zha_gateway.device_joined(zigpy_gpd)
    assert len(joined) == 1
    assert joined[0].device_info.ieee == zigpy_gpd.ieee
    assert joined[0].device_info.nwk == zigpy_gpd.nwk
    assert joined[0].device_info.pairing_status is DevicePairingStatus.PAIRED

    zha_gateway.raw_device_initialized(zigpy_gpd)
    assert len(raw) == 1

    zha_gateway.device_initialized(zigpy_gpd)
    await zha_gateway.async_block_till_done()

    zha_device = zha_gateway.devices[zigpy_gpd.ieee]
    assert isinstance(zha_device, GreenPowerDevice)
    assert zha_device.available is True
    assert zha_device.on_network is True

    assert [e.device_info.pairing_status for e in full] == [
        DevicePairingStatus.CONFIGURED,
        DevicePairingStatus.INITIALIZED,
    ]
    assert full[0].new_join is True
    assert full[0].device_info.ieee == zigpy_gpd.ieee
    assert full[0].device_info.device_type == "GreenPower"

    # Initializing it again is a rejoin of a known device
    zha_gateway.device_initialized(zigpy_gpd)
    await zha_gateway.async_block_till_done()

    assert zha_gateway.devices[zigpy_gpd.ieee] is zha_device
    assert [e.device_info.pairing_status for e in full[2:]] == [
        DevicePairingStatus.CONFIGURED,
        DevicePairingStatus.INITIALIZED,
    ]
    assert full[2].new_join is False


async def test_green_power_device_left(zha_gateway: Gateway) -> None:
    """Test that a GPD leaving the network is flagged off-network and unavailable."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)
    assert zha_device.on_network is True

    left: list[DeviceLeftEvent] = []
    zha_gateway.on_event(ZHA_GW_MSG_DEVICE_LEFT, left.append)

    zha_gateway.device_left(zigpy_gpd)
    await zha_gateway.async_block_till_done()

    assert zha_device.on_network is False
    assert zha_device.available is False
    assert left == [DeviceLeftEvent(ieee=zigpy_gpd.ieee, nwk=zigpy_gpd.nwk)]


async def test_green_power_device_removed(zha_gateway: Gateway) -> None:
    """Test removal of a GPD, from zigpy and via the gateway API."""
    zigpy_gpd = make_zigpy_gpd(zha_gateway)
    zha_device = zha_gateway.get_or_create_device(zigpy_gpd)

    removed: list[DeviceRemovedEvent] = []
    zha_gateway.on_event(ZHA_GW_MSG_DEVICE_REMOVED, removed.append)

    # No groups: the gateway just asks zigpy to remove the device
    zha_gateway.application_controller.remove = AsyncMock()
    await zha_gateway.async_remove_device(zigpy_gpd.ieee)
    zha_gateway.application_controller.remove.assert_called_once_with(zigpy_gpd.ieee)

    # zigpy then announces the removal
    zha_gateway.device_removed(zigpy_gpd)
    await zha_gateway.async_block_till_done()

    assert zigpy_gpd.ieee not in zha_gateway.devices
    assert zha_gateway.get_device(zigpy_gpd.ieee) is None
    assert len(removed) == 1
    assert removed[0].device_info.ieee == zha_device.ieee
    assert removed[0].device_info.device_type == "GreenPower"

    # Removing an unknown device is a no-op
    zha_gateway.device_removed(zigpy_gpd)
    assert len(removed) == 1


async def test_green_power_recommissioned_factory_change(zha_gateway: Gateway) -> None:
    """Test that a quirk resolving on re-commissioning replaces the ZHA device."""
    zha_device = zha_gateway.get_or_create_device(make_zigpy_gpd(zha_gateway))
    assert type(zha_device) is GreenPowerDevice

    entry = GreenPowerQuirkRegistryEntry(
        device_match=GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch),
        zha_device_factory=QuirkGreenPowerDevice,
    )

    with DEVICE_REGISTRY.preserve_state():
        DEVICE_REGISTRY.register(entry)

        new_zigpy_gpd = DEVICE_REGISTRY.resolve(make_zigpy_gpd(zha_gateway))
        assert getattr(new_zigpy_gpd, QUIRK_REGISTRY_ENTRY_ATTR) is entry

        full: list[DeviceFullInitEvent] = []
        zha_gateway.on_event(ZHA_GW_MSG_DEVICE_FULL_INIT, full.append)

        zha_gateway.application_controller.listener_event(
            "device_reinterviewed", new_zigpy_gpd
        )
        await zha_gateway.async_block_till_done()

        new_zha_device = zha_gateway.devices[new_zigpy_gpd.ieee]
        assert new_zha_device is not zha_device
        assert isinstance(new_zha_device, QuirkGreenPowerDevice)
        assert new_zha_device.device is new_zigpy_gpd
        assert new_zha_device.available is True
        assert new_zha_device.on_network is True
        assert len(new_zha_device.platform_entities) == 1
        assert [e.device_info.pairing_status for e in full] == [
            DevicePairingStatus.CONFIGURED
        ]

        # The same entry on both sides is rebuilt in place
        newer_zigpy_gpd = DEVICE_REGISTRY.resolve(make_zigpy_gpd(zha_gateway))
        zha_gateway.application_controller.listener_event(
            "device_reinterviewed", newer_zigpy_gpd
        )
        await zha_gateway.async_block_till_done()
        assert zha_gateway.devices[newer_zigpy_gpd.ieee] is new_zha_device
        assert new_zha_device.device is newer_zigpy_gpd


async def test_bindable_target_source_without_clusters(zha_gateway: Gateway) -> None:
    """Test bindability with sources that do and do not have clusters."""
    gpd = zha_gateway.get_or_create_device(make_zigpy_gpd(zha_gateway))
    remote = await join_zigpy_device(
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

    # A source with clusters can bind to the coordinator
    assert async_is_bindable_target(remote, zha_gateway.coordinator_zha_device)

    # A source without clusters never can, not even to the coordinator
    assert not async_is_bindable_target(gpd, zha_gateway.coordinator_zha_device)
    assert not async_is_bindable_target(gpd, remote)


# Registry tests, using private registries so the global one is untouched
def make_gp_entry(
    match: GreenPowerDeviceMatch | None = None, file: str | None = None
) -> GreenPowerQuirkRegistryEntry:
    """Create a GP registry entry, optionally defined in `file`."""
    return GreenPowerQuirkRegistryEntry(
        device_match=match or GreenPowerDeviceMatch(device_id=DeviceID.OnOffSwitch),
        source=None
        if file is None
        else QuirkSource(module="custom", file=file, line=1, label="Custom"),
    )


def test_registry_gp_entries_iterate_remove_and_dedupe() -> None:
    """Test that GP entries are listed, deduplicated and removable."""
    registry = DeviceRegistry()
    generic = make_gp_entry()
    specific = make_gp_entry(GreenPowerDeviceMatch(device_id=1, model_id=2))
    zigbee = QuirkRegistryEntry(
        device_match=DeviceMatch(applies_to=(ModelInfo("m", "x"), ModelInfo("m", None)))
    )
    wildcard = QuirkRegistryEntry(device_match=DeviceMatch(applies_to=()))

    for entry in (generic, zigbee, wildcard, specific):
        assert registry.register(entry) is entry
        # Exact duplicates are ignored
        registry.register(entry)

    # Zigbee entries are listed once, then GP entries by specificity
    assert list(registry) == [zigbee, wildcard, specific, generic]

    registry.remove(generic)
    assert list(registry) == [zigbee, wildcard, specific]
    registry.remove(wildcard)
    registry.remove(zigbee)
    assert list(registry) == [specific]

    with pytest.raises(ValueError):
        registry.remove(generic)


def test_registry_purge_custom_quirks(tmp_path: Path) -> None:
    """Test that quirks defined under the custom quirks root are purged."""
    registry = DeviceRegistry()
    root = tmp_path / "custom_zha_quirks"

    def source(file: str | None) -> QuirkSource:
        return QuirkSource(module="m", file=file, line=1, label="Q")

    custom_gp = make_gp_entry(file=str(root / "gp.py"))
    other_gp = make_gp_entry(
        GreenPowerDeviceMatch(device_id=1), file=str(tmp_path / "builtin.py")
    )
    sourceless_gp = make_gp_entry(GreenPowerDeviceMatch(device_id=3))
    custom_zigbee = QuirkRegistryEntry(
        device_match=DeviceMatch(applies_to=(ModelInfo("a", "b"),)),
        source=source(str(root / "zigbee.py")),
    )
    custom_wildcard = QuirkRegistryEntry(
        device_match=DeviceMatch(applies_to=()), source=source(str(root / "w.py"))
    )
    builtin_zigbee = QuirkRegistryEntry(
        device_match=DeviceMatch(applies_to=(ModelInfo("c", "d"),)),
        source=source(str(tmp_path / "builtin.py")),
    )
    no_file_zigbee = QuirkRegistryEntry(
        device_match=DeviceMatch(applies_to=(ModelInfo("e", "f"),)),
        source=source(None),
    )

    entries = [
        custom_gp,
        other_gp,
        sourceless_gp,
        custom_zigbee,
        custom_wildcard,
        builtin_zigbee,
        no_file_zigbee,
    ]
    for entry in entries:
        registry.register(entry)

    registry.purge_custom_quirks(root)

    assert set(map(id, registry)) == {
        id(other_gp),
        id(sourceless_gp),
        id(builtin_zigbee),
        id(no_file_zigbee),
    }


def test_registry_register_validation() -> None:
    """Test that unusable entries and classes are rejected."""
    registry = DeviceRegistry()

    with pytest.raises(ValueError, match="manufacturer and/or model"):
        registry.register(
            QuirkRegistryEntry(
                device_match=DeviceMatch(applies_to=(ModelInfo(None, None),))
            )
        )

    class NoMatch(Device):
        _device_match = None

    with pytest.raises(ValueError, match="does not define `_device_match`"):
        registry.register_device(NoMatch)


def test_registry_register_device_transforms() -> None:
    """Test that `register_device` collects the zigpy device transforms."""
    registry = DeviceRegistry()

    def extra_transform(device: zigpy.device.ZigbeeDevice) -> zigpy.device.ZigbeeDevice:
        return device

    class Replacement:
        pass

    class QuirkedDevice(Device):
        _device_match = DeviceMatch(applies_to=(ModelInfo("mfg", "mdl"),))
        _zigpy_device_cls = Replacement  # type: ignore[assignment]
        _zigpy_device_transforms = (extra_transform,)

    assert registry.register_device(QuirkedDevice) is QuirkedDevice

    (entry,) = list(registry)
    assert entry.zha_device_factory is QuirkedDevice
    assert entry.zigpy_transforms[1:] == (extra_transform,)
    assert entry.zigpy_transforms[0].device_cls is Replacement
    assert entry.source is not None
    assert entry.source.label.endswith("QuirkedDevice")


def test_device_match_applies_to_mismatch() -> None:
    """Test that a device matching none of the `applies_to` pairs is rejected."""
    zigpy_device = MagicMock(spec=zigpy.device.ZigbeeDevice)
    zigpy_device.manufacturer = "mfg"
    zigpy_device.model = "mdl"

    assert DeviceMatch(applies_to=(ModelInfo("mfg", "mdl"),)).matches(zigpy_device)
    assert DeviceMatch(applies_to=(ModelInfo(None, "mdl"),)).matches(zigpy_device)
    assert not DeviceMatch(applies_to=(ModelInfo("mfg", "other"),)).matches(
        zigpy_device
    )
    assert not DeviceMatch(applies_to=(ModelInfo("other", None),)).matches(zigpy_device)


def test_registry_resolve_edge_cases(caplog: pytest.LogCaptureFixture) -> None:
    """Test resolving devices that are not matched or whose transform fails."""
    registry = DeviceRegistry()

    # Neither a Zigbee nor a Green Power device
    other_device = MagicMock(spec=zigpy.device.BaseDevice)
    assert registry.resolve(other_device) is other_device

    # A Zigbee device with no matching entry
    zigbee_device = MagicMock(spec=zigpy.device.ZigbeeDevice)
    zigbee_device.manufacturer = "mfg"
    zigbee_device.model = "mdl"
    assert registry.resolve(zigbee_device) is zigbee_device

    # A failing transform falls back to the bare device, untagged
    def broken(device: zigpy.device.ZigbeeDevice) -> zigpy.device.ZigbeeDevice:
        raise RuntimeError("boom")

    registry.register(
        QuirkRegistryEntry(
            device_match=DeviceMatch(applies_to=(ModelInfo("mfg", "mdl"),)),
            zigpy_transforms=(broken,),
        )
    )

    with caplog.at_level(logging.ERROR):
        assert registry.resolve(zigbee_device) is zigbee_device

    assert "Failed to load quirk" in caplog.text
    assert not hasattr(zigbee_device, QUIRK_REGISTRY_ENTRY_ATTR)
