"""Test ZHA firmware updates."""

from unittest.mock import ANY, AsyncMock, PropertyMock, call, patch

import pytest
from zigpy.device import ZigbeeDevice
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


def create_fw_image(
    version: int,
    changelog: str | None = None,
    release_notes: str | None = None,
    release_url: str | None = None,
) -> OtaImageWithMetadata:
    """Create an OTA image with a specific file version."""
    return OtaImageWithMetadata(
        metadata=BaseOtaImageMetadata(
            file_version=version,
            manufacturer_id=0x1234,
            image_type=0x90,
            changelog=changelog,
            release_notes=release_notes,
            release_url=release_url,
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
    zigpy_device: ZigbeeDevice,  # pylint: disable=redefined-outer-name
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
    zigpy_device: ZigbeeDevice,
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

    # Prevent post-OTA reinterview side effects in OTA-focused tests
    zigpy_device.reinterview = AsyncMock()

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    return zha_device, ota_cluster, fw_image, installed_fw_version


async def test_firmware_update_notification_from_zigpy(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - firmware update notification."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert entity.state.latest_version is None

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
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert entity.state.in_progress is False
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
    )


@patch("zigpy.device.AFTER_OTA_ATTR_READ_DELAY", 0.01)
async def test_firmware_update_success(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - firmware update success and post-OTA reinterview."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    # Replace the reinterview mock from setup_test_data with one that
    # simulates a successful device swap via the gateway listener.
    new_zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        endpoints={
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
                SIG_EP_OUTPUT: [general.Ota.cluster_id],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=str(zigpy_device.ieee),
        manufacturer="FakeManufacturer",
        model="FakeModel",
    )

    async def fake_reinterview():
        zha_gateway.application_controller.devices[zigpy_device.ieee] = new_zigpy_device
        zha_gateway.device_reinterviewed(new_zigpy_device)

    zigpy_device.reinterview = fake_reinterview

    old_zigpy_device = zha_device.device

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
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert entity.state.in_progress is False
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
    )

    ota_completed = False

    async def endpoint_reply(cluster, sequence, data, **kwargs):
        nonlocal ota_completed
        if cluster == general.Ota.cluster_id:
            hdr, cmd = ota_cluster.deserialize(data)
            if isinstance(cmd, general.Ota.ImageNotifyCommand):
                if ota_completed:
                    # Post-OTA image_notify: ignore or don't respond
                    return

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
                # After a successful OTA, zigpy sends a post-OTA image_notify
                # which triggers a query_next_image -> NO_IMAGE_AVAILABLE exchange
                if cmd.status == foundation.Status.NO_IMAGE_AVAILABLE:
                    return

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
                        entity.state.installed_version
                        == f"0x{installed_fw_version:08x}"
                    )
                    assert entity.state.in_progress is True
                    assert entity.state.update_percentage == pytest.approx(
                        100 * (40 / 70)
                    )
                    assert (
                        entity.state.latest_version
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

                ota_completed = True

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
        entity.state.installed_version
        == f"0x{fw_image.firmware.header.file_version:08x}"
    )
    assert not entity.state.in_progress
    assert entity.state.latest_version == entity.state.installed_version

    # If we send a progress notification incorrectly, it won't be handled
    entity._update_progress(50, 100, 0.50)

    assert not entity.state.in_progress

    # Post-OTA reinterview should have swapped the zigpy device and rebuilt ZHA
    assert zha_device.device is not old_zigpy_device
    assert zha_device.status.name == "INITIALIZED"
    assert len(zha_device.platform_entities) > 0


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
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert not entity.state.in_progress
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
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
                if cmd.status == foundation.Status.NO_IMAGE_AVAILABLE:
                    return

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
            "zigpy.device.ZigbeeDevice.update_firmware",
            AsyncMock(side_effect=DeliveryError("failed to deliver")),
        ),
        pytest.raises(ZHAException),
    ):
        await entity.async_install(
            version=f"0x{fw_image.firmware.header.file_version:08x}"
        )
        await zha_gateway.async_block_till_done()


async def _offer_update(zha_gateway: Gateway):
    """Join a device and have it query for the test firmware image."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

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

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    return zha_device, entity, fw_image


WAKE_UP_HINT = (
    " If the device is battery powered, wake it up (for example by pressing a button"
    " on it) right before starting the update."
)


@pytest.mark.parametrize(
    ("result", "progress", "mains_powered", "expected"),
    [
        (
            foundation.Status.TIMEOUT,
            None,
            False,
            "The device did not start downloading the firmware." + WAKE_UP_HINT,
        ),
        (
            foundation.Status.TIMEOUT,
            None,
            True,
            "The device did not start downloading the firmware.",
        ),
        (
            foundation.Status.TIMEOUT,
            42.9,
            False,
            "The device stopped downloading the firmware at 42%.",
        ),
        (
            foundation.Status.TIMEOUT,
            100.0,
            False,
            "The whole firmware image was sent, but the device did not confirm the"
            " update.",
        ),
        (
            foundation.Status.FAILURE,
            None,
            False,
            "The update failed: a message to the device could not be delivered, or the"
            " device reported a failure." + WAKE_UP_HINT,
        ),
        (
            foundation.Status.FAILURE,
            None,
            True,
            "The update failed: a message to the device could not be delivered, or the"
            " device reported a failure.",
        ),
        (
            foundation.Status.FAILURE,
            7.0,
            False,
            "The update failed: a message to the device could not be delivered, or the"
            " device reported a failure.",
        ),
        (
            foundation.Status.NO_IMAGE_AVAILABLE,
            None,
            True,
            "The device's firmware request does not match this image. The device may"
            " already have this version or a newer one, or need a different image.",
        ),
        (
            foundation.Status.ABORT,
            50.0,
            True,
            "The device aborted the update.",
        ),
        (
            foundation.Status.INVALID_IMAGE,
            100.0,
            True,
            "The device rejected the firmware image as invalid.",
        ),
        (
            foundation.Status.MALFORMED_COMMAND,
            100.0,
            True,
            "The update ended with status MALFORMED_COMMAND (0x80).",
        ),
        (
            None,
            None,
            True,
            "A firmware update is already in progress for this device.",
        ),
    ],
)
async def test_firmware_update_result_message(
    zha_gateway: Gateway,
    result: foundation.Status | None,
    progress: float | None,
    mains_powered: bool,
    expected: str,
) -> None:
    """An unsuccessful update result is described in words, not as an enum repr."""
    zha_device, entity, fw_image = await _offer_update(zha_gateway)

    async def update_firmware(image, progress_callback):
        if progress is not None:
            progress_callback(1, 1, progress)
        return result

    with (
        patch(
            "zigpy.device.ZigbeeDevice.update_firmware",
            AsyncMock(side_effect=update_firmware),
        ),
        patch.object(
            type(zha_device),
            "is_mains_powered",
            new_callable=PropertyMock,
            return_value=mains_powered,
        ),
        pytest.raises(ZHAException) as exc_info,
    ):
        await entity.async_install(
            version=f"0x{fw_image.firmware.header.file_version:08x}"
        )

    assert str(exc_info.value) == expected
    assert not entity.state.in_progress


@pytest.mark.parametrize(
    ("exception", "progress", "mains_powered", "expected"),
    [
        (
            TimeoutError(),
            None,
            False,
            "The device did not respond." + WAKE_UP_HINT,
        ),
        (
            TimeoutError(),
            None,
            None,
            "The device did not respond." + WAKE_UP_HINT,
        ),
        (
            TimeoutError(),
            None,
            True,
            "The device did not respond.",
        ),
        (
            DeliveryError(
                "Failed to deliver message: <sl_Status.ZIGBEE_DELIVERY_FAILED: 3074>"
            ),
            None,
            True,
            "The device could not be reached.",
        ),
        (
            DeliveryError("Failed to deliver message"),
            None,
            False,
            "The device could not be reached." + WAKE_UP_HINT,
        ),
        (
            TimeoutError(),
            100.0,
            False,
            "The device reported a successful update, but its new firmware version"
            " could not be read back. It may still be restarting; check the firmware"
            " version again later.",
        ),
        (
            RuntimeError("Failed to download the firmware image: 404"),
            None,
            False,
            "Failed to download the firmware image: 404",
        ),
        (
            ValueError(),
            None,
            False,
            "ValueError()",
        ),
    ],
)
async def test_firmware_update_exception_message(
    zha_gateway: Gateway,
    exception: Exception,
    progress: float | None,
    mains_powered: bool | None,
    expected: str,
) -> None:
    """An exception from a firmware update is described in words."""
    zha_device, entity, fw_image = await _offer_update(zha_gateway)

    async def update_firmware(image, progress_callback):
        if progress is not None:
            progress_callback(1, 1, progress)
        raise exception

    with (
        patch(
            "zigpy.device.ZigbeeDevice.update_firmware",
            AsyncMock(side_effect=update_firmware),
        ),
        patch.object(
            type(zha_device),
            "is_mains_powered",
            new_callable=PropertyMock,
            return_value=mains_powered,
        ),
        pytest.raises(ZHAException) as exc_info,
    ):
        await entity.async_install(
            version=f"0x{fw_image.firmware.header.file_version:08x}"
        )

    assert str(exc_info.value) == expected
    assert exc_info.value.__cause__ is exception
    assert not entity.state.in_progress


async def test_firmware_update_read_back_fails(zha_gateway: Gateway) -> None:
    """A failed read-back after a successful transfer is not called a failed update."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )
    entity = get_entity(zha_device, platform=Platform.UPDATE)

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

    image_size = len(fw_image.firmware.serialize())
    read_back_error = TimeoutError()

    async def endpoint_reply(cluster, sequence, data, **kwargs):
        if cluster != general.Ota.cluster_id:
            return

        _, cmd = ota_cluster.deserialize(data)

        if isinstance(cmd, general.Ota.ImageNotifyCommand):
            zigpy_device.packet_received(
                make_packet(
                    zigpy_device,
                    ota_cluster,
                    general.Ota.ServerCommandDefs.query_next_image.name,
                    field_control=general.Ota.QueryNextImageCommand.FieldControl.HardwareVersion,
                    manufacturer_code=fw_image.firmware.header.manufacturer_id,
                    image_type=fw_image.firmware.header.image_type,
                    current_file_version=installed_fw_version,
                    hardware_version=1,
                )
            )
        elif isinstance(
            cmd, general.Ota.ClientCommandDefs.query_next_image_response.schema
        ):
            assert cmd.status == foundation.Status.SUCCESS
            zigpy_device.packet_received(
                make_packet(
                    zigpy_device,
                    ota_cluster,
                    general.Ota.ServerCommandDefs.image_block.name,
                    field_control=general.Ota.ImageBlockCommand.FieldControl(0),
                    manufacturer_code=fw_image.firmware.header.manufacturer_id,
                    image_type=fw_image.firmware.header.image_type,
                    file_version=fw_image.firmware.header.file_version,
                    file_offset=0,
                    maximum_data_size=image_size,
                )
            )
        elif isinstance(cmd, general.Ota.ClientCommandDefs.image_block_response.schema):
            next_offset = cmd.file_offset + len(cmd.image_data)

            if next_offset < image_size:
                zigpy_device.packet_received(
                    make_packet(
                        zigpy_device,
                        ota_cluster,
                        general.Ota.ServerCommandDefs.image_block.name,
                        field_control=general.Ota.ImageBlockCommand.FieldControl(0),
                        manufacturer_code=fw_image.firmware.header.manufacturer_id,
                        image_type=fw_image.firmware.header.image_type,
                        file_version=fw_image.firmware.header.file_version,
                        file_offset=next_offset,
                        maximum_data_size=image_size,
                    )
                )
                return

            # The device has the whole image, verifies it and reports success
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
        elif isinstance(cmd, general.Ota.ClientCommandDefs.upgrade_end_response.schema):
            # Then it restarts and does not answer the read of its new version
            ota_cluster.read_attributes.side_effect = read_back_error

    ota_cluster.endpoint.reply = AsyncMock(side_effect=endpoint_reply)

    with pytest.raises(ZHAException) as exc_info:
        await entity.async_install(version=None)

    assert str(exc_info.value) == (
        "The device reported a successful update, but its new firmware version"
        " could not be read back. It may still be restarting; check the firmware"
        " version again later."
    )
    assert exc_info.value.__cause__ is read_back_error
    assert not entity.state.in_progress


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
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert not entity.state.in_progress
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
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
        entity.state.installed_version
        == f"0x{fw_image_downgrade.firmware.header.file_version:08x}"
    )
    assert not entity.state.in_progress
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
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
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert not entity.state.in_progress
    assert entity.state.latest_version is None

    with pytest.raises(ZHAException):
        await entity.async_install(version=None)

    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert not entity.state.in_progress
    assert entity.state.latest_version is None


async def test_firmware_update_latest_version_even_if_downgrade(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA update platform - latest downgrade sets version and release URL."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, fw_image, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    fw_image_downgrade = create_fw_image(
        installed_fw_version - 10, release_url="https://example.com/releases/v0.1"
    )

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
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert not entity.state.in_progress
    assert (
        entity.state.latest_version
        == f"0x{fw_image_downgrade.firmware.header.file_version:08x}"
    )
    assert entity.state.release_url == "https://example.com/releases/v0.1"


async def test_firmware_update_metadata(zha_gateway: Gateway) -> None:
    """Test ZHA update platform - firmware metadata (changelog, release_notes, release_url)."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, _, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    # firmware image with optional metadata
    fw_image = create_fw_image(
        installed_fw_version + 10,
        changelog="This is a test changelog!",
        release_notes="These are the full release notes.",
        release_url="https://example.com/releases/v1.0",
    )

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(fw_image,),
            downgrades=(),
        )
    )

    entity = get_entity(zha_device, platform=Platform.UPDATE)

    # metadata should be None before notification
    assert entity.state.release_summary is None
    assert entity.state.release_notes is None
    assert entity.state.release_url is None

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

    # verify metadata is exposed in entity state now
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
    )
    assert entity.state.release_url == "https://example.com/releases/v1.0"
    assert entity.state.release_summary == "This is a test changelog!"

    # release notes include version header
    assert entity.state.release_notes == (
        f"## 0x{fw_image.firmware.header.file_version:08x}\n"
        "These are the full release notes."
    )


async def test_firmware_update_multiple_upgrades_combined_release_notes(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA update platform - multiple upgrades combine release notes with version headers."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    zha_device, ota_cluster, _, installed_fw_version = await setup_test_data(
        zha_gateway, zigpy_device
    )

    # Create multiple firmware images (newest to oldest)
    # Note: fw_image_v2 has no release notes and should be skipped
    fw_image_v3 = create_fw_image(
        installed_fw_version + 30,
        changelog="Latest changelog",
        release_notes="Release notes for v3.",
        release_url="https://example.com/releases/v3",
    )
    fw_image_v2 = create_fw_image(
        installed_fw_version + 20,
        release_notes=None,  # No release notes for this version
    )
    fw_image_v1 = create_fw_image(
        installed_fw_version + 10,
        release_notes="Release notes for v1.",
    )

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(fw_image_v3, fw_image_v2, fw_image_v1),
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
            field_control=fw_image_v3.firmware.header.field_control,
            manufacturer_code=zha_device.manufacturer_code,
            image_type=fw_image_v3.firmware.header.image_type,
            current_file_version=installed_fw_version,
            hardware_version=1,
        ),
    )

    await zha_gateway.async_block_till_done()

    # Verify latest version is the newest firmware
    assert (
        entity.state.latest_version
        == f"0x{fw_image_v3.firmware.header.file_version:08x}"
    )
    # Only latest firmware provides URL and release summary
    assert entity.state.release_url == "https://example.com/releases/v3"
    assert entity.state.release_summary == "Latest changelog"

    # Release notes should be combined with version headers
    # fw_image_v2 is skipped because it has no release notes
    expected_release_notes = (
        f"## 0x{fw_image_v3.firmware.header.file_version:08x}\n"
        "Release notes for v3.\n\n"
        f"## 0x{fw_image_v1.firmware.header.file_version:08x}\n"
        "Release notes for v1."
    )
    assert entity.state.release_notes == expected_release_notes


async def test_firmware_update_cached_on_startup(zha_gateway: Gateway) -> None:
    """Test that entities pick up cached OTA state from zigpy on startup."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    installed_fw_version = 0x12345678

    ota_cluster = zigpy_device.endpoints[1].out_clusters[general.Ota.cluster_id]
    ota_cluster.PLUGGED_ATTR_READS = {
        general.Ota.AttributeDefs.current_file_version.name: installed_fw_version
    }
    update_attribute_cache(ota_cluster)

    fw_image = create_fw_image(installed_fw_version + 10)

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(
            upgrades=(fw_image,),
            downgrades=(),
        )
    )

    # Pre-populate the cluster's cached query command (as if the device had
    # previously sent a query_next_image before ZHA restarted)
    ota_cluster.last_query_cmd = general.QueryNextImageCommand(
        field_control=fw_image.firmware.header.field_control,
        manufacturer_code=zigpy_device.node_desc.manufacturer_code,
        image_type=fw_image.firmware.header.image_type,
        current_file_version=installed_fw_version,
    )

    # Join the device — on_add triggers check_cluster_for_ota
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    await zha_gateway.async_block_till_done()

    entity = get_entity(zha_device, platform=Platform.UPDATE)
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert (
        entity.state.latest_version == f"0x{fw_image.firmware.header.file_version:08x}"
    )


async def test_firmware_update_no_cached_query_on_startup(
    zha_gateway: Gateway,
) -> None:
    """Test that entities don't error when there's no cached query on startup."""
    zigpy_device = zigpy_device_mock(zha_gateway)
    installed_fw_version = 0x12345678

    ota_cluster = zigpy_device.endpoints[1].out_clusters[general.Ota.cluster_id]
    ota_cluster.PLUGGED_ATTR_READS = {
        general.Ota.AttributeDefs.current_file_version.name: installed_fw_version
    }
    update_attribute_cache(ota_cluster)

    zigpy_device.application.ota.get_ota_images = AsyncMock(
        return_value=OtaImagesResult(upgrades=(), downgrades=())
    )

    # No last_query_cmd — check_cluster_for_ota should be a no-op
    assert ota_cluster.last_query_cmd is None

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    await zha_gateway.async_block_till_done()

    entity = get_entity(zha_device, platform=Platform.UPDATE)
    assert entity.state.installed_version == f"0x{installed_fw_version:08x}"
    assert entity.state.latest_version is None
    # get_ota_images should not have been called since there's no cached query
    zigpy_device.application.ota.get_ota_images.assert_not_called()
