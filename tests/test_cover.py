"""Test zha cover."""

# pylint: disable=redefined-outer-name

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha
import zigpy.types
from zigpy.zcl.clusters import closures, general
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    get_entity,
    make_zcl_header,
    send_attributes_report,
    update_attribute_cache,
)
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform
from zha.application.const import ATTR_COMMAND
from zha.application.gateway import Gateway
from zha.application.platforms.cover import (
    ATTR_CURRENT_POSITION,
    STATE_CLOSED,
    STATE_OPEN,
)
from zha.application.platforms.cover.const import (
    STATE_CLOSING,
    STATE_OPENING,
    CoverEntityFeature,
)
from zha.exceptions import ZHAException
from zha.zigbee.device import Device

Default_Response = zcl_f.GENERAL_COMMANDS[zcl_f.GeneralCommand.Default_Response].schema


@pytest.fixture
def zigpy_cover_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy cover device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.WINDOW_COVERING_DEVICE,
            SIG_EP_INPUT: [closures.WindowCovering.cluster_id],
            SIG_EP_OUTPUT: [],
        }
    }
    return zigpy_device_mock(endpoints)


@pytest.fixture
def zigpy_cover_remote(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy cover remote device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.WINDOW_COVERING_CONTROLLER,
            SIG_EP_INPUT: [],
            SIG_EP_OUTPUT: [closures.WindowCovering.cluster_id],
        }
    }
    return zigpy_device_mock(endpoints)


@pytest.fixture
def zigpy_shade_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy shade device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.SHADE,
            SIG_EP_INPUT: [
                closures.Shade.cluster_id,
                general.LevelControl.cluster_id,
                general.OnOff.cluster_id,
            ],
            SIG_EP_OUTPUT: [],
        }
    }
    return zigpy_device_mock(endpoints)


@pytest.fixture
def zigpy_keen_vent(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> ZigpyDevice:
    """Zigpy Keen Vent device."""

    endpoints = {
        1: {
            SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
            SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROLLABLE_OUTPUT,
            SIG_EP_INPUT: [general.LevelControl.cluster_id, general.OnOff.cluster_id],
            SIG_EP_OUTPUT: [],
        }
    }
    return zigpy_device_mock(
        endpoints, manufacturer="Keen Home Inc", model="SV02-612-MP-1.3"
    )


WCAttrs = closures.WindowCovering.AttributeDefs
WCCmds = closures.WindowCovering.ServerCommandDefs
WCT = closures.WindowCovering.WindowCoveringType
WCCS = closures.WindowCovering.ConfigStatus


async def test_cover_non_tilt_initial_state(  # pylint: disable=unused-argument
    zha_gateway: Gateway,
    device_joined,
    zigpy_cover_device,
) -> None:
    """Test ZHA cover platform."""

    # load up cover domain
    cluster = zigpy_cover_device.endpoints[1].window_covering
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_lift_percentage.name: 0,
        WCAttrs.window_covering_type.name: WCT.Drapery,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
    }
    update_attribute_cache(cluster)
    zha_device = await device_joined(zigpy_cover_device)
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

    entity = get_entity(zha_device, platform=Platform.COVER)
    state = entity.state
    assert state["state"] == STATE_OPEN
    assert state[ATTR_CURRENT_POSITION] == 100

    # test update
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_lift_percentage.name: 100,
        WCAttrs.window_covering_type.name: WCT.Drapery,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
    }
    update_attribute_cache(cluster)
    prev_call_count = cluster.read_attributes.call_count
    await entity.async_update()
    assert cluster.read_attributes.call_count == prev_call_count + 1

    assert entity.state["state"] == STATE_CLOSED
    assert entity.state[ATTR_CURRENT_POSITION] == 0


async def test_cover(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_cover_device: ZigpyDevice,
    zha_gateway: Gateway,
) -> None:
    """Test zha cover platform."""

    cluster = zigpy_cover_device.endpoints.get(1).window_covering
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_lift_percentage.name: 0,
        WCAttrs.current_position_tilt_percentage.name: 42,
        WCAttrs.window_covering_type.name: WCT.Tilt_blind_tilt_and_lift,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
    }
    update_attribute_cache(cluster)
    zha_device = await device_joined(zigpy_cover_device)

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

    entity = get_entity(zha_device, platform=Platform.COVER)
    assert entity.supported_features == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.STOP
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.STOP_TILT
        | CoverEntityFeature.SET_TILT_POSITION
    )

    # test that the state has changed from unavailable to off
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 100}
    )
    assert entity.state["state"] == STATE_CLOSED

    # test to see if it opens
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 0}
    )
    assert entity.state["state"] == STATE_OPEN

    # test that the state remains after tilting to 100%
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 100}
    )
    assert entity.state["state"] == STATE_OPEN

    # test to see the state remains after tilting to 0%
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 0}
    )
    assert entity.state["state"] == STATE_OPEN

    cluster.PLUGGED_ATTR_READS = {1: 100}
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == STATE_OPEN

    # close from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x1, zcl_f.Status.SUCCESS]):
        await entity.async_close_cover()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x01
        assert cluster.request.call_args[0][2].command.name == WCCmds.down_close.name
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == STATE_CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 100}
        )

        assert entity.state["state"] == STATE_CLOSED

    # tilt close from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x1, zcl_f.Status.SUCCESS]):
        await entity.async_close_cover_tilt()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x08
        assert (
            cluster.request.call_args[0][2].command.name
            == WCCmds.go_to_tilt_percentage.name
        )
        assert cluster.request.call_args[0][3] == 100
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == STATE_CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 100}
        )

        assert entity.state["state"] == STATE_CLOSED

    # open from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x0, zcl_f.Status.SUCCESS]):
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x00
        assert cluster.request.call_args[0][2].command.name == WCCmds.up_open.name
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == STATE_OPENING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 0}
        )

        assert entity.state["state"] == STATE_OPEN

    # open tilt from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x0, zcl_f.Status.SUCCESS]):
        await entity.async_open_cover_tilt()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x08
        assert (
            cluster.request.call_args[0][2].command.name
            == WCCmds.go_to_tilt_percentage.name
        )
        assert cluster.request.call_args[0][3] == 0
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == STATE_OPENING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 0}
        )

        assert entity.state["state"] == STATE_OPEN

    # set position UI
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        await entity.async_set_cover_position(position=47)
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x05
        assert cluster.request.call_args[0][2].command.name == "go_to_lift_percentage"
        assert cluster.request.call_args[0][3] == 53
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == STATE_CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 35}
        )

        assert entity.state["state"] == STATE_CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 53}
        )

        assert entity.state["state"] == STATE_OPEN

    # set tilt position UI
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        await entity.async_set_cover_tilt_position(tilt_position=47)
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x08
        assert (
            cluster.request.call_args[0][2].command.name
            == WCCmds.go_to_tilt_percentage.name
        )
        assert cluster.request.call_args[0][3] == 53
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == STATE_CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 35}
        )

        assert entity.state["state"] == STATE_CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 53}
        )

        assert entity.state["state"] == STATE_OPEN

    # stop from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x2, zcl_f.Status.SUCCESS]):
        await entity.async_stop_cover()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x02
        assert cluster.request.call_args[0][2].command.name == WCCmds.stop.name
        assert cluster.request.call_args[1]["expect_reply"] is True

    # stop tilt from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x2, zcl_f.Status.SUCCESS]):
        await entity.async_stop_cover_tilt()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x02
        assert cluster.request.call_args[0][2].command.name == WCCmds.stop.name
        assert cluster.request.call_args[1]["expect_reply"] is True


async def test_cover_failures(
    zha_gateway: Gateway, device_joined, zigpy_cover_device
) -> None:
    """Test ZHA cover platform failure cases."""

    # load up cover domain
    cluster = zigpy_cover_device.endpoints[1].window_covering
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.current_position_tilt_percentage.name: 42,
        WCAttrs.window_covering_type.name: WCT.Tilt_blind_tilt_and_lift,
    }
    update_attribute_cache(cluster)
    zha_device = await device_joined(zigpy_cover_device)

    entity = get_entity(zha_device, platform=Platform.COVER)

    # test to see if it opens
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 0}
    )

    assert entity.state["state"] == STATE_OPEN

    # close from UI
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.down_close.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to close cover"):
            await entity.async_close_cover()
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.down_close.id
        )
        assert entity.state["state"] == STATE_OPEN

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to close cover tilt"):
            await entity.async_close_cover_tilt()
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id
        )

    # open from UI
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.up_open.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to open cover"):
            await entity.async_open_cover()
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.up_open.id
        )

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to open cover tilt"):
            await entity.async_open_cover_tilt()
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id
        )

    # set position UI
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.go_to_lift_percentage.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to set cover position"):
            await entity.async_set_cover_position(position=47)
            await zha_gateway.async_block_till_done()

        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.go_to_lift_percentage.id
        )

    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to set cover tilt position"):
            await entity.async_set_cover_tilt_position(tilt_position=47)
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.go_to_tilt_percentage.id
        )

    # stop from UI
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.stop.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to stop cover"):
            await entity.async_stop_cover()
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.stop.id
        )

    # stop tilt from UI
    with patch(
        "zigpy.zcl.Cluster.request",
        return_value=Default_Response(
            command_id=closures.WindowCovering.ServerCommandDefs.stop.id,
            status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
        ),
    ):
        with pytest.raises(ZHAException, match=r"Failed to stop cover"):
            await entity.async_stop_cover_tilt()
            await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert (
            cluster.request.call_args[0][1]
            == closures.WindowCovering.ServerCommandDefs.stop.id
        )


async def test_shade(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_shade_device: ZigpyDevice,
    zha_gateway: Gateway,
) -> None:
    """Test zha cover platform for shade device type."""

    zha_device = await device_joined(zigpy_shade_device)
    cluster_on_off = zigpy_shade_device.endpoints.get(1).on_off
    cluster_level = zigpy_shade_device.endpoints.get(1).level
    entity = get_entity(zha_device, platform=Platform.COVER)

    assert entity.supported_features == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    # test that the state has changed from unavailable to off
    await send_attributes_report(
        zha_gateway, cluster_on_off, {cluster_on_off.AttributeDefs.on_off.id: 0}
    )
    assert entity.state["state"] == STATE_CLOSED

    # test to see if it opens
    await send_attributes_report(
        zha_gateway, cluster_on_off, {cluster_on_off.AttributeDefs.on_off.id: 1}
    )
    assert entity.state["state"] == STATE_OPEN

    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == STATE_OPEN

    # close from client command fails
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=Default_Response(
                command_id=general.OnOff.ServerCommandDefs.off.id,
                status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
            ),
        ),
        pytest.raises(ZHAException, match="Failed to close cover"),
    ):
        await entity.async_close_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0000
        assert entity.state["state"] == STATE_OPEN

    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x1, zcl_f.Status.SUCCESS])
    ):
        await entity.async_close_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0000
        assert entity.state["state"] == STATE_CLOSED

    # open from client command fails
    await send_attributes_report(zha_gateway, cluster_level, {0: 0})
    assert entity.state["state"] == STATE_CLOSED

    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=Default_Response(
                command_id=general.OnOff.ServerCommandDefs.on.id,
                status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
            ),
        ),
        pytest.raises(ZHAException, match="Failed to open cover"),
    ):
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert entity.state["state"] == STATE_CLOSED

    # open from client succeeds
    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x0, zcl_f.Status.SUCCESS])
    ):
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert entity.state["state"] == STATE_OPEN

    # set position UI command fails
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=Default_Response(
                command_id=general.LevelControl.ServerCommandDefs.move_to_level_with_on_off.id,
                status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
            ),
        ),
        pytest.raises(ZHAException, match="Failed to set cover position"),
    ):
        await entity.async_set_cover_position(position=47)
        await zha_gateway.async_block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] == 0x0004
        assert int(cluster_level.request.call_args[0][3] * 100 / 255) == 47
        assert entity.state["current_position"] == 0

    # set position UI success
    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x5, zcl_f.Status.SUCCESS])
    ):
        await entity.async_set_cover_position(position=47)
        await zha_gateway.async_block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] == 0x0004
        assert int(cluster_level.request.call_args[0][3] * 100 / 255) == 47
        assert entity.state["current_position"] == 47

    # report position change
    await send_attributes_report(zha_gateway, cluster_level, {8: 0, 0: 100, 1: 1})
    assert entity.state["current_position"] == int(100 * 100 / 255)

    # stop command fails
    with (
        patch(
            "zigpy.zcl.Cluster.request",
            return_value=Default_Response(
                command_id=general.LevelControl.ServerCommandDefs.stop.id,
                status=zcl_f.Status.UNSUP_CLUSTER_COMMAND,
            ),
        ),
        pytest.raises(ZHAException, match="Failed to stop cover"),
    ):
        await entity.async_stop_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] in (0x0003, 0x0007)

    # test cover stop
    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x0, zcl_f.Status.SUCCESS])
    ):
        await entity.async_stop_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_level.request.call_count == 1
        assert cluster_level.request.call_args[0][0] is False
        assert cluster_level.request.call_args[0][1] in (0x0003, 0x0007)


async def test_keen_vent(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_keen_vent: ZigpyDevice,
    zha_gateway: Gateway,
) -> None:
    """Test keen vent."""

    zha_device = await device_joined(zigpy_keen_vent)
    cluster_on_off = zigpy_keen_vent.endpoints.get(1).on_off
    cluster_level = zigpy_keen_vent.endpoints.get(1).level
    entity = get_entity(zha_device, platform=Platform.COVER)

    assert entity.supported_features == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    # test that the state has changed from unavailable to off
    await send_attributes_report(zha_gateway, cluster_on_off, {8: 0, 0: False, 1: 1})
    assert entity.state["state"] == STATE_CLOSED

    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == STATE_CLOSED

    # open from client command fails
    p1 = patch.object(cluster_on_off, "request", side_effect=asyncio.TimeoutError)
    p2 = patch.object(cluster_level, "request", AsyncMock(return_value=[4, 0]))
    p3 = pytest.raises(
        ZHAException, match="Failed to send request: device did not respond"
    )

    with p1, p2, p3:
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert cluster_level.request.call_count == 1
        assert entity.state["state"] == STATE_CLOSED

    # open from client command success
    p1 = patch.object(cluster_on_off, "request", AsyncMock(return_value=[1, 0]))
    p2 = patch.object(cluster_level, "request", AsyncMock(return_value=[4, 0]))

    with p1, p2:
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert cluster_level.request.call_count == 1
        assert entity.state["state"] == STATE_OPEN
        assert entity.state["current_position"] == 100


async def test_cover_remote(
    zha_gateway: Gateway, device_joined, zigpy_cover_remote
) -> None:
    """Test ZHA cover remote."""

    # load up cover domain
    zha_device = await device_joined(zigpy_cover_remote)
    zha_device.emit_zha_event = MagicMock(wraps=zha_device.emit_zha_event)

    cluster = zigpy_cover_remote.endpoints[1].out_clusters[
        closures.WindowCovering.cluster_id
    ]

    zha_device.emit_zha_event.reset_mock()

    # up command
    hdr = make_zcl_header(0, global_command=False)
    cluster.handle_message(hdr, [])
    await zha_gateway.async_block_till_done()

    assert zha_device.emit_zha_event.call_count == 1
    assert ATTR_COMMAND in zha_device.emit_zha_event.call_args[0][0]
    assert zha_device.emit_zha_event.call_args[0][0][ATTR_COMMAND] == "up_open"

    zha_device.emit_zha_event.reset_mock()

    # down command
    hdr = make_zcl_header(1, global_command=False)
    cluster.handle_message(hdr, [])
    await zha_gateway.async_block_till_done()

    assert zha_device.emit_zha_event.call_count == 1
    assert ATTR_COMMAND in zha_device.emit_zha_event.call_args[0][0]
    assert zha_device.emit_zha_event.call_args[0][0][ATTR_COMMAND] == "down_close"


async def test_cover_state_restoration(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_cover_device: ZigpyDevice,
    zha_gateway: Gateway,
) -> None:
    """Test the cover state restoration."""
    zha_device = await device_joined(zigpy_cover_device)
    entity = get_entity(zha_device, platform=Platform.COVER)

    assert entity.state["state"] != STATE_CLOSED
    assert entity.state["target_lift_position"] != 12
    assert entity.state["target_tilt_position"] != 34

    entity.restore_external_state_attributes(
        state=STATE_CLOSED,
        target_lift_position=12,
        target_tilt_position=34,
    )

    assert entity.state["state"] == STATE_CLOSED
    assert entity.state["target_lift_position"] == 12
    assert entity.state["target_tilt_position"] == 34
