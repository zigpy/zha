"""Test ZHA button."""

from collections.abc import Awaitable, Callable
from typing import Final
from unittest.mock import call, patch

import pytest
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.tuya.ts0601_valve import ParksideTuyaValveManufCluster
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
from zigpy.quirks import CustomCluster, CustomDevice
from zigpy.quirks.v2 import add_to_registry_v2
import zigpy.types as t
from zigpy.zcl.clusters import general, security
from zigpy.zcl.clusters.manufacturer_specific import ManufacturerSpecificCluster
import zigpy.zcl.foundation as zcl_f

from tests.common import get_entity, mock_coro, update_attribute_cache
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.platforms.button import Button, WriteAttributeButton
from zha.application.platforms.button.const import ButtonDeviceClass
from zha.exceptions import ZHAException
from zha.zigbee.device import Device


@pytest.fixture
async def contact_sensor(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> tuple[Device, general.Identify]:
    """Contact sensor fixture."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    general.Identify.cluster_id,
                    security.IasZone.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_ZONE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zha_device: Device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].identify


class FrostLockQuirk(CustomDevice):
    """Quirk with frost lock attribute."""

    class TuyaManufCluster(CustomCluster, ManufacturerSpecificCluster):
        """Tuya manufacturer specific cluster."""

        cluster_id = 0xEF00
        ep_attribute = "tuya_manufacturer"

        attributes = {0xEF01: ("frost_lock_reset", t.Bool)}

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [general.Basic.cluster_id, TuyaManufCluster],
                OUTPUT_CLUSTERS: [],
            },
        }
    }


@pytest.fixture
async def tuya_water_valve(zigpy_device_mock, device_joined):
    """Tuya Water Valve fixture."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                INPUT_CLUSTERS: [
                    general.Basic.cluster_id,
                    general.Identify.cluster_id,
                    general.Groups.cluster_id,
                    general.Scenes.cluster_id,
                    general.OnOff.cluster_id,
                    ParksideTuyaValveManufCluster.cluster_id,
                ],
                OUTPUT_CLUSTERS: [general.Time.cluster_id, general.Ota.cluster_id],
            },
        },
        manufacturer="_TZE200_htnnfasr",
        model="TS0601",
    )

    zha_device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].tuya_manufacturer


async def test_button(
    contact_sensor: tuple[Device, general.Identify],  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
) -> None:
    """Test zha button platform."""

    zha_device, cluster = contact_sensor
    assert cluster is not None
    entity: PlatformEntity = get_entity(zha_device, Platform.BUTTON)
    assert isinstance(entity, Button)
    assert entity.PLATFORM == Platform.BUTTON

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=mock_coro([0x00, zcl_f.Status.SUCCESS]),
    ):
        await entity.async_press()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 5  # duration in seconds


async def test_frost_unlock(
    zha_gateway: Gateway,
    tuya_water_valve: tuple[Device, general.Identify],  # pylint: disable=redefined-outer-name
) -> None:
    """Test custom frost unlock ZHA button."""

    zha_device, cluster = tuya_water_valve
    assert cluster is not None
    entity: PlatformEntity = get_entity(
        zha_device, platform=Platform.BUTTON, entity_type=WriteAttributeButton
    )
    assert isinstance(entity, WriteAttributeButton)

    assert entity._attr_device_class == ButtonDeviceClass.RESTART
    assert entity._attr_entity_category == EntityCategory.CONFIG

    await entity.async_press()
    await zha_gateway.async_block_till_done()
    assert cluster.write_attributes.mock_calls == [
        call({"frost_lock_reset": 0}, manufacturer=None)
    ]

    cluster.write_attributes.reset_mock()
    cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZHAException):
        await entity.async_press()
        await zha_gateway.async_block_till_done()

    # There are three retries
    assert cluster.write_attributes.mock_calls == [
        call({"frost_lock_reset": 0}, manufacturer=None),
        call({"frost_lock_reset": 0}, manufacturer=None),
        call({"frost_lock_reset": 0}, manufacturer=None),
    ]


class FakeManufacturerCluster(CustomCluster, ManufacturerSpecificCluster):
    """Fake manufacturer cluster."""

    cluster_id: Final = 0xFFF3
    ep_attribute: Final = "mfg_identify"

    class AttributeDefs(zcl_f.BaseAttributeDefs):
        """Attribute definitions."""

        feed: Final = zcl_f.ZCLAttributeDef(
            id=0x0000, type=t.uint8_t, access="rw", is_manufacturer_specific=True
        )

    class ServerCommandDefs(zcl_f.BaseCommandDefs):
        """Server command definitions."""

        self_test: Final = zcl_f.ZCLCommandDef(
            id=0x00, schema={"identify_time": t.uint16_t}, direction=False
        )


(
    add_to_registry_v2("Fake_Model", "Fake_Manufacturer")
    .replaces(FakeManufacturerCluster)
    .command_button(
        FakeManufacturerCluster.ServerCommandDefs.self_test.name,
        FakeManufacturerCluster.cluster_id,
        command_args=(5,),
    )
    .write_attr_button(
        FakeManufacturerCluster.AttributeDefs.feed.name,
        2,
        FakeManufacturerCluster.cluster_id,
    )
)


@pytest.fixture
async def custom_button_device(zigpy_device_mock, device_joined):
    """Button device fixture for quirks button tests."""

    zigpy_device = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    FakeManufacturerCluster.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.REMOTE_CONTROL,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="Fake_Model",
        model="Fake_Manufacturer",
    )

    zigpy_device.endpoints[1].mfg_identify.PLUGGED_ATTR_READS = {
        FakeManufacturerCluster.AttributeDefs.feed.name: 0,
    }
    update_attribute_cache(zigpy_device.endpoints[1].mfg_identify)
    zha_device = await device_joined(zigpy_device)
    return zha_device, zigpy_device.endpoints[1].mfg_identify


async def test_quirks_command_button(
    zha_gateway: Gateway,
    custom_button_device: tuple[Device, general.Identify],  # pylint: disable=redefined-outer-name
) -> None:
    """Test ZHA button platform."""

    zha_device, cluster = custom_button_device
    assert cluster is not None
    entity: PlatformEntity = get_entity(zha_device, platform=Platform.BUTTON)

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_press()
        await zha_gateway.async_block_till_done()
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0
        assert cluster.request.call_args[0][3] == 5  # duration in seconds


async def test_quirks_write_attr_button(
    zha_gateway: Gateway,
    custom_button_device: tuple[Device, general.Identify],  # pylint: disable=redefined-outer-name
) -> None:
    """Test ZHA button platform."""

    zha_device, cluster = custom_button_device
    assert cluster is not None
    entity: PlatformEntity = get_entity(
        zha_device, platform=Platform.BUTTON, entity_type=WriteAttributeButton
    )

    assert cluster.get(cluster.AttributeDefs.feed.name) == 0

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_press()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({cluster.AttributeDefs.feed.name: 2}, manufacturer=None)
        ]

    assert cluster.get(cluster.AttributeDefs.feed.name) == 2
