"""Test zha switch."""

import asyncio
import logging
from unittest.mock import call, patch

import pytest
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zigpy.exceptions import ZigbeeException
from zigpy.profiles import zha
from zigpy.quirks import _DEVICE_REGISTRY, CustomCluster, CustomDevice
from zigpy.quirks.v2 import CustomDeviceV2, QuirkBuilder
import zigpy.types as t
from zigpy.zcl.clusters import closures, general
from zigpy.zcl.clusters.manufacturer_specific import ManufacturerSpecificCluster
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    get_group_entity,
    group_entity_availability_test,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import GroupEntity, PlatformEntity
from zha.exceptions import ZHAException
from zha.zigbee.device import Device
from zha.zigbee.group import Group, GroupMemberReference

ON = 1
OFF = 0
IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"
_LOGGER = logging.getLogger(__name__)


ZIGPY_DEVICE = {
    1: {
        SIG_EP_INPUT: [general.Basic.cluster_id, general.OnOff.cluster_id],
        SIG_EP_OUTPUT: [],
        SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
        SIG_EP_PROFILE: zha.PROFILE_ID,
    }
}


ZIGPY_COVER_DEVICE = {
    1: {
        SIG_EP_PROFILE: zha.PROFILE_ID,
        SIG_EP_TYPE: zha.DeviceType.WINDOW_COVERING_DEVICE,
        SIG_EP_INPUT: [
            general.Basic.cluster_id,
            closures.WindowCovering.cluster_id,
        ],
        SIG_EP_OUTPUT: [],
    }
}


async def device_switch_1_mock(zha_gateway: Gateway) -> Device:
    """Test zha switch platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE,
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)
    return zha_device


async def device_switch_2_mock(zha_gateway: Gateway) -> Device:
    """Test zha switch platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.OnOff.cluster_id, general.Groups.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)
    return zha_device


async def test_switch(zha_gateway: Gateway) -> None:
    """Test zha switch platform."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE)
    zigpy_device.node_desc.mac_capability_flags |= (
        0b_0000_0100  # this one is mains powered
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster = zigpy_device.endpoints.get(1).on_off
    entity: PlatformEntity = get_entity(zha_device, Platform.SWITCH)

    assert bool(bool(entity.state["state"])) is False

    # turn on at switch
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert bool(entity.state["state"]) is True

    # turn off at switch
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert bool(entity.state["state"]) is False

    # turn on from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert bool(entity.state["state"]) is True
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            ON,
            cluster.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # Fail turn off from client
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x01, zcl_f.Status.FAILURE],
        ),
        pytest.raises(ZHAException, match="Failed to turn off"),
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert bool(entity.state["state"]) is True
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            OFF,
            cluster.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # turn off from client
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x01, zcl_f.Status.SUCCESS],
    ):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert bool(entity.state["state"]) is False
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            OFF,
            cluster.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # Fail turn on from client
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=[0x01, zcl_f.Status.FAILURE],
        ),
        pytest.raises(ZHAException, match="Failed to turn on"),
    ):
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert bool(entity.state["state"]) is False
        assert len(cluster.request.mock_calls) == 1
        assert cluster.request.call_args == call(
            False,
            ON,
            cluster.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )

    # test updating entity state from client
    cluster.read_attributes.reset_mock()
    assert bool(entity.state["state"]) is False
    cluster.PLUGGED_ATTR_READS = {"on_off": True}
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["on_off"], allow_cache=False, only_cache=False, manufacturer=None
    )
    assert bool(entity.state["state"]) is True


async def test_zha_group_switch_entity(zha_gateway: Gateway) -> None:
    """Test the switch entity for a ZHA group."""
    device_switch_1 = await device_switch_1_mock(zha_gateway)
    device_switch_2 = await device_switch_2_mock(zha_gateway)
    member_ieee_addresses = [device_switch_1.ieee, device_switch_2.ieee]
    members = [
        GroupMemberReference(ieee=device_switch_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_switch_2.ieee, endpoint_id=1),
    ]

    # test creating a group with 2 members
    zha_group: Group = await zha_gateway.async_create_zigpy_group("Test Group", members)
    await zha_gateway.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 2
    for member in zha_group.members:
        assert member.device.ieee in member_ieee_addresses
        assert member.group == zha_group
        assert member.endpoint is not None

    entity: GroupEntity = get_group_entity(zha_group, platform=Platform.SWITCH)
    assert entity.group_id == zha_group.group_id
    assert entity.info_object.fallback_name == zha_group.name

    group_cluster_on_off = zha_group.zigpy_group.endpoint[general.OnOff.cluster_id]
    dev1_cluster_on_off = device_switch_1.device.endpoints[1].on_off
    dev2_cluster_on_off = device_switch_2.device.endpoints[1].on_off

    # test that the lights were created and are off
    assert bool(entity.state["state"]) is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x00, zcl_f.Status.SUCCESS],
    ):
        # turn on via UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert len(group_cluster_on_off.request.mock_calls) == 1
        assert group_cluster_on_off.request.call_args == call(
            False,
            ON,
            group_cluster_on_off.commands_by_name["on"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
    assert bool(entity.state["state"]) is True

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=[0x01, zcl_f.Status.SUCCESS],
    ):
        # turn off via UI
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert len(group_cluster_on_off.request.mock_calls) == 1
        assert group_cluster_on_off.request.call_args == call(
            False,
            OFF,
            group_cluster_on_off.commands_by_name["off"].schema,
            expect_reply=True,
            manufacturer=None,
            tsn=None,
        )
    assert bool(entity.state["state"]) is False

    # test some of the group logic to make sure we key off states correctly
    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # group member updates are debounced
    assert bool(entity.state["state"]) is False
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()

    # test that group light is on
    assert bool(entity.state["state"]) is True

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # test that group light is still on
    assert bool(entity.state["state"]) is True

    await send_attributes_report(zha_gateway, dev2_cluster_on_off, {0: 0})
    await zha_gateway.async_block_till_done()

    # group member updates are debounced
    assert bool(entity.state["state"]) is True
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()

    # test that group light is now off
    assert bool(entity.state["state"]) is False

    await send_attributes_report(zha_gateway, dev1_cluster_on_off, {0: 1})
    await zha_gateway.async_block_till_done()

    # group member updates are debounced
    assert bool(entity.state["state"]) is False
    await asyncio.sleep(1)
    await zha_gateway.async_block_till_done()

    # test that group light is now back on
    assert bool(entity.state["state"]) is True

    await group_entity_availability_test(
        zha_gateway, device_switch_1, device_switch_2, entity
    )


class WindowDetectionFunctionQuirk(CustomDevice):
    """Quirk with window detection function attribute."""

    class TuyaManufCluster(CustomCluster, ManufacturerSpecificCluster):
        """Tuya manufacturer specific cluster."""

        cluster_id = 0xEF00
        ep_attribute = "tuya_manufacturer"

        attributes = {
            0xEF01: ("window_detection_function", t.Bool),
            0xEF02: ("window_detection_function_inverter", t.Bool),
        }

        def __init__(self, *args, **kwargs):
            """Initialize with task."""
            super().__init__(*args, **kwargs)
            self._attr_cache.update(
                {0xEF01: False}
            )  # entity won't be created without this

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


async def test_switch_configurable(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA configurable switch platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="_TZE200_b6wax7g0",
        quirk=WindowDetectionFunctionQuirk,
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_dev)

    cluster = zigpy_dev.endpoints[1].tuya_manufacturer
    entity = get_entity(zha_device, platform=Platform.SWITCH)

    # test that the state has changed from unavailable to off
    assert bool(entity.state["state"]) is False

    # turn on at switch
    await send_attributes_report(
        zha_gateway, cluster, {"window_detection_function": True}
    )
    assert bool(entity.state["state"]) is True

    # turn off at switch
    await send_attributes_report(
        zha_gateway, cluster, {"window_detection_function": False}
    )
    assert bool(entity.state["state"]) is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.Status.SUCCESS, zcl_f.Status.SUCCESS],
    ):
        # turn on via UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": True}, manufacturer=None)
        ]

    cluster.write_attributes.reset_mock()

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.Status.SUCCESS, zcl_f.Status.SUCCESS],
    ):
        # turn off via UI
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": False}, manufacturer=None)
        ]

    cluster.read_attributes.reset_mock()
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    # the mocking doesn't update the attr cache so this flips back to initial value
    assert cluster.read_attributes.call_count == 1
    assert [
        call(
            [
                "window_detection_function",
                "window_detection_function_inverter",
            ],
            allow_cache=False,
            only_cache=False,
            manufacturer=None,
        )
    ] == cluster.read_attributes.call_args_list

    cluster.write_attributes.reset_mock()
    cluster.write_attributes.side_effect = ZigbeeException

    with pytest.raises(ZHAException):
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()

    assert cluster.write_attributes.mock_calls == [
        call({"window_detection_function": False}, manufacturer=None),
        call({"window_detection_function": False}, manufacturer=None),
        call({"window_detection_function": False}, manufacturer=None),
    ]

    cluster.write_attributes.side_effect = None

    # test inverter
    cluster.write_attributes.reset_mock()
    cluster._attr_cache.update({0xEF02: True})

    await entity.async_turn_off()
    await zha_gateway.async_block_till_done()
    assert cluster.write_attributes.mock_calls == [
        call({"window_detection_function": True}, manufacturer=None)
    ]

    cluster.write_attributes.reset_mock()
    await entity.async_turn_on()
    await zha_gateway.async_block_till_done()
    assert cluster.write_attributes.mock_calls == [
        call({"window_detection_function": False}, manufacturer=None)
    ]


async def test_switch_configurable_custom_on_off_values(zha_gateway: Gateway) -> None:
    """Test ZHA configurable switch platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="manufacturer",
        model="model",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .adds(WindowDetectionFunctionQuirk.TuyaManufCluster)
        .switch(
            "window_detection_function",
            WindowDetectionFunctionQuirk.TuyaManufCluster.cluster_id,
            on_value=3,
            off_value=5,
            translation_key="window_detection_function",
            fallback_name="Window detection function",
        )
        .add_to_registry()
    )

    zigpy_device_ = _DEVICE_REGISTRY.get_device(zigpy_dev)

    assert isinstance(zigpy_device_, CustomDeviceV2)
    cluster = zigpy_device_.endpoints[1].tuya_manufacturer
    cluster.PLUGGED_ATTR_READS = {"window_detection_function": 5}
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)

    entity = get_entity(zha_device, platform=Platform.SWITCH)

    assert bool(entity.state["state"]) is False

    # turn on at switch
    await send_attributes_report(zha_gateway, cluster, {"window_detection_function": 3})
    assert bool(entity.state["state"]) is True

    # turn off at switch
    await send_attributes_report(zha_gateway, cluster, {"window_detection_function": 5})
    assert bool(entity.state["state"]) is False

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        # turn on via UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": 3}, manufacturer=None)
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        # turn off via UI
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": 5}, manufacturer=None)
        ]


async def test_switch_configurable_custom_on_off_values_force_inverted(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA configurable switch platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="manufacturer2",
        model="model2",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .adds(WindowDetectionFunctionQuirk.TuyaManufCluster)
        .switch(
            "window_detection_function",
            WindowDetectionFunctionQuirk.TuyaManufCluster.cluster_id,
            on_value=3,
            off_value=5,
            force_inverted=True,
            translation_key="window_detection_function",
            fallback_name="Window detection function",
        )
        .add_to_registry()
    )

    zigpy_device_ = _DEVICE_REGISTRY.get_device(zigpy_dev)

    assert isinstance(zigpy_device_, CustomDeviceV2)
    cluster = zigpy_device_.endpoints[1].tuya_manufacturer
    cluster.PLUGGED_ATTR_READS = {"window_detection_function": 5}
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)

    entity = get_entity(zha_device, platform=Platform.SWITCH)

    assert bool(entity.state["state"]) is True

    # turn on at switch
    await send_attributes_report(zha_gateway, cluster, {"window_detection_function": 3})
    assert bool(entity.state["state"]) is False

    # turn off at switch
    await send_attributes_report(zha_gateway, cluster, {"window_detection_function": 5})
    assert bool(entity.state["state"]) is True

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        # turn on via UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": 5}, manufacturer=None)
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        # turn off via UI
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": 3}, manufacturer=None)
        ]


async def test_switch_configurable_custom_on_off_values_inverter_attribute(
    zha_gateway: Gateway,
) -> None:
    """Test ZHA configurable switch platform."""

    zigpy_dev = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        manufacturer="manufacturer3",
        model="model3",
    )

    (
        QuirkBuilder(zigpy_dev.manufacturer, zigpy_dev.model)
        .adds(WindowDetectionFunctionQuirk.TuyaManufCluster)
        .switch(
            "window_detection_function",
            WindowDetectionFunctionQuirk.TuyaManufCluster.cluster_id,
            on_value=3,
            off_value=5,
            invert_attribute_name="window_detection_function_inverter",
            translation_key="window_detection_function",
            fallback_name="Window detection function",
        )
        .add_to_registry()
    )

    zigpy_device_ = _DEVICE_REGISTRY.get_device(zigpy_dev)

    assert isinstance(zigpy_device_, CustomDeviceV2)
    cluster = zigpy_device_.endpoints[1].tuya_manufacturer
    cluster.PLUGGED_ATTR_READS = {
        "window_detection_function": 5,
        "window_detection_function_inverter": t.Bool(True),
    }
    update_attribute_cache(cluster)

    zha_device = await join_zigpy_device(zha_gateway, zigpy_device_)

    entity = get_entity(zha_device, platform=Platform.SWITCH)

    assert bool(entity.state["state"]) is True

    # turn on at switch
    await send_attributes_report(zha_gateway, cluster, {"window_detection_function": 3})
    assert bool(entity.state["state"]) is False

    # turn off at switch
    await send_attributes_report(zha_gateway, cluster, {"window_detection_function": 5})
    assert bool(entity.state["state"]) is True

    # turn on from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        # turn on via UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": 5}, manufacturer=None)
        ]
        cluster.write_attributes.reset_mock()

    # turn off from HA
    with patch(
        "zigpy.zcl.Cluster.write_attributes",
        return_value=[zcl_f.WriteAttributesResponse.deserialize(b"\x00")[0]],
    ):
        # turn off via UI
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.mock_calls == [
            call({"window_detection_function": 3}, manufacturer=None)
        ]


WCAttrs = closures.WindowCovering.AttributeDefs
WCT = closures.WindowCovering.WindowCoveringType
WCCS = closures.WindowCovering.ConfigStatus
WCM = closures.WindowCovering.WindowCoveringMode


async def test_cover_inversion_switch(zha_gateway: Gateway) -> None:
    """Test ZHA cover platform."""

    # load up cover domain
    zigpy_cover_device = create_mock_zigpy_device(zha_gateway, ZIGPY_COVER_DEVICE)
    cluster = zigpy_cover_device.endpoints[1].window_covering
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_lift_percentage.name: 65,
        WCAttrs.current_position_tilt_percentage.name: 42,
        WCAttrs.window_covering_type.name: WCT.Tilt_blind_tilt_and_lift,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
        WCAttrs.window_covering_mode.name: WCM(WCM.LEDs_display_feedback),
    }
    update_attribute_cache(cluster)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_cover_device)
    assert (
        not zha_device.endpoints[1]
        .all_cluster_handlers[f"1:0x{cluster.cluster_id:04x}"]
        .inverted
    )
    assert cluster.read_attributes.call_count == 3
    assert (
        WCAttrs.current_position_lift_percentage.name
        in cluster.read_attributes.call_args[0][0]
    )
    assert (
        WCAttrs.current_position_tilt_percentage.name
        in cluster.read_attributes.call_args[0][0]
    )

    entity = get_entity(zha_device, platform=Platform.SWITCH)

    # test update
    prev_call_count = cluster.read_attributes.call_count
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.call_count == prev_call_count + 1
    assert bool(entity.state["state"]) is False

    # test to see the state remains after tilting to 0%
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 0}
    )
    assert bool(entity.state["state"]) is False

    with patch(
        "zigpy.zcl.Cluster.write_attributes", return_value=[0x1, zcl_f.Status.SUCCESS]
    ):
        cluster.PLUGGED_ATTR_READS = {
            WCAttrs.config_status.name: WCCS.Operational
            | WCCS.Open_up_commands_reversed,
        }
        # turn on from UI
        await entity.async_turn_on()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.call_count == 1
        assert cluster.write_attributes.call_args_list[0] == call(
            {
                WCAttrs.window_covering_mode.name: WCM.Motor_direction_reversed
                | WCM.LEDs_display_feedback
            },
            manufacturer=None,
        )

        assert bool(entity.state["state"]) is True

        cluster.write_attributes.reset_mock()

        # turn off from UI
        cluster.PLUGGED_ATTR_READS = {
            WCAttrs.config_status.name: WCCS.Operational,
        }
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.call_count == 1
        assert cluster.write_attributes.call_args_list[0] == call(
            {WCAttrs.window_covering_mode.name: WCM.LEDs_display_feedback},
            manufacturer=None,
        )

        assert bool(entity.state["state"]) is False

        cluster.write_attributes.reset_mock()

        # test that sending the command again does not result in a write
        await entity.async_turn_off()
        await zha_gateway.async_block_till_done()
        assert cluster.write_attributes.call_count == 0

        assert bool(entity.state["state"]) is False


async def test_cover_inversion_switch_not_created(zha_gateway: Gateway) -> None:
    """Test ZHA cover platform."""

    # load up cover domain
    zigpy_cover_device = create_mock_zigpy_device(zha_gateway, ZIGPY_COVER_DEVICE)
    cluster = zigpy_cover_device.endpoints[1].window_covering
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_lift_percentage.name: 65,
        WCAttrs.current_position_tilt_percentage.name: 42,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
    }
    update_attribute_cache(cluster)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_cover_device)

    assert cluster.read_attributes.call_count == 3
    assert (
        WCAttrs.current_position_lift_percentage.name
        in cluster.read_attributes.call_args[0][0]
    )
    assert (
        WCAttrs.current_position_tilt_percentage.name
        in cluster.read_attributes.call_args[0][0]
    )

    # entity should not be created when mode or config status aren't present
    with pytest.raises(KeyError):
        get_entity(zha_device, platform=Platform.SWITCH)
