"""Test ZHA select entities."""

from unittest.mock import call, patch

import pytest
from zhaquirks import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.builder import QuirkBuilder
from zhaquirks.clusters import CustomCluster
from zhaquirks.device import CustomZigpyDevice
from zhaquirks.legacy import CustomDevice, get_device
from zigpy.const import SIG_EP_PROFILE
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.typing import UNDEFINED
from zigpy.zcl import foundation
from zigpy.zcl.clusters import general, security
from zigpy.zcl.clusters.manufacturer_specific import ManufacturerSpecificCluster

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    send_attributes_report,
    zigpy_device_from_json,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import EntityCategory
from zha.application.platforms.select import (
    AqaraMotionSensitivities,
    BegaColorTemperatureChannel,
)


async def test_select(zha_gateway: Gateway) -> None:
    """Test zha select platform."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints[1].ias_wd
    assert cluster is not None
    select_name = security.IasWd.Warning.WarningMode.__name__

    entity = get_entity(zha_device, platform=Platform.SELECT, qualifier=select_name)
    assert entity.state.current_option is None  # unknown in HA
    assert entity.state.options == [
        "Stop",
        "Burglar",
        "Fire",
        "Emergency",
        "Police Panic",
        "Fire Panic",
        "Emergency Panic",
    ]
    assert entity._enum == security.IasWd.Warning.WarningMode

    # change value from client
    await entity.async_select_option(security.IasWd.Warning.WarningMode.Burglar.name)
    await zha_gateway.async_block_till_done()
    assert (
        entity.state.current_option == security.IasWd.Warning.WarningMode.Burglar.name
    )


class MotionSensitivityQuirk(CustomDevice):
    """Quirk with motion sensitivity attribute."""

    class OppleCluster(CustomCluster, ManufacturerSpecificCluster):
        """Aqara manufacturer specific cluster."""

        cluster_id = 0xFCC0
        ep_attribute = "opple_cluster"
        attributes = {
            0x010C: ("motion_sensitivity", t.uint8_t, True),
            0x020C: ("motion_sensitivity_disabled", t.uint8_t, True),
        }

        def __init__(self, *args, **kwargs):
            """Initialize."""
            super().__init__(*args, **kwargs)
            # populate cache to create config entity
            self._attr_cache.update(
                {
                    0x010C: AqaraMotionSensitivities.Medium,
                    0x020C: AqaraMotionSensitivities.Medium,
                }
            )

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.OCCUPANCY_SENSOR,
                INPUT_CLUSTERS: [general.Basic.cluster_id, OppleCluster],
                OUTPUT_CLUSTERS: [],
            },
        }
    }


async def test_on_off_select_attribute_report(zha_gateway: Gateway) -> None:
    """Test ZHA attribute report parsing for select platform."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.OCCUPANCY_SENSOR,
            }
        },
        manufacturer="LUMI",
        model="lumi.motion.ac02",
        quirk=MotionSensitivityQuirk,
    )

    zigpy_device = get_device(zigpy_device)
    aqara_sensor = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = aqara_sensor.device.endpoints.get(1).opple_cluster

    entity = get_entity(aqara_sensor, platform=Platform.SELECT)
    assert entity.state.current_option == AqaraMotionSensitivities.Medium.name

    # send attribute report from device
    await send_attributes_report(
        zha_gateway, cluster, {"motion_sensitivity": AqaraMotionSensitivities.Low}
    )
    assert entity.state.current_option == AqaraMotionSensitivities.Low.name


(
    QuirkBuilder("Fake_Manufacturer", "Fake_Model")
    .replaces(MotionSensitivityQuirk.OppleCluster)
    .enum(
        "motion_sensitivity",
        AqaraMotionSensitivities,
        MotionSensitivityQuirk.OppleCluster.cluster_id,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
    )
    .enum(
        "motion_sensitivity_disabled",
        AqaraMotionSensitivities,
        MotionSensitivityQuirk.OppleCluster.cluster_id,
        translation_key="motion_sensitivity",
        fallback_name="Motion sensitivity",
        initially_disabled=True,
    )
    .add_to_registry()
)


async def test_on_off_select_attribute_report_v2(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA attribute report parsing for select platform."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.Basic.cluster_id,
                    MotionSensitivityQuirk.OppleCluster.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.OCCUPANCY_SENSOR,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="Fake_Manufacturer",
        model="Fake_Model",
        attributes={
            1: {
                "opple_cluster": {
                    "motion_sensitivity": AqaraMotionSensitivities.Medium,
                    "motion_sensitivity_disabled": AqaraMotionSensitivities.Medium,
                }
            }
        },
    )
    zigpy_device = get_device(zigpy_device)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints[1].opple_cluster
    assert isinstance(zha_device.device, CustomZigpyDevice)

    entity = get_entity(
        zha_device,
        platform=Platform.SELECT,
        qualifier_func=lambda e: e.state.unique_id.endswith("motion_sensitivity"),
    )

    # test that the state is in default medium state
    assert entity.state.current_option == AqaraMotionSensitivities.Medium.name

    # send attribute report from device
    await send_attributes_report(
        zha_gateway, cluster, {"motion_sensitivity": AqaraMotionSensitivities.Low}
    )
    assert entity.state.current_option == AqaraMotionSensitivities.Low.name

    assert entity._attr_entity_category == EntityCategory.CONFIG
    assert entity._attr_entity_registry_enabled_default is True
    assert entity._attr_translation_key == "motion_sensitivity"

    Write_Attributes_rsp = foundation.GENERAL_COMMANDS[
        foundation.GeneralCommand.Write_Attributes_rsp
    ].schema

    with (
        patch(
            "zigpy.device.Device.request",
            return_value=Write_Attributes_rsp(
                status_records=[
                    foundation.WriteAttributesStatusRecord(
                        status=foundation.Status.SUCCESS
                    )
                ]
            ),
        ),
        patch.object(cluster, "write_attributes", wraps=cluster.write_attributes),
    ):
        await entity.async_select_option(AqaraMotionSensitivities.Medium.name)

        await zha_gateway.async_block_till_done()
        assert entity.state.current_option == AqaraMotionSensitivities.Medium.name
        assert cluster.write_attributes.call_count == 1
        assert cluster.write_attributes.call_args == call(
            {"motion_sensitivity": AqaraMotionSensitivities.Medium},
            manufacturer=UNDEFINED,
        )


async def test_non_zcl_select_state_restoration(zha_gateway: Gateway) -> None:
    """Test the non-ZCL select state restoration."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, security.IasWd.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.IAS_WARNING_DEVICE,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(zha_device, platform=Platform.SELECT, qualifier="WarningMode")

    assert entity.state.current_option is None

    entity.restore_external_state_attributes(
        state=security.IasWd.Warning.WarningMode.Burglar.name
    )
    assert (
        entity.state.current_option == security.IasWd.Warning.WarningMode.Burglar.name
    )

    entity.restore_external_state_attributes(
        state=security.IasWd.Warning.WarningMode.Fire.name
    )
    assert entity.state.current_option == security.IasWd.Warning.WarningMode.Fire.name


async def test_bega_color_temperature_channel_select(zha_gateway: Gateway) -> None:
    """Test BEGA color temperature channel select entity."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/bega-gantenbrink-leuchten-kg-smart-dimmable-light-0x00990be9.json",
    )

    cluster = zigpy_device.endpoints[1].in_clusters[general.LevelControl.cluster_id]
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity = get_entity(
        zha_device,
        platform=Platform.SELECT,
        qualifier="switchable_white",
    )
    assert entity.state.current_option == "Warm white"
    assert entity.state.options == ["Warm white", "Cool white"]

    # send attribute report from device
    await send_attributes_report(
        zha_gateway,
        cluster,
        {"switchable_white": BegaColorTemperatureChannel.Cool_white},
    )
    assert entity.state.current_option == "Cool white"

    # test selecting an option
    Write_Attributes_rsp = foundation.GENERAL_COMMANDS[
        foundation.GeneralCommand.Write_Attributes_rsp
    ].schema

    with (
        patch(
            "zigpy.device.Device.request",
            return_value=Write_Attributes_rsp(
                status_records=[
                    foundation.WriteAttributesStatusRecord(
                        status=foundation.Status.SUCCESS
                    )
                ]
            ),
        ),
        patch.object(cluster, "write_attributes", wraps=cluster.write_attributes),
    ):
        await entity.async_select_option("Warm white")
        await zha_gateway.async_block_till_done()
        assert entity.state.current_option == "Warm white"
        assert cluster.write_attributes.call_count == 1
        assert cluster.write_attributes.call_args == call(
            {"switchable_white": BegaColorTemperatureChannel.Warm_white},
            manufacturer=UNDEFINED,
        )


@pytest.mark.parametrize(
    ("temp_1", "temp_2"),
    [
        (0xFFFF, 0xFFFF),
        (0xFFFF, 3000),
        (3000, 0xFFFF),
    ],
)
async def test_bega_color_temperature_channel_select_unsupported(
    zha_gateway: Gateway,
    temp_1: int,
    temp_2: int,
) -> None:
    """Test BEGA select entity is not created when a color temp is 0xFFFF."""
    zigpy_device = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/bega-gantenbrink-leuchten-kg-smart-dimmable-light-0x00990be9.json",
    )

    cluster = zigpy_device.endpoints[1].in_clusters[general.LevelControl.cluster_id]
    cluster.update_attribute(
        cluster.find_attribute("switchable_color_temperature_1").id, temp_1
    )
    cluster.update_attribute(
        cluster.find_attribute("switchable_color_temperature_2").id, temp_2
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    with pytest.raises(KeyError):
        get_entity(
            zha_device,
            platform=Platform.SELECT,
            qualifier="switchable_white",
        )
