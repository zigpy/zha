"""Common test objects."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any, Optional
from unittest.mock import AsyncMock, Mock

import zigpy.types as t
import zigpy.zcl
import zigpy.zcl.foundation as zcl_f

from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import BaseEntity, GroupEntity, PlatformEntity
from zha.zigbee.device import Device
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
