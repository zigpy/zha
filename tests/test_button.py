"""Test ZHA button."""

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
from zhaquirks.tuya.tuya_valve import ParksideTuyaValveManufCluster
import zigpy
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
from zigpy.quirks import CustomCluster, CustomDevice, DeviceRegistry
from zigpy.quirks.v2 import CustomDeviceV2, QuirkBuilder
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl.clusters import general, security
from zigpy.zcl.clusters.manufacturer_specific import ManufacturerSpecificCluster
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    mock_coro,
    patch_cluster_for_testing,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.const import ZCL_INIT_ATTRS
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.platforms.button import (
    Button,
    FrostLockResetButton,
    WriteAttributeButton,
)
from zha.application.platforms.button.const import ButtonDeviceClass
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers.manufacturerspecific import OppleRemoteClusterHandler
from zha.zigbee.device import Device

ZIGPY_DEVICE = {
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
}


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


TUYA_WATER_VALVE = {
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
}


async def test_button(
    zha_gateway: Gateway,
) -> None:
    """Test zha button platform."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        ZIGPY_DEVICE,
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints[1].identify
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
) -> None:
    """Test custom frost unlock ZHA button."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        TUYA_WATER_VALVE,
        manufacturer="_TZE200_htnnfasr",
        model="TS0601",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints[1].tuya_manufacturer
    assert cluster is not None
    entity: PlatformEntity = get_entity(
        zha_device,
        platform=Platform.BUTTON,
        entity_type=FrostLockResetButton,
    )
    assert isinstance(entity, FrostLockResetButton)

    assert entity._attr_device_class == ButtonDeviceClass.RESTART
    assert entity._attr_entity_category == EntityCategory.CONFIG

    await entity.async_press()
    await zha_gateway.async_block_till_done()
    assert cluster.write_attributes.mock_calls == [
        call({"frost_lock_reset": 0}, manufacturer=UNDEFINED)
    ]

    cluster.write_attributes.reset_mock()
    cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZHAException):
        await entity.async_press()
        await zha_gateway.async_block_till_done()

    # There are three retries
    assert cluster.write_attributes.mock_calls == [
        call({"frost_lock_reset": 0}, manufacturer=UNDEFINED),
        call({"frost_lock_reset": 0}, manufacturer=UNDEFINED),
        call({"frost_lock_reset": 0}, manufacturer=UNDEFINED),
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
            id=0x00, schema={"identify_time": t.uint16_t}
        )


async def custom_button_device(zha_gateway: Gateway):
    """Button device fixture for quirks button tests."""

    registry = DeviceRegistry()
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
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

    (
        QuirkBuilder("Fake_Model", "Fake_Manufacturer", registry=registry)
        .replaces(FakeManufacturerCluster)
        .command_button(
            FakeManufacturerCluster.ServerCommandDefs.self_test.name,
            FakeManufacturerCluster.cluster_id,
            command_args=(5,),
            translation_key="self_test",
            fallback_name="Self test",
        )
        .write_attr_button(
            FakeManufacturerCluster.AttributeDefs.feed.name,
            2,
            FakeManufacturerCluster.cluster_id,
            translation_key="feed",
            fallback_name="Feed",
        )
        .add_to_registry()
    )

    zigpy_device = registry.get_device(zigpy_device)

    assert isinstance(zigpy_device, CustomDeviceV2)
    # XXX: this should be handled automatically, patch quirks added cluster
    patch_cluster_for_testing(zigpy_device.endpoints[1].mfg_identify)

    zigpy_device.endpoints[1].mfg_identify.PLUGGED_ATTR_READS = {
        FakeManufacturerCluster.AttributeDefs.feed.name: 0,
    }
    update_attribute_cache(zigpy_device.endpoints[1].mfg_identify)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device, zigpy_device.endpoints[1].mfg_identify


async def test_quirks_command_button(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA button platform."""
    zha_device, cluster = await custom_button_device(zha_gateway)
    assert cluster is not None
    entity: PlatformEntity = get_entity(
        zha_device, platform=Platform.BUTTON, entity_type=Button
    )

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
) -> None:
    """Test ZHA button platform."""
    zha_device, cluster = await custom_button_device(zha_gateway)
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
            call({cluster.AttributeDefs.feed.name: 2}, manufacturer=UNDEFINED)
        ]

    assert cluster.get(cluster.AttributeDefs.feed.name) == 2


async def test_quirks_write_attr_buttons_uid(zha_gateway: Gateway) -> None:
    """Test multiple buttons created with different unique id suffixes."""

    registry = DeviceRegistry()
    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
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

    (
        QuirkBuilder("Fake_Model", "Fake_Manufacturer", registry=registry)
        .replaces(FakeManufacturerCluster)
        .write_attr_button(
            FakeManufacturerCluster.AttributeDefs.feed.name,
            1,
            FakeManufacturerCluster.cluster_id,
            unique_id_suffix="btn_1",
            translation_key="btn_1",
            fallback_name="Button 1",
        )
        .write_attr_button(
            FakeManufacturerCluster.AttributeDefs.feed.name,
            2,
            FakeManufacturerCluster.cluster_id,
            unique_id_suffix="btn_2",
            translation_key="btn_2",
            fallback_name="Button 2",
        )
        .add_to_registry()
    )

    zigpy_device_ = registry.get_device(zigpy_dev)

    assert isinstance(zigpy_device_, CustomDeviceV2)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)

    entity_btn_1 = get_entity(zha_device, platform=Platform.BUTTON, qualifier="btn_1")
    entity_btn_2 = get_entity(zha_device, platform=Platform.BUTTON, qualifier="btn_2")

    # check both entities are created and have a different unique id suffix
    assert isinstance(entity_btn_1, WriteAttributeButton)
    assert entity_btn_1.translation_key == "btn_1"
    assert entity_btn_1._unique_id_suffix == "btn_1"
    assert entity_btn_1._attribute_value == 1

    assert isinstance(entity_btn_2, WriteAttributeButton)
    assert entity_btn_2.translation_key == "btn_2"
    assert entity_btn_2._unique_id_suffix == "btn_2"
    assert entity_btn_2._attribute_value == 2


class OppleCluster(CustomCluster, ManufacturerSpecificCluster):
    """Aqara manufacturer specific cluster."""

    cluster_id = 0xFCC0
    ep_attribute = "opple_cluster"

    class ServerCommandDefs(zcl_f.BaseCommandDefs):
        """Server command definitions."""

        self_test: Final = zcl_f.ZCLCommandDef(
            id=0x00, schema={"identify_time": t.uint16_t}
        )


async def test_cluster_handler_quirks_unnecessary_claiming(
    zha_gateway: Gateway,
) -> None:
    """Test quirks button doesn't claim cluster handlers unnecessarily."""

    registry = DeviceRegistry()
    (
        QuirkBuilder(
            "Fake_Manufacturer_sensor_2", "Fake_Model_sensor_2", registry=registry
        )
        .replaces(OppleCluster)
        .command_button(
            OppleCluster.ServerCommandDefs.self_test.name,
            OppleCluster.cluster_id,
            command_kwargs={"identify_time": 5},
            translation_key="self_test",
            fallback_name="Self test",
        )
        .add_to_registry()
    )

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    OppleCluster.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.OCCUPANCY_SENSOR,
                SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            }
        },
        manufacturer="Fake_Manufacturer_sensor_2",
        model="Fake_Model_sensor_2",
    )
    zigpy_device = registry.get_device(zigpy_device)

    # Suppress normal endpoint probing, as this will claim the Opple cluster handler
    # already due to it being in the "CLUSTER_HANDLER_ONLY_CLUSTERS" registry.
    # We want to test the handler also gets claimed via quirks v2 attributes init.
    with patch("zha.application.discovery.discover_entities_for_endpoint"):
        zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    assert isinstance(zha_device.device, CustomDeviceV2)

    # get cluster handler of OppleCluster
    opple_ch = zha_device.endpoints[1].all_cluster_handlers["1:0xfcc0"]
    assert isinstance(opple_ch, OppleRemoteClusterHandler)

    # make sure the cluster handler was not claimed,
    # as no reporting is configured and no attributes are to be read
    assert opple_ch not in zha_device.endpoints[1].claimed_cluster_handlers.values()

    # check that BIND is left at default of True, though ZHA will ignore it
    assert opple_ch.BIND is True

    # check ZCL_INIT_ATTRS is empty
    assert opple_ch.ZCL_INIT_ATTRS == {}

    # check that no ZCL_INIT_ATTRS instance variable was created
    assert opple_ch.__dict__.get(ZCL_INIT_ATTRS) is None
    assert opple_ch.ZCL_INIT_ATTRS is OppleRemoteClusterHandler.ZCL_INIT_ATTRS

    # double check we didn't modify the class variable
    assert OppleRemoteClusterHandler.ZCL_INIT_ATTRS == {}

    # check if REPORT_CONFIG is empty, both instance and class variable
    assert opple_ch.REPORT_CONFIG == ()
    assert OppleRemoteClusterHandler.REPORT_CONFIG == ()
