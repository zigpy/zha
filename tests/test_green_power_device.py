"""Tests for ZHA Green Power devices."""

from __future__ import annotations

from zigpy.device import GreenPowerDevice as ZigpyGreenPowerDevice
from zigpy.zgp.types import ApplicationID, DeviceID, GPDCommandID, SrcID

from zha.application.const import UNKNOWN_MANUFACTURER, UNKNOWN_MODEL
from zha.application.gateway import Gateway
from zha.quirks import DEVICE_REGISTRY
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
