"""Tests for ZHA Green Power devices."""

from __future__ import annotations

from zigpy.device import GreenPowerDevice as ZigpyGreenPowerDevice
from zigpy.types import EUI64
from zigpy.zgp.types import ApplicationID, DeviceID, GPDCommandID, SrcID

from zha.application.const import UNKNOWN_MANUFACTURER, UNKNOWN_MODEL
from zha.application.gateway import Gateway
from zha.quirks import (
    DEVICE_REGISTRY,
    QUIRK_REGISTRY_ENTRY_ATTR,
    GreenPowerDeviceMatch,
    GreenPowerQuirkRegistryEntry,
)
from zha.zigbee.device import GreenPowerDevice


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

    diagnostics = zha_device.get_diagnostics_json()
    assert diagnostics["ieee"] == str(zigpy_gpd.ieee)
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
        endpoint=1,
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
        DEVICE_REGISTRY.register(generic_entry)
        DEVICE_REGISTRY.register(entry)

        # The most recently registered matching entry wins
        assert DEVICE_REGISTRY.match_green_power_entry(zigpy_gpd) is entry

        resolved = DEVICE_REGISTRY.resolve(zigpy_gpd)
        assert resolved is zigpy_gpd
        assert getattr(resolved, QUIRK_REGISTRY_ENTRY_ATTR) is entry

        zha_device = zha_gateway.get_or_create_device(resolved)
        assert isinstance(zha_device, QuirkedGreenPowerDevice)
        assert zha_device.quirk_applied
