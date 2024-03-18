"""Common test objects."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Any, Optional
from unittest.mock import AsyncMock, Mock

from slugify import slugify
import zigpy.types as t
import zigpy.zcl
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.gateway import ZHAGateway
from zha.application.platforms import PlatformEntity
from zha.zigbee.device import ZHADevice
from zha.zigbee.group import Group

_LOGGER = logging.getLogger(__name__)


def patch_cluster(cluster: zigpy.zcl.Cluster) -> None:
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
    cluster.deserialize = Mock()
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
    zha_gateway: ZHAGateway, cluster: zigpy.zcl.Cluster, attributes: dict
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


def find_entity(device: ZHADevice, platform: Platform) -> Optional[PlatformEntity]:
    """Find an entity for the specified platform on the given device."""
    for entity in device.platform_entities.values():
        if platform == entity.PLATFORM:
            return entity
    return None


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


def find_entity_id(
    domain: str, zha_device: ZHADevice, qualifier: Optional[str] = None
) -> Optional[str]:
    """Find the entity id under the testing.

    This is used to get the entity id in order to get the state from the state
    machine so that we can test state changes.
    """
    entities = find_entity_ids(domain, zha_device)
    if not entities:
        return None
    if qualifier:
        for entity_id in entities:
            if qualifier in entity_id:
                return entity_id
        return None
    else:
        return entities[0]


def find_entity_ids(
    domain: str, zha_device: ZHADevice, omit: Optional[list[str]] = None
) -> list[str]:
    """Find the entity ids under the testing.

    This is used to get the entity id in order to get the state from the state
    machine so that we can test state changes.
    """
    ieeetail = "".join([f"{o:02x}" for o in zha_device.ieee[:4]])
    head = f"{domain}.{slugify(f'{zha_device.name} {ieeetail}', separator='_')}"

    entity_ids = [
        f"{entity.PLATFORM}.{slugify(entity.name, separator='_')}"
        for entity in zha_device.platform_entities.values()
    ]

    matches = []
    res = []
    for entity_id in entity_ids:
        if entity_id.startswith(head):
            matches.append(entity_id)

    if omit:
        for entity_id in matches:
            skip = False
            for o in omit:
                if o in entity_id:
                    skip = True
                    break
            if not skip:
                res.append(entity_id)
    else:
        res = matches
    return res


def async_find_group_entity_id(domain: str, group: Group) -> Optional[str]:
    """Find the group entity id under test."""
    entity_id = f"{domain}.{group.name.lower().replace(' ','_')}_0x{group.group_id:04x}"

    entity_ids = [
        f"{entity.PLATFORM}.{slugify(entity.name, separator='_')}"
        for entity in group.group_entities.values()
    ]

    if entity_id in entity_ids:
        return entity_id
    return None
