"""Test ZHA firmware updates."""

from unittest.mock import ANY, AsyncMock, call, patch

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import DeliveryError
from zigpy.ota import OtaImagesResult, OtaImageWithMetadata
import zigpy.ota.image as firmware
from zigpy.ota.providers import BaseOtaImageMetadata
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.zcl import Cluster, foundation
from zigpy.zcl.clusters import general
import zigpy.zdo.types as zdo_t

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms.update import (
    ATTR_IN_PROGRESS,
    ATTR_INSTALLED_VERSION,
    ATTR_LATEST_VERSION,
    ATTR_UPDATE_PERCENTAGE,
)
from zha.exceptions import ZHAException


def zigpy_device_mock(zha_gateway: Gateway):
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
            SIG_EP_OUTPUT: [general.Ota.cluster_id],
            SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return create_mock_zigpy_device(
        zha_gateway,
        endpoints,
        node_descriptor=zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.EndDevice,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
            ),
            manufacturer_code=4447,
            maximum_buffer_size=127,
            maximum_incoming_transfer_size=100,
            server_mask=11264,
            maximum_outgoing_transfer_size=100,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        ),
    )


def create_fw_image(version: int) -> OtaImageWithMetadata:
    """Create an OTA image with a specific file version."""
    return OtaImageWithMetadata(
        metadata=BaseOtaImageMetadata(
            file_version=version,
            manufacturer_id=0x1234,
            image_type=0x90,
            changelog="This is a test firmware image!",
        ),
        firmware=firmware.OTAImage(
            header=firmware.OTAImageHeader(
                upgrade_file_id=firmware.OTAImageHeader.MAGIC_VALUE,
                file_version=version,
                image_type=0x90,
                manufacturer_id=0x1234,
                header_version=256,
                header_length=56,
                field_control=0,
                stack_version=2,
                header_string="This is a test header!",
                image_size=56 + 2 + 4 + 8,
            ),
            subelements=[firmware.SubElement(tag_id=0x0000, data=b"fw_image")],
        ),
    )


def make_packet(
    zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    cluster: Cluster,
    cmd_name: str,
    **kwargs,
):
    """Make a zigpy packet."""
    req_hdr, req_cmd = cluster._create_request(
        general=False,
        command_id=cluster.commands_by_name[cmd_name].id,
        schema=cluster.commands_by_name[cmd_name].schema,
        disable_default_response=False,
        direction=foundation.Direction.Client_to_Server,
        args=(),
        kwargs=kwargs,
    )

    ota_packet = t.ZigbeePacket(
        src=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=zigpy_device.nwk),
        src_ep=1,
        dst=t.AddrModeAddress(addr_mode=t.AddrMode.NWK, address=0x0000),
        dst_ep=1,
        tsn=req_hdr.tsn,
        profile_id=260,
        cluster_id=cluster.cluster_id,
        data=t.SerializableBytes(req_hdr.serialize() + req_cmd.serialize()),
        lqi=255,
        rssi=-30,
    )

    return ota_packet


async def setup_test_data(
    zha_gateway: Gateway,
    zigpy_device: ZigpyDevice,
):
    """Set up test data for the tests."""
    installed_fw_version = 0x12345678

    ota_cluster = zigpy_device.endpoints[1].out_clusters[general.Ota.cluster_id]
    ota_cluster.PLUGGED_ATTR_READS = {
        general.Ota.AttributeDefs.current_file_version.name: installed_fw_version
    }
    update_attribute_cache(ota_cluster)

    # set up firmware image
    fw_image = create_fw_image(installed_fw_version + 10)

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(fw_image,),
            downgrades=(),
        )
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    zha_device.async_update_sw_build_id(installed_fw_version)

    return zha_device, ota_cluster, fw_image, installed_fw_version


async def test_firmware_update_notification_from_zigpy(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - firmware update notification."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)
    assert (
        entity.state["latest_version"]
        == entity.state["installed_version"]
        == f"0x{installed_fw_version:08x}"
    )

    # simulate an image available notification
    await ota_cluster._handle_query_next_image(
        foundation.ZCLHeader.cluster(
            tsn=0x12, command_id=general.Ota.ServerCommandDefs.query_next_image.id
        ),
        general.QueryNextImageCommand(
            field_control=fw_image.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image.firmware.header.image_type,
            current_file_version=installed_fw_version,
            hardware_version=1,
        ),
    )

    await zha_gateway.async_block_till_done()
    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert entity.state[ATTR_IN_PROGRESS] is False
    assert (
        entity.state[ATTR_LATEST_VERSION]
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )


@patch("zigpy.device.AFTER_OTA_ATTR_READ_DELAY", 0.01)
async def test_firmware_update_success(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - firmware update success."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    assert installed_fw_version < fw_image.firmware.header.file_version

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    # simulate an image available notification
    await ota_cluster._handle_query_next_image(
        foundation.ZCLHeader.cluster(
            tsn=0x12, command_id=general.Ota.ServerCommandDefs.query_next_image.id
        ),
        general.QueryNextImageCommand(
            field_control=fw_image.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image.firmware.header.image_type,
            current_file_version=installed_fw_version,
        ),
    )

    await zha_gateway.async_block_till_done()
    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert entity.state[ATTR_IN_PROGRESS] is False
    assert (
        entity.state[ATTR_LATEST_VERSION]
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )

    async def endpoint_reply(cluster, sequence, data, **kwargs):
        if cluster == general.Ota.cluster_id:
            hdr, cmd = ota_cluster.deserialize(data)
            if isinstance(cmd, general.Ota.ImageNotifyCommand):
                zigpy_device.packet_received(
                    make_packet(
                        zigpy_device,
                        ota_cluster,
                        general.Ota.ServerCommandDefs.query_next_image.name,
                        field_control=general.Ota.QueryNextImageCommand.FieldControl.HardwareVersion,
                        manufacturer_code=fw_image.firmware.header.manufacturer_id,
                        image_type=fw_image.firmware.header.image_type,
                        current_file_version=fw_image.firmware.header.file_version - 10,
                        hardware_version=1,
                    )
                )
            elif isinstance(
                cmd, general.Ota.ClientCommandDefs.query_next_image_response.schema
            ):
                assert cmd.status == foundation.Status.SUCCESS
                assert cmd.manufacturer_code == fw_image.firmware.header.manufacturer_id
                assert cmd.image_type == fw_image.firmware.header.image_type
                assert cmd.file_version == fw_image.firmware.header.file_version
                assert cmd.image_size == fw_image.firmware.header.image_size
                zigpy_device.packet_received(
                    make_packet(
                        zigpy_device,
                        ota_cluster,
                        general.Ota.ServerCommandDefs.image_block.name,
                        field_control=general.Ota.ImageBlockCommand.FieldControl.RequestNodeAddr,
                        manufacturer_code=fw_image.firmware.header.manufacturer_id,
                        image_type=fw_image.firmware.header.image_type,
                        file_version=fw_image.firmware.header.file_version,
                        file_offset=0,
                        maximum_data_size=40,
                        request_node_addr=zigpy_device.ieee,
                    )
                )
            elif isinstance(
                cmd, general.Ota.ClientCommandDefs.image_block_response.schema
            ):
                if cmd.file_offset == 0:
                    assert cmd.status == foundation.Status.SUCCESS
                    assert (
                        cmd.manufacturer_code
                        == fw_image.firmware.header.manufacturer_id
                    )
                    assert cmd.image_type == fw_image.firmware.header.image_type
                    assert cmd.file_version == fw_image.firmware.header.file_version
                    assert cmd.file_offset == 0
                    assert cmd.image_data == fw_image.firmware.serialize()[0:40]
                    zigpy_device.packet_received(
                        make_packet(
                            zigpy_device,
                            ota_cluster,
                            general.Ota.ServerCommandDefs.image_block.name,
                            field_control=general.Ota.ImageBlockCommand.FieldControl.RequestNodeAddr,
                            manufacturer_code=fw_image.firmware.header.manufacturer_id,
                            image_type=fw_image.firmware.header.image_type,
                            file_version=fw_image.firmware.header.file_version,
                            file_offset=40,
                            maximum_data_size=40,
                            request_node_addr=zigpy_device.ieee,
                        )
                    )
                elif cmd.file_offset == 40:
                    assert cmd.status == foundation.Status.SUCCESS
                    assert (
                        cmd.manufacturer_code
                        == fw_image.firmware.header.manufacturer_id
                    )
                    assert cmd.image_type == fw_image.firmware.header.image_type
                    assert cmd.file_version == fw_image.firmware.header.file_version
                    assert cmd.file_offset == 40
                    assert cmd.image_data == fw_image.firmware.serialize()[40:70]

                    # make sure the state machine gets progress reports

                    assert (
                        entity.state[ATTR_INSTALLED_VERSION]
                        == f"0x{installed_fw_version:08x}"
                    )
                    assert entity.state[ATTR_IN_PROGRESS] is True
                    assert entity.state[ATTR_UPDATE_PERCENTAGE] == pytest.approx(
                        100 * (40 / 70)
                    )
                    assert (
                        entity.state[ATTR_LATEST_VERSION]
                        == f"0x{fw_image.firmware.header.file_version:08x}"
                    )

                    zigpy_device.packet_received(
                        make_packet(
                            zigpy_device,
                            ota_cluster,
                            general.Ota.ServerCommandDefs.upgrade_end.name,
                            status=foundation.Status.SUCCESS,
                            manufacturer_code=fw_image.firmware.header.manufacturer_id,
                            image_type=fw_image.firmware.header.image_type,
                            file_version=fw_image.firmware.header.file_version,
                        )
                    )

            elif isinstance(
                cmd, general.Ota.ClientCommandDefs.upgrade_end_response.schema
            ):
                assert cmd.manufacturer_code == fw_image.firmware.header.manufacturer_id
                assert cmd.image_type == fw_image.firmware.header.image_type
                assert cmd.file_version == fw_image.firmware.header.file_version
                assert cmd.current_time == 0
                assert cmd.upgrade_time == 0

                def read_new_fw_version(*args, **kwargs):
                    ota_cluster.update_attribute(
                        attrid=general.Ota.AttributeDefs.current_file_version.id,
                        value=fw_image.firmware.header.file_version,
                    )
                    return {
                        general.Ota.AttributeDefs.current_file_version.id: (
                            fw_image.firmware.header.file_version
                        )
                    }, {}

                ota_cluster.read_attributes.side_effect = read_new_fw_version

    ota_cluster.endpoint.reply = AsyncMock(side_effect=endpoint_reply)

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    await entity.async_install(version=None)
    await zha_gateway.async_block_till_done()

    assert (
        entity.state[ATTR_INSTALLED_VERSION]
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )
    assert not entity.state[ATTR_IN_PROGRESS]
    assert entity.state[ATTR_LATEST_VERSION] == entity.state[ATTR_INSTALLED_VERSION]

    # If we send a progress notification incorrectly, it won't be handled
    entity._update_progress(50, 100, 0.50)

    assert not entity.state[ATTR_IN_PROGRESS]


async def test_firmware_update_raises(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - firmware update raises."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    # simulate an image available notification
    await ota_cluster._handle_query_next_image(
        foundation.ZCLHeader.cluster(
            tsn=0x12, command_id=general.Ota.ServerCommandDefs.query_next_image.id
        ),
        general.QueryNextImageCommand(
            field_control=fw_image.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image.firmware.header.image_type,
            current_file_version=installed_fw_version,
            hardware_version=1,
        ),
    )

    await zha_gateway.async_block_till_done()
    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert not entity.state[ATTR_IN_PROGRESS]
    assert (
        entity.state[ATTR_LATEST_VERSION]
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )

    async def endpoint_reply(cluster, sequence, data, **kwargs):
        if cluster == general.Ota.cluster_id:
            hdr, cmd = ota_cluster.deserialize(data)
            if isinstance(cmd, general.Ota.ImageNotifyCommand):
                zigpy_device.packet_received(
                    make_packet(
                        zigpy_device,
                        ota_cluster,
                        general.Ota.ServerCommandDefs.query_next_image.name,
                        field_control=general.Ota.QueryNextImageCommand.FieldControl.HardwareVersion,
                        manufacturer_code=fw_image.firmware.header.manufacturer_id,
                        image_type=fw_image.firmware.header.image_type,
                        current_file_version=fw_image.firmware.header.file_version - 10,
                        hardware_version=1,
                    )
                )
            elif isinstance(
                cmd, general.Ota.ClientCommandDefs.query_next_image_response.schema
            ):
                assert cmd.status == foundation.Status.SUCCESS
                assert cmd.manufacturer_code == fw_image.firmware.header.manufacturer_id
                assert cmd.image_type == fw_image.firmware.header.image_type
                assert cmd.file_version == fw_image.firmware.header.file_version
                assert cmd.image_size == fw_image.firmware.header.image_size
                raise DeliveryError("failed to deliver")

    ota_cluster.endpoint.reply = AsyncMock(side_effect=endpoint_reply)
    with pytest.raises(ZHAException):
        await entity.async_install(
            version=f"0x{fw_image.firmware.header.file_version:08x}"
        )
        await zha_gateway.async_block_till_done()

    with (
        patch(
            "zigpy.device.Device.update_firmware",
            AsyncMock(side_effect=DeliveryError("failed to deliver")),
        ),
        pytest.raises(ZHAException),
    ):
        await entity.async_install(
            version=f"0x{fw_image.firmware.header.file_version:08x}"
        )
        await zha_gateway.async_block_till_done()


async def test_firmware_update_downgrade(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - force a firmware downgrade."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    fw_image_downgrade = create_fw_image(installed_fw_version - 10)

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(fw_image,),
            downgrades=(fw_image_downgrade,),
        )
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    # simulate an image available notification
    await ota_cluster._handle_query_next_image(
        foundation.ZCLHeader.cluster(
            tsn=0x12, command_id=general.Ota.ServerCommandDefs.query_next_image.id
        ),
        general.QueryNextImageCommand(
            field_control=fw_image.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image.firmware.header.image_type,
            current_file_version=installed_fw_version,
            hardware_version=1,
        ),
    )

    await zha_gateway.async_block_till_done()
    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert not entity.state[ATTR_IN_PROGRESS]
    assert (
        entity.state[ATTR_LATEST_VERSION]
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )

    with patch.object(
        zigpy_device, "update_firmware", return_value=foundation.Status.SUCCESS
    ) as mock_update:
        # Only the specific versions we have to install can be installed
        with pytest.raises(ZHAException):
            await entity.async_install(
                version=f"0x{fw_image_downgrade.firmware.header.file_version - 1:08x}"
            )

        await entity.async_install(
            version=f"0x{fw_image_downgrade.firmware.header.file_version:08x}"
        )
        # Pretend the downgrade worked
        ota_cluster.update_attribute(
            general.Ota.AttributeDefs.current_file_version.id,
            fw_image_downgrade.firmware.header.file_version,
        )
        await zha_gateway.async_block_till_done()

    # The downgrade image was used
    assert mock_update.mock_calls == [
        call(image=fw_image_downgrade, progress_callback=ANY)
    ]

    assert (
        entity.state[ATTR_INSTALLED_VERSION]
        == f"0x{fw_image_downgrade.firmware.header.file_version:08x}"
    )
    assert not entity.state[ATTR_IN_PROGRESS]
    assert (
        entity.state[ATTR_LATEST_VERSION]
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )


async def test_firmware_update_no_image(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - no images exist."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(),
            downgrades=(),
        )
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    # simulate an image available notification
    await ota_cluster._handle_query_next_image(
        foundation.ZCLHeader.cluster(
            tsn=0x12, command_id=general.Ota.ServerCommandDefs.query_next_image.id
        ),
        general.QueryNextImageCommand(
            field_control=fw_image.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image.firmware.header.image_type,
            current_file_version=installed_fw_version,
            hardware_version=1,
        ),
    )

    await zha_gateway.async_block_till_done()
    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert not entity.state[ATTR_IN_PROGRESS]
    assert entity.state[ATTR_LATEST_VERSION] is None

    with pytest.raises(ZHAException):
        await entity.async_install(version=None)

    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert not entity.state[ATTR_IN_PROGRESS]
    assert entity.state[ATTR_LATEST_VERSION] is None


async def test_firmware_update_latest_version_even_if_downgrade(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA update platform - `latest_version` always reflects the latest."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    fw_image_downgrade = create_fw_image(installed_fw_version - 10)

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(),
            downgrades=(fw_image_downgrade,),
        )
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    # simulate an image available notification
    await ota_cluster._handle_query_next_image(
        foundation.ZCLHeader.cluster(
            tsn=0x12, command_id=general.Ota.ServerCommandDefs.query_next_image.id
        ),
        general.QueryNextImageCommand(
            field_control=fw_image.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image.firmware.header.image_type,
            current_file_version=installed_fw_version,
            hardware_version=1,
        ),
    )

    await zha_gateway.async_block_till_done()
    assert entity.state[ATTR_INSTALLED_VERSION] == f"0x{installed_fw_version:08x}"
    assert not entity.state[ATTR_IN_PROGRESS]
    assert (
        entity.state[ATTR_LATEST_VERSION]
        == f"0x{fw_image_downgrade.firmware.header.file_version:08x}"
    )
