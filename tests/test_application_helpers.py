"""Test zha application helpers."""

from typing import Any

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
import zigpy.types as t
from zigpy.zcl.clusters.general import Basic, Identify, OnOff
from zigpy.zcl.clusters.security import IasZone

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    join_zigpy_device,
)
from zha.application.gateway import Gateway
from zha.application.helpers import (
    async_is_bindable_target,
    convert_to_zcl_values,
    convert_zcl_value,
    get_matched_clusters,
)

IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"


ZIGPY_DEVICE = {
    1: {
        SIG_EP_INPUT: [Basic.cluster_id, OnOff.cluster_id],
        SIG_EP_OUTPUT: [],
        SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
        SIG_EP_PROFILE: zha.PROFILE_ID,
    }
}

ZIGPY_DEVICE_NOT_BINDABLE = {
    1: {
        SIG_EP_INPUT: [Basic.cluster_id, IasZone.cluster_id],
        SIG_EP_OUTPUT: [],
        SIG_EP_TYPE: zha.DeviceType.IAS_ZONE,
        SIG_EP_PROFILE: zha.PROFILE_ID,
    }
}


REMOTE_ZIGPY_DEVICE = {
    1: {
        SIG_EP_INPUT: [Basic.cluster_id],
        SIG_EP_OUTPUT: [OnOff.cluster_id],
        SIG_EP_TYPE: zha.DeviceType.REMOTE_CONTROL,
        SIG_EP_PROFILE: zha.PROFILE_ID,
    }
}


async def test_async_is_bindable_target(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test zha if a device is a binding target for another device."""
    zigpy_device: ZigpyDevice = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE)
    zigpy_device.node_desc.mac_capability_flags |= (
        0b_0000_0100  # this one is mains powered
    )
    zigpy_device_not_bindable: ZigpyDevice = create_mock_zigpy_device(
        zha_gateway, ZIGPY_DEVICE_NOT_BINDABLE, ieee=IEEE_GROUPABLE_DEVICE2, nwk=0x2345
    )
    remote_zigpy_device: ZigpyDevice = create_mock_zigpy_device(
        zha_gateway, REMOTE_ZIGPY_DEVICE, ieee=IEEE_GROUPABLE_DEVICE, nwk=0x1234
    )

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    not_bindable_zha_device = await join_zigpy_device(
        zha_gateway, zigpy_device_not_bindable
    )
    remote_zha_device = await join_zigpy_device(zha_gateway, remote_zigpy_device)

    assert async_is_bindable_target(remote_zha_device, zha_device)

    assert not async_is_bindable_target(not_bindable_zha_device, remote_zha_device)


async def test_get_matched_clusters(
    zha_gateway: Gateway,  # pylint: disable=unused-argument
) -> None:
    """Test getting matched clusters for 2 zha devices."""
    zigpy_device: ZigpyDevice = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE)
    zigpy_device.node_desc.mac_capability_flags |= (
        0b_0000_0100  # this one is mains powered
    )
    zigpy_device_not_bindable: ZigpyDevice = create_mock_zigpy_device(
        zha_gateway, ZIGPY_DEVICE_NOT_BINDABLE, ieee=IEEE_GROUPABLE_DEVICE2, nwk=0x2345
    )
    remote_zigpy_device: ZigpyDevice = create_mock_zigpy_device(
        zha_gateway, REMOTE_ZIGPY_DEVICE, ieee=IEEE_GROUPABLE_DEVICE, nwk=0x1234
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    not_bindable_zha_device = await join_zigpy_device(
        zha_gateway, zigpy_device_not_bindable
    )
    remote_zha_device = await join_zigpy_device(zha_gateway, remote_zigpy_device)

    matches = await get_matched_clusters(remote_zha_device, zha_device)
    assert len(matches) == 1
    assert (
        matches[0].source_cluster
        == remote_zha_device.device.endpoints[1].out_clusters[OnOff.cluster_id]
    )
    assert matches[0].target_ieee == zha_device.ieee
    assert matches[0].target_ep_id == 1

    assert not await get_matched_clusters(not_bindable_zha_device, remote_zha_device)


class SomeEnum(t.enum8):
    """Some enum."""

    value_1 = 0x12
    value_2 = 0x34
    value_3 = 0x56


class SomeFlag(t.bitmap8):
    """Some bitmap."""

    flag_1 = 0b00000001
    flag_2 = 0b00000010
    flag_3 = 0b00000100


@pytest.mark.parametrize(
    ("text", "field_type", "result"),
    [
        # Bytes
        (
            "b'Some data\\x00\\x01'",
            t.SerializableBytes,
            t.SerializableBytes(b"Some data\x00\x01"),
        ),
        (
            'b"Some data\\x00\\x01"',
            t.SerializableBytes,
            t.SerializableBytes(b"Some data\x00\x01"),
        ),
        (
            b"Some data\x00\x01".hex(),
            t.SerializableBytes,
            t.SerializableBytes(b"Some data\x00\x01"),
        ),
        # Enum
        ("value 1", SomeEnum, SomeEnum.value_1),
        ("value_1", SomeEnum, SomeEnum.value_1),
        ("SomeEnum.value_1", SomeEnum, SomeEnum.value_1),
        (0x12, SomeEnum, SomeEnum.value_1),
        # Flag
        ("flag 1", SomeFlag, SomeFlag.flag_1),
        ("flag_1", SomeFlag, SomeFlag.flag_1),
        ("SomeFlag.flag_1", SomeFlag, SomeFlag.flag_1),
        ("SomeFlag.flag_1|flag_2", SomeFlag, SomeFlag.flag_1 | SomeFlag.flag_2),
        (0b00000001, SomeFlag, SomeFlag.flag_1),
        ([0b00000001], SomeFlag, SomeFlag.flag_1),
        ([0b00000001, 0b00000010], SomeFlag, SomeFlag.flag_1 | SomeFlag.flag_2),
        (["flag_1", "flag_2"], SomeFlag, SomeFlag.flag_1 | SomeFlag.flag_2),
        # Int
        (0x1234, t.uint16_t, 0x1234),
        ("0x1234", t.uint16_t, 0x1234),
        ("4660", t.uint16_t, 0x1234),
        # Some fallthrough type
        (1.000, t.Single, t.Single(1.000)),
        ("1.000", t.Single, t.Single(1.000)),
    ],
)
def test_convert_zcl_value(text: Any, field_type: Any, result: Any) -> None:
    """Test converting ZCL values."""
    assert convert_zcl_value(text, field_type) == result


def test_convert_to_zcl_values() -> None:
    """Test converting ZCL values."""

    identify_schema = Identify.ServerCommandDefs.identify.schema
    assert convert_to_zcl_values(
        fields={"identify_time": "1"},
        schema=identify_schema,
    ) == {"identify_time": 1}
