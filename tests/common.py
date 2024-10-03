"""Common test objects."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
import itertools
import json
import logging
import pathlib
import time
from typing import Any, Optional
from unittest.mock import AsyncMock, Mock

from zigpy.application import ControllerApplication
from zigpy.const import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zigpy.quirks import get_device as quirks_get_device
import zigpy.types as t
import zigpy.zcl
import zigpy.zcl.foundation as zcl_f
import zigpy.zdo.types as zdo_t

from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import BaseEntity, GroupEntity, PlatformEntity
from zha.zigbee.device import Device
from zha.zigbee.group import Group

_LOGGER = logging.getLogger(__name__)


def patch_cluster_for_testing(cluster: zigpy.zcl.Cluster) -> None:
    """Patch a cluster for testing."""
    cluster.PLUGGED_ATTR_READS = {}

    async def _read_attribute_raw(attributes: Any, *args: Any, **kwargs: Any) -> Any:
        result = []
        for attr_id in attributes:
            value = cluster.PLUGGED_ATTR_READS.get(attr_id)
            if value is None:
                # try converting attr_id to attr_name and lookup the plugs again
                attr = cluster.attributes.get(attr_id)
                if attr is not None:
                    value = cluster.PLUGGED_ATTR_READS.get(attr.name)
            if value is not None:
                result.append(
                    zcl_f.ReadAttributeRecord(
                        attr_id,
                        zcl_f.Status.SUCCESS,
                        zcl_f.TypeValue(type=None, value=value),
                    )
                )
            else:
                result.append(zcl_f.ReadAttributeRecord(attr_id, zcl_f.Status.FAILURE))
        return (result,)

    cluster.bind = AsyncMock(return_value=[0])
    cluster.configure_reporting = AsyncMock(
        return_value=[
            [zcl_f.ConfigureReportingResponseRecord(zcl_f.Status.SUCCESS, 0x00, 0xAABB)]
        ]
    )
    cluster.configure_reporting_multiple = AsyncMock(
        return_value=zcl_f.ConfigureReportingResponse.deserialize(b"\x00")[0]
    )
    cluster.handle_cluster_request = Mock()
    cluster.read_attributes = AsyncMock(wraps=cluster.read_attributes)
    cluster.read_attributes_raw = AsyncMock(side_effect=_read_attribute_raw)
    cluster.unbind = AsyncMock(return_value=[0])
    cluster.write_attributes = AsyncMock(wraps=cluster.write_attributes)
    cluster._write_attributes = AsyncMock(
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]]
    )
    if cluster.cluster_id == 4:
        cluster.add = AsyncMock(return_value=[0])
    if cluster.cluster_id == 0x1000:
        get_group_identifiers_rsp = (
            zigpy.zcl.clusters.lightlink.LightLink.commands_by_name[
                "get_group_identifiers_rsp"
            ].schema
        )
        cluster.get_group_identifiers = AsyncMock(
            return_value=get_group_identifiers_rsp(
                total=0, start_index=0, group_info_records=[]
            )
        )
    if cluster.cluster_id == 0xFC45:
        cluster.attributes = {
            # Relative Humidity Measurement Information
            0x0000: zcl_f.ZCLAttributeDef(
                id=0x0000, name="measured_value", type=t.uint16_t
            )
        }
        cluster.attributes_by_name = {
            "measured_value": zcl_f.ZCLAttributeDef(
                id=0x0000, name="measured_value", type=t.uint16_t
            )
        }


def update_attribute_cache(cluster: zigpy.zcl.Cluster) -> None:
    """Update attribute cache based on plugged attributes."""
    if not cluster.PLUGGED_ATTR_READS:
        return

    attrs = []
    for attrid, value in cluster.PLUGGED_ATTR_READS.items():
        if isinstance(attrid, str):
            attrid = cluster.attributes_by_name[attrid].id
        else:
            attrid = zigpy.types.uint16_t(attrid)
        attrs.append(make_attribute(attrid, value))

    hdr = make_zcl_header(zcl_f.GeneralCommand.Report_Attributes)
    hdr.frame_control.disable_default_response = True
    msg = zcl_f.GENERAL_COMMANDS[zcl_f.GeneralCommand.Report_Attributes].schema(
        attribute_reports=attrs
    )
    cluster.handle_message(hdr, msg)


def make_attribute(attrid: int, value: Any, status: int = 0) -> zcl_f.Attribute:
    """Make an attribute."""
    attr = zcl_f.Attribute()
    attr.attrid = attrid
    attr.value = zcl_f.TypeValue()
    attr.value.value = value
    return attr


async def send_attributes_report(
    zha_gateway: Gateway, cluster: zigpy.zcl.Cluster, attributes: dict
) -> None:
    """Cause the sensor to receive an attribute report from the network.

    This is to simulate the normal device communication that happens when a
    device is paired to the zigbee network.
    """
    attrs = []

    for attrid, value in attributes.items():
        if isinstance(attrid, str):
            attrid = cluster.attributes_by_name[attrid].id
        else:
            attrid = zigpy.types.uint16_t(attrid)

        attrs.append(make_attribute(attrid, value))

    msg = zcl_f.GENERAL_COMMANDS[zcl_f.GeneralCommand.Report_Attributes].schema(
        attribute_reports=attrs
    )

    hdr = make_zcl_header(zcl_f.GeneralCommand.Report_Attributes)
    hdr.frame_control.disable_default_response = True
    cluster.handle_message(hdr, msg)
    await zha_gateway.async_block_till_done()


def make_zcl_header(
    command_id: int, global_command: bool = True, tsn: int = 1
) -> zcl_f.ZCLHeader:
    """Cluster.handle_message() ZCL Header helper."""
    if global_command:
        frc = zcl_f.FrameControl(zcl_f.FrameType.GLOBAL_COMMAND)
    else:
        frc = zcl_f.FrameControl(zcl_f.FrameType.CLUSTER_COMMAND)
    return zcl_f.ZCLHeader(frc, tsn=tsn, command_id=command_id)


def reset_clusters(clusters: list[zigpy.zcl.Cluster]) -> None:
    """Reset mocks on cluster."""
    for cluster in clusters:
        cluster.bind.reset_mock()
        cluster.configure_reporting.reset_mock()
        cluster.configure_reporting_multiple.reset_mock()
        cluster.write_attributes.reset_mock()


def find_entity(device: Device, platform: Platform) -> PlatformEntity:
    """Find an entity for the specified platform on the given device."""
    for entity in device.platform_entities.values():
        if platform == entity.PLATFORM:
            return entity

    raise KeyError(
        f"No entity found for platform {platform!r} on device {device}: {device.platform_entities}"
    )


def mock_coro(
    return_value: Any = None, exception: Optional[Exception] = None
) -> Awaitable:
    """Return a coro that returns a value or raise an exception."""
    fut: asyncio.Future = asyncio.Future()
    if exception is not None:
        fut.set_exception(exception)
    else:
        fut.set_result(return_value)
    return fut


def get_group_entity(
    group: Group,
    platform: Platform,
    entity_type: type[BaseEntity] = BaseEntity,
    qualifier: str | None = None,
) -> GroupEntity:
    """Get the first entity of the specified platform on the given group."""
    for entity in group.group_entities.values():
        if platform != entity.PLATFORM:
            continue

        if not isinstance(entity, entity_type):
            continue

        if qualifier is not None and qualifier not in entity.info_object.unique_id:
            continue

        return entity

    raise KeyError(
        f"No {entity_type} entity found for platform {platform!r} on group {group}: {group.group_entities}"
    )


def get_entity(
    device: Device,
    platform: Platform,
    entity_type: type[BaseEntity] = BaseEntity,
    exact_entity_type: type[BaseEntity] | None = None,
    qualifier: str | None = None,
    qualifier_func: Callable[[BaseEntity], bool] = lambda e: True,
) -> PlatformEntity:
    """Get the first entity of the specified platform on the given device."""
    for entity in device.platform_entities.values():
        if platform != entity.PLATFORM:
            continue

        if not isinstance(entity, entity_type):
            continue

        if exact_entity_type is not None and type(entity) is not exact_entity_type:
            continue

        if qualifier is not None and qualifier not in entity.info_object.unique_id:
            continue

        if not qualifier_func(entity):
            continue

        return entity

    raise KeyError(
        f"No {entity_type} entity found for platform {platform!r} on device {device}: {device.platform_entities}"
    )


async def group_entity_availability_test(
    zha_gateway: Gateway, device_1: Device, device_2: Device, entity: GroupEntity
):
    """Test group entity availability handling."""

    assert entity.state["available"] is True

    device_1.on_network = False
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()
    assert entity.state["available"] is True

    device_2.on_network = False
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()

    assert entity.state["available"] is False

    device_1.on_network = True
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()
    assert entity.state["available"] is True

    device_2.on_network = True
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()

    assert entity.state["available"] is True

    device_1.available = False
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()
    assert entity.state["available"] is True

    device_2.available = False
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()

    assert entity.state["available"] is False

    device_1.available = True
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()
    assert entity.state["available"] is True

    device_2.available = True
    await asyncio.sleep(0.1)
    await zha_gateway.async_block_till_done()

    assert entity.state["available"] is True


def zigpy_device_from_device_data(
    app: ControllerApplication,
    device_data: dict,
    patch_cluster: bool = True,
    quirk: Optional[Callable] = None,
) -> zigpy.device.Device:
    """Make a fake device using the specified cluster classes."""
    ieee = zigpy.types.EUI64.convert(device_data["ieee"])
    nwk = device_data["nwk"]
    manufacturer = device_data["manufacturer"]
    model = device_data["model"]
    node_descriptor = device_data["signature"]["node_descriptor"]
    endpoints = device_data["signature"]["endpoints"]
    cluster_data = device_data["cluster_details"]

    device = zigpy.device.Device(app, ieee, nwk)
    device.manufacturer = manufacturer
    device.model = model

    node_desc = zdo_t.NodeDescriptor(
        logical_type=node_descriptor["logical_type"],
        complex_descriptor_available=node_descriptor["complex_descriptor_available"],
        user_descriptor_available=node_descriptor["user_descriptor_available"],
        reserved=node_descriptor["reserved"],
        aps_flags=node_descriptor["aps_flags"],
        frequency_band=node_descriptor["frequency_band"],
        mac_capability_flags=node_descriptor["mac_capability_flags"],
        manufacturer_code=node_descriptor["manufacturer_code"],
        maximum_buffer_size=node_descriptor["maximum_buffer_size"],
        maximum_incoming_transfer_size=node_descriptor[
            "maximum_incoming_transfer_size"
        ],
        server_mask=node_descriptor["server_mask"],
        maximum_outgoing_transfer_size=node_descriptor[
            "maximum_outgoing_transfer_size"
        ],
        descriptor_capability_field=node_descriptor["descriptor_capability_field"],
    )
    device.node_desc = node_desc
    device.last_seen = time.time()

    orig_endpoints = (
        device_data["original_signature"]["endpoints"]
        if "original_signature" in device_data
        else endpoints
    )
    for epid, ep in orig_endpoints.items():
        endpoint = device.add_endpoint(int(epid))
        profile = None
        with suppress(Exception):
            profile = zigpy.profiles.PROFILES[int(ep["profile_id"], 16)]

        endpoint.device_type = (
            profile.DeviceType(int(ep["device_type"], 16))
            if profile
            else int(ep["device_type"], 16)
        )
        endpoint.profile_id = (
            profile.PROFILE_ID if profile else int(ep["profile_id"], 16)
        )
        endpoint.request = AsyncMock(return_value=[0])

        for cluster_id in ep["input_clusters"]:
            endpoint.add_input_cluster(int(cluster_id, 16))

        for cluster_id in ep["output_clusters"]:
            endpoint.add_output_cluster(int(cluster_id, 16))

    if quirk:
        device = quirk(app, device.ieee, device.nwk, device)
    else:
        device = quirks_get_device(device)

    for epid, ep in cluster_data.items():
        endpoint.request = AsyncMock(return_value=[0])
        for cluster_id, cluster in ep["in_clusters"].items():
            real_cluster = device.endpoints[int(epid)].in_clusters[int(cluster_id, 16)]
            if patch_cluster:
                patch_cluster_for_testing(real_cluster)
            for attr_id, attr in cluster["attributes"].items():
                if (
                    attr["value"] is None
                    or attr_id in cluster["unsupported_attributes"]
                ):
                    continue
                real_cluster._attr_cache[int(attr_id, 16)] = attr["value"]
                real_cluster.PLUGGED_ATTR_READS[int(attr_id, 16)] = attr["value"]
            for unsupported_attr in cluster["unsupported_attributes"]:
                if isinstance(unsupported_attr, str) and unsupported_attr.startswith(
                    "0x"
                ):
                    attrid = int(unsupported_attr, 16)
                    real_cluster.unsupported_attributes.add(attrid)
                    if attrid in real_cluster.attributes:
                        real_cluster.unsupported_attributes.add(
                            real_cluster.attributes[attrid].name
                        )
                else:
                    real_cluster.unsupported_attributes.add(unsupported_attr)

        for cluster_id, cluster in ep["out_clusters"].items():
            real_cluster = device.endpoints[int(epid)].out_clusters[int(cluster_id, 16)]
            if patch_cluster:
                patch_cluster_for_testing(real_cluster)
            for attr_id, attr in cluster["attributes"].items():
                if (
                    attr["value"] is None
                    or attr_id in cluster["unsupported_attributes"]
                ):
                    continue
                real_cluster._attr_cache[int(attr_id, 16)] = attr["value"]
                real_cluster.PLUGGED_ATTR_READS[int(attr_id, 16)] = attr["value"]
            for unsupported_attr in cluster["unsupported_attributes"]:
                if isinstance(unsupported_attr, str) and unsupported_attr.startswith(
                    "0x"
                ):
                    attrid = int(unsupported_attr, 16)
                    real_cluster.unsupported_attributes.add(attrid)
                    if attrid in real_cluster.attributes:
                        real_cluster.unsupported_attributes.add(
                            real_cluster.attributes[attrid].name
                        )
                else:
                    real_cluster.unsupported_attributes.add(unsupported_attr)

    return device


async def zigpy_device_from_json(
    app: ControllerApplication,
    json_file: str,
    patch_cluster: bool = True,
    quirk: Optional[Callable] = None,
) -> zigpy.device.Device:
    """Make a fake device using the specified cluster classes."""
    device_data = await asyncio.get_running_loop().run_in_executor(
        None, pathlib.Path(json_file).read_text
    )

    return zigpy_device_from_device_data(
        app=app,
        device_data=json.loads(device_data),
        patch_cluster=patch_cluster,
        quirk=quirk,
    )


async def join_zigpy_device(
    zha_gateway: Gateway, zigpy_dev: zigpy.device.Device
) -> Device:
    """Return a newly joined ZHA device."""

    zha_gateway.application_controller.devices[zigpy_dev.ieee] = zigpy_dev
    await zha_gateway.async_device_initialized(zigpy_dev)
    await zha_gateway.async_block_till_done()

    device = zha_gateway.get_device(zigpy_dev.ieee)
    assert device is not None
    return device


def create_mock_zigpy_device(
    zha_gateway: Gateway,
    endpoints: dict[int, dict[str, Any]],
    ieee: str = "00:0d:6f:00:0a:90:69:e7",
    manufacturer: str = "FakeManufacturer",
    model: str = "FakeModel",
    node_descriptor: zdo_t.NodeDescriptor | None = None,
    nwk: int = 0xB79C,
    patch_cluster: bool = True,
    quirk: Optional[Callable] = None,
    attributes: dict[int, dict[str, dict[str, Any]]] = None,
) -> zigpy.device.Device:
    """Make a fake device using the specified cluster classes."""
    zigpy_app_controller = zha_gateway.application_controller
    device = zigpy.device.Device(
        zigpy_app_controller, zigpy.types.EUI64.convert(ieee), nwk
    )
    device.manufacturer = manufacturer
    device.model = model

    if node_descriptor is None:
        node_descriptor = zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.EndDevice,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress,
            manufacturer_code=4151,
            maximum_buffer_size=127,
            maximum_incoming_transfer_size=100,
            server_mask=10752,
            maximum_outgoing_transfer_size=100,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        )

    device.node_desc = node_descriptor
    device.last_seen = time.time()

    for epid, ep in endpoints.items():
        endpoint = device.add_endpoint(epid)
        endpoint.device_type = ep[SIG_EP_TYPE]
        endpoint.profile_id = ep.get(SIG_EP_PROFILE)
        endpoint.request = AsyncMock(return_value=[0])

        for cluster_id in ep.get(SIG_EP_INPUT, []):
            endpoint.add_input_cluster(cluster_id)

        for cluster_id in ep.get(SIG_EP_OUTPUT, []):
            endpoint.add_output_cluster(cluster_id)

    if quirk:
        device = quirk(zigpy_app_controller, device.ieee, device.nwk, device)
    else:
        device = quirks_get_device(device)

    if patch_cluster:
        for endpoint in (ep for epid, ep in device.endpoints.items() if epid):
            endpoint.request = AsyncMock(return_value=[0])
            for cluster in itertools.chain(
                endpoint.in_clusters.values(), endpoint.out_clusters.values()
            ):
                patch_cluster_for_testing(cluster)

    if attributes is not None:
        for ep_id, clusters in attributes.items():
            for cluster_name, attrs in clusters.items():
                cluster = getattr(device.endpoints[ep_id], cluster_name)

                for name, value in attrs.items():
                    attr_id = cluster.find_attribute(name).id
                    cluster._attr_cache[attr_id] = value

    return device
