"""Test zha cover."""

# pylint: disable=redefined-outer-name

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import zigpy.profiles.zha
import zigpy.types
from zigpy.zcl.clusters import closures, general
import zigpy.zcl.foundation as zcl_f

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    make_zcl_header,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.const import ATTR_COMMAND
from zha.application.gateway import Gateway
from zha.application.platforms.cover import (
    DEFAULT_MOVEMENT_TIMEOUT,
    LIFT_MOVEMENT_TIMEOUT_RANGE,
    TILT_MOVEMENT_TIMEOUT_RANGE,
)
from zha.application.platforms.cover.const import (
    ATTR_CURRENT_POSITION,
    ATTR_CURRENT_TILT_POSITION,
    WCT,
    CoverEntityFeature,
    CoverState,
)
from zha.exceptions import ZHAException
from zha.zigbee.device import Device

Default_Response = zcl_f.GENERAL_COMMANDS[zcl_f.GeneralCommand.Default_Response].schema


ZIGPY_COVER_DEVICE = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.WINDOW_COVERING_DEVICE,
        SIG_EP_INPUT: [closures.WindowCovering.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


ZIGPY_COVER_REMOTE = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.WINDOW_COVERING_CONTROLLER,
        SIG_EP_INPUT: [],
        SIG_EP_OUTPUT: [closures.WindowCovering.cluster_id],
    }
}


ZIGPY_SHADE_DEVICE = {
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


ZIGPY_KEEN_VENT = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.LEVEL_CONTROLLABLE_OUTPUT,
        SIG_EP_INPUT: [general.LevelControl.cluster_id, general.OnOff.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


WCAttrs = closures.WindowCovering.AttributeDefs
WCCmds = closures.WindowCovering.ServerCommandDefs
WCCS = closures.WindowCovering.ConfigStatus


async def device_cover_mock(
    zha_gateway: Gateway,
    current_position_lift_percentage: int | None,
    current_position_tilt_percentage: int | None,
    window_covering_type: WCT,
) -> tuple[Device, zigpy.device.Device]:
    """Return a mock zha cover device and its corresponding zipgy device."""

    zigpy_device = create_mock_zigpy_device(zha_gateway, ZIGPY_COVER_DEVICE)
    cluster = zigpy_device.endpoints[1].window_covering
    cluster.PLUGGED_ATTR_READS = {
        WCAttrs.window_covering_type.name: window_covering_type,
        WCAttrs.config_status.name: WCCS(~WCCS.Open_up_commands_reversed),
    }
    if current_position_lift_percentage is not None:
        cluster.PLUGGED_ATTR_READS[WCAttrs.current_position_lift_percentage.name] = (
            current_position_lift_percentage
        )
    if current_position_tilt_percentage is not None:
        cluster.PLUGGED_ATTR_READS[WCAttrs.current_position_tilt_percentage.name] = (
            current_position_tilt_percentage
        )
    update_attribute_cache(cluster)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    return (zha_device, zigpy_device)


async def test_cover_non_tilt_initial_state(  # pylint: disable=unused-argument
    zha_gateway: Gateway,
) -> None:
    """Test ZHA cover platform."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=0,
        current_position_tilt_percentage=0,  # to validate that this is overridden to None in the state attribute
        window_covering_type=WCT.Drapery,
    )

    cluster = zigpy_cover_device.endpoints[1].window_covering
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
    assert entity.state["state"] == CoverState.OPEN
    assert entity.state[ATTR_CURRENT_POSITION] == 100
    assert entity.state[ATTR_CURRENT_TILT_POSITION] is None
    assert entity.supported_features == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    # test update
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 100}
    )
    assert entity.state["state"] == CoverState.CLOSED
    assert entity.state[ATTR_CURRENT_POSITION] == 0


async def test_cover_non_lift_initial_state(  # pylint: disable=unused-argument
    zha_gateway: Gateway,
) -> None:
    """Test ZHA cover platform."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=0,  # to validate that this is overridden to None in the state attribute
        current_position_tilt_percentage=0,
        window_covering_type=WCT.Tilt_blind_tilt_only,
    )

    cluster = zigpy_cover_device.endpoints[1].window_covering
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
    assert entity.state["state"] == CoverState.OPEN
    assert entity.state[ATTR_CURRENT_POSITION] is None
    assert entity.state[ATTR_CURRENT_TILT_POSITION] == 100
    assert entity.supported_features == (
        CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
        | CoverEntityFeature.STOP_TILT
        | CoverEntityFeature.SET_TILT_POSITION
    )

    # test update
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 100}
    )
    assert entity.state["state"] == CoverState.CLOSED
    assert entity.state[ATTR_CURRENT_TILT_POSITION] == 0


async def test_cover(
    zha_gateway: Gateway,
) -> None:
    """Test zha cover platform."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=0,
        current_position_tilt_percentage=42,
        window_covering_type=WCT.Tilt_blind_tilt_and_lift,
    )

    cluster = zigpy_cover_device.endpoints[1].window_covering
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

    # set lift to 100% (closed) and test that the state has changed from unavailable to closed
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 100}
    )
    assert entity.state["state"] == CoverState.CLOSED

    # test that the state remains after tilting to 100% (closed)
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 100}
    )
    assert entity.state["state"] == CoverState.CLOSED

    # set lift to 0% (open) and test to see if state changes to open
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 0}
    )
    assert entity.state["state"] == CoverState.OPEN

    # test that the state remains after tilting to 0% (open)
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 0}
    )
    assert entity.state["state"] == CoverState.OPEN

    # test to see the state remains after tilting to 100% (closed)
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 100}
    )
    assert entity.state["state"] == CoverState.OPEN

    # test entity async_update read of positions from the cluster
    cluster.PLUGGED_ATTR_READS[WCAttrs.current_position_lift_percentage.name] = 0
    cluster.PLUGGED_ATTR_READS[WCAttrs.current_position_tilt_percentage.name] = 100
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == CoverState.OPEN

    # close from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x1, zcl_f.Status.SUCCESS]):
        await entity.async_close_cover()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x01
        assert cluster.request.call_args[0][2].command.name == WCCmds.down_close.name
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == CoverState.CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 100}
        )

        assert entity.state["state"] == CoverState.CLOSED

        # verify that a subsequent close command does not change the state to closing
        await entity.async_close_cover()
        assert entity.state["state"] == CoverState.CLOSED

    # tilt close from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x1, zcl_f.Status.SUCCESS]):
        # reset the tilt to 0% (open)
        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 0}
        )
        assert entity.state["state"] == CoverState.CLOSED

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

        assert entity.state["state"] == CoverState.CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 100}
        )

        assert entity.state["state"] == CoverState.CLOSED

        # verify that a subsequent close command does not change the state to closing
        await entity.async_close_cover_tilt()
        assert entity.state["state"] == CoverState.CLOSED

    # open from client
    with patch("zigpy.zcl.Cluster.request", return_value=[0x0, zcl_f.Status.SUCCESS]):
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x00
        assert cluster.request.call_args[0][2].command.name == WCCmds.up_open.name
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == CoverState.OPENING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 0}
        )

        assert entity.state["state"] == CoverState.OPEN

        # verify that a subsequent open command does not change the state to opening
        await entity.async_open_cover()
        assert entity.state["state"] == CoverState.OPEN

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

        assert entity.state["state"] == CoverState.OPENING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 0}
        )

        assert entity.state["state"] == CoverState.OPEN

        # verify that a subsequent open command does not change the state to opening
        await entity.async_open_cover_tilt()
        assert entity.state["state"] == CoverState.OPEN

    # test set position command, starting at 100 % / 0 ZCL (open) from previous lift test
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_POSITION] == 100
        await entity.async_set_cover_position(position=47)  # 53 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x05
        assert cluster.request.call_args[0][2].command.name == "go_to_lift_percentage"
        assert cluster.request.call_args[0][3] == 53
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == CoverState.CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 35}
        )

        assert entity.state[ATTR_CURRENT_POSITION] == 65
        assert entity.state["state"] == CoverState.CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 53}
        )

        assert entity.state[ATTR_CURRENT_POSITION] == 47
        assert entity.state["state"] == CoverState.OPEN

        # verify that a subsequent go_to command does not change the state to closing/opening
        await entity.async_set_cover_position(position=47)
        assert entity.state["state"] == CoverState.OPEN

        # wait for transition timeout to clear the target
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPEN

    # test set tilt position command, starting at 100 % / 0 ZCL (open) from previous tilt test
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 100
        await entity.async_set_cover_tilt_position(
            tilt_position=47
        )  # 53 when inverted for ZCL
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

        assert entity.state["state"] == CoverState.CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 35}
        )

        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 65
        assert entity.state["state"] == CoverState.CLOSING

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 53}
        )

        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 47
        assert entity.state["state"] == CoverState.OPEN

        # verify that a subsequent go_to command does not change the state to closing/opening
        await entity.async_set_cover_tilt_position(tilt_position=47)
        assert entity.state["state"] == CoverState.OPEN

        # wait for transition timeout to clear the target
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPEN

    # test interrupted movement (e.g. device button press), starting from 47 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        await entity.async_set_cover_position(position=0)  # 100 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x05
        assert cluster.request.call_args[0][2].command.name == "go_to_lift_percentage"
        assert cluster.request.call_args[0][3] == 100
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state[ATTR_CURRENT_POSITION] == 47
        assert entity.state["state"] == CoverState.CLOSING

        # simulate a device position update to set timer to the default duration rather than dynamic
        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 70}
        )

        assert entity.state[ATTR_CURRENT_POSITION] == 30
        assert entity.state["state"] == CoverState.CLOSING

        # wait the timer duration
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPEN

    # test interrupted tilt movement (e.g. device button press), starting from 47 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        await entity.async_set_cover_tilt_position(
            tilt_position=0
        )  # 100 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x08
        assert cluster.request.call_args[0][2].command.name == "go_to_tilt_percentage"
        assert cluster.request.call_args[0][3] == 100
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 47
        assert entity.state["state"] == CoverState.CLOSING

        # simulate a device position update to set timer to the default duration rather than dynamic
        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 70}
        )

        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 30
        assert entity.state["state"] == CoverState.CLOSING

        # wait the timer duration
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPEN

    # test device instigated movement (e.g. device button press), starting from 30 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_POSITION] == 30
        assert entity.state["state"] == CoverState.OPEN

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 60}
        )

        assert entity.state[ATTR_CURRENT_POSITION] == 40
        assert entity.state["state"] == CoverState.OPENING

        # wait the default timer duration
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPEN

    # test device instigated tilt movement (e.g. device button press), starting from 30 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 30
        assert entity.state["state"] == CoverState.OPEN

        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 60}
        )

        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 40
        assert entity.state["state"] == CoverState.OPENING

        # wait the default timer duration
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPEN

    # test dynamic movement timeout, starting from 40 % and moving to 90 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_POSITION] == 40
        assert entity.state["state"] == CoverState.OPEN

        await entity.async_set_cover_position(position=90)  # 10 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x05
        assert cluster.request.call_args[0][2].command.name == "go_to_lift_percentage"
        assert cluster.request.call_args[0][3] == 10
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == CoverState.OPENING

        # wait the default timer duration and verify status is still opening
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPENING

        # wait the remainder of the dynamic timeout and check if the movement timed out: (50% * 300 seconds) - default
        await asyncio.sleep(
            (50 * 0.01 * LIFT_MOVEMENT_TIMEOUT_RANGE) - DEFAULT_MOVEMENT_TIMEOUT
        )
        assert entity.state[ATTR_CURRENT_POSITION] == 40
        assert entity.state["state"] == CoverState.OPEN

    # test dynamic tilt movement timeout, starting from 40 % and moving to 90 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 40
        assert entity.state["state"] == CoverState.OPEN

        await entity.async_set_cover_tilt_position(
            tilt_position=90
        )  # 10 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x08
        assert cluster.request.call_args[0][2].command.name == "go_to_tilt_percentage"
        assert cluster.request.call_args[0][3] == 10
        assert cluster.request.call_args[1]["expect_reply"] is True

        assert entity.state["state"] == CoverState.OPENING

        # wait the default timer duration and verify status is still opening
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
        assert entity.state["state"] == CoverState.OPENING

        # wait the remainder of the dynamic timeout and check if the movement timed out: (50% * 30 seconds) - default
        await asyncio.sleep(
            (50 * 0.01 * TILT_MOVEMENT_TIMEOUT_RANGE) - DEFAULT_MOVEMENT_TIMEOUT
        )
        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 40
        assert entity.state["state"] == CoverState.OPEN

    # test concurrent movement of both axis, lift and tilt starting at 40 %
    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, zcl_f.Status.SUCCESS]):
        assert entity.state[ATTR_CURRENT_POSITION] == 40
        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 40

        await entity.async_set_cover_position(position=90)  # 10 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 1
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x05
        assert cluster.request.call_args[0][2].command.name == "go_to_lift_percentage"
        assert cluster.request.call_args[0][3] == 10
        assert cluster.request.call_args[1]["expect_reply"] is True

        # verify the cover is opening due to the lift direction
        assert entity.state["state"] == CoverState.OPENING

        await entity.async_set_cover_tilt_position(
            tilt_position=1
        )  # 99 when inverted for ZCL
        await zha_gateway.async_block_till_done()
        assert cluster.request.call_count == 2
        assert cluster.request.call_args[0][0] is False
        assert cluster.request.call_args[0][1] == 0x08
        assert cluster.request.call_args[0][2].command.name == "go_to_tilt_percentage"
        assert cluster.request.call_args[0][3] == 99
        assert cluster.request.call_args[1]["expect_reply"] is True

        # the last action's direction takes state precedence (tilt)
        assert entity.state["state"] == CoverState.CLOSING

        # report that tilt has reached its target
        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_tilt_percentage.id: 99}
        )
        assert entity.state[ATTR_CURRENT_TILT_POSITION] == 1

        # state should have reverted to opening because there is still an active lift target transition
        assert entity.state["state"] == CoverState.OPENING

        # report that lift has reached its target
        await send_attributes_report(
            zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 10}
        )
        assert entity.state[ATTR_CURRENT_POSITION] == 90

        # the state should now be open (static)
        assert entity.state["state"] == CoverState.OPEN

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


async def test_cover_failures(zha_gateway: Gateway) -> None:
    """Test ZHA cover platform failure cases."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=None,
        current_position_tilt_percentage=42,
        window_covering_type=WCT.Tilt_blind_tilt_and_lift,
    )

    cluster = zigpy_cover_device.endpoints[1].window_covering
    entity = get_entity(zha_device, platform=Platform.COVER)

    # test to see if it opens
    await send_attributes_report(
        zha_gateway, cluster, {WCAttrs.current_position_lift_percentage.id: 0}
    )

    assert entity.state["state"] == CoverState.OPEN

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
        assert entity.state["state"] == CoverState.OPEN

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
    zha_gateway: Gateway,
) -> None:
    """Test zha cover platform for shade device type."""

    zigpy_shade_device = create_mock_zigpy_device(zha_gateway, ZIGPY_SHADE_DEVICE)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_shade_device)
    cluster_on_off = zigpy_shade_device.endpoints.get(1).on_off
    cluster_level = zigpy_shade_device.endpoints.get(1).level
    entity = get_entity(zha_device, platform=Platform.COVER)

    assert entity.supported_features == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    # coverage (these are always None for now)
    assert entity.is_opening is None
    assert entity.is_closing is None
    assert entity.current_cover_tilt_position is None

    # test that the state has changed from unavailable to off
    await send_attributes_report(
        zha_gateway, cluster_on_off, {cluster_on_off.AttributeDefs.on_off.id: 0}
    )
    assert entity.state["state"] == CoverState.CLOSED

    # test to see if it opens
    await send_attributes_report(
        zha_gateway, cluster_on_off, {cluster_on_off.AttributeDefs.on_off.id: 1}
    )
    assert entity.state["state"] == CoverState.OPEN

    # test entity async_update
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == CoverState.OPEN

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
        assert entity.state["state"] == CoverState.OPEN

    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x1, zcl_f.Status.SUCCESS])
    ):
        await entity.async_close_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0000
        assert entity.state["state"] == CoverState.CLOSED

    # open from client command fails
    await send_attributes_report(zha_gateway, cluster_level, {0: 0})
    assert entity.state["state"] == CoverState.CLOSED

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
        assert entity.state["state"] == CoverState.CLOSED

    # open from client succeeds
    with patch(
        "zigpy.zcl.Cluster.request", AsyncMock(return_value=[0x0, zcl_f.Status.SUCCESS])
    ):
        await entity.async_open_cover()
        await zha_gateway.async_block_till_done()
        assert cluster_on_off.request.call_count == 1
        assert cluster_on_off.request.call_args[0][0] is False
        assert cluster_on_off.request.call_args[0][1] == 0x0001
        assert entity.state["state"] == CoverState.OPEN

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
        assert entity.state[ATTR_CURRENT_POSITION] == 0

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
        assert entity.state[ATTR_CURRENT_POSITION] == 47

    # report position change
    await send_attributes_report(zha_gateway, cluster_level, {8: 0, 0: 100, 1: 1})
    assert entity.state[ATTR_CURRENT_POSITION] == int(100 * 100 / 255)

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
    zha_gateway: Gateway,
) -> None:
    """Test keen vent."""

    zigpy_keen_vent = create_mock_zigpy_device(
        zha_gateway,
        ZIGPY_KEEN_VENT,
        manufacturer="Keen Home Inc",
        model="SV02-612-MP-1.3",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_keen_vent)
    cluster_on_off = zigpy_keen_vent.endpoints.get(1).on_off
    cluster_level = zigpy_keen_vent.endpoints.get(1).level
    entity = get_entity(zha_device, platform=Platform.COVER)

    assert entity.supported_features == (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    # coverage (these are always None for now)
    assert entity.is_opening is None
    assert entity.is_closing is None

    # test that the state has changed from unavailable to off
    await send_attributes_report(zha_gateway, cluster_on_off, {8: 0, 0: False, 1: 1})
    assert entity.state["state"] == CoverState.CLOSED

    # test entity async_update
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == CoverState.CLOSED

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
        assert entity.state["state"] == CoverState.CLOSED

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
        assert entity.state["state"] == CoverState.OPEN
        assert entity.state[ATTR_CURRENT_POSITION] == 100


async def test_cover_remote(zha_gateway: Gateway) -> None:
    """Test ZHA cover remote."""

    # create mock cover remote device
    zigpy_cover_remote = create_mock_zigpy_device(zha_gateway, ZIGPY_COVER_REMOTE)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_cover_remote)
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


@pytest.mark.parametrize(
    "current_position_lift_percentage, current_position_tilt_percentage, restore_state, interim_state, final_state",
    (
        (0, 0, CoverState.OPENING, None, CoverState.OPEN),
        (0, 0, CoverState.CLOSING, CoverState.CLOSING, CoverState.OPEN),
        (100, 100, CoverState.OPENING, CoverState.OPENING, CoverState.CLOSED),
        (100, 100, CoverState.CLOSING, None, CoverState.CLOSED),
        (0, 0, CoverState.OPEN, None, CoverState.OPEN),
        (0, 0, CoverState.CLOSED, None, CoverState.OPEN),
        (100, 100, CoverState.OPEN, None, CoverState.CLOSED),
        (100, 100, CoverState.CLOSED, None, CoverState.CLOSED),
        (0, None, CoverState.OPENING, None, CoverState.OPEN),
        (None, 0, CoverState.OPENING, None, CoverState.OPEN),
        (None, None, CoverState.OPENING, None, None),
    ),
)
async def test_cover_state_restoration(
    zha_gateway: Gateway,
    current_position_lift_percentage: int | None,
    current_position_tilt_percentage: int | None,
    restore_state: CoverState | None,
    interim_state: CoverState | None,
    final_state: CoverState | None,
) -> None:
    """Test the cover state restoration function."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage,
        current_position_tilt_percentage,
        WCT.Tilt_blind_tilt_and_lift,
    )

    current_position = (
        100 - current_position_lift_percentage
        if current_position_lift_percentage is not None
        else None
    )
    current_tilt_position = (
        100 - current_position_tilt_percentage
        if current_position_tilt_percentage is not None
        else None
    )

    entity = get_entity(zha_device, platform=Platform.COVER)
    assert entity.state["state"] == final_state
    assert entity.state[ATTR_CURRENT_POSITION] == current_position
    assert entity.state[ATTR_CURRENT_TILT_POSITION] == current_tilt_position

    entity.restore_external_state_attributes(state=restore_state)
    if interim_state:
        assert entity.state["state"] == interim_state
        await asyncio.sleep(DEFAULT_MOVEMENT_TIMEOUT)
    assert entity.state["state"] == final_state


async def test_cover_lift_timer_cancellation_on_remove(zha_gateway: Gateway) -> None:
    """Test the cover timer handle cancellation upon removal."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=0,
        current_position_tilt_percentage=0,
        window_covering_type=WCT.Tilt_blind_tilt_and_lift,
    )

    # start lift close timer
    entity = get_entity(zha_device, platform=Platform.COVER)
    with patch("zigpy.zcl.Cluster.request", return_value=[0x1, zcl_f.Status.SUCCESS]):
        await entity.async_close_cover()
        await zha_gateway.async_block_till_done()
        assert entity.state["state"] == CoverState.CLOSING

    # remove entity
    await entity.on_remove()


async def test_cover_tilt_timer_cancellation_on_remove(zha_gateway: Gateway) -> None:
    """Test the cover timer handle cancellation upon removal."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=0,
        current_position_tilt_percentage=0,
        window_covering_type=WCT.Tilt_blind_tilt_and_lift,
    )

    # start tilt close timer
    entity = get_entity(zha_device, platform=Platform.COVER)
    with patch("zigpy.zcl.Cluster.request", return_value=[0x1, zcl_f.Status.SUCCESS]):
        await entity.async_close_cover_tilt()
        await zha_gateway.async_block_till_done()
        assert entity.state["state"] == CoverState.CLOSING

    # remove entity
    await entity.on_remove()


async def test_cover_state_restore_timer_cancellation_on_remove(
    zha_gateway: Gateway,
) -> None:
    """Test the cover timer handle cancellation upon removal."""

    # create mock cover device
    zha_device, zigpy_cover_device = await device_cover_mock(
        zha_gateway,
        current_position_lift_percentage=0,
        current_position_tilt_percentage=0,
        window_covering_type=WCT.Tilt_blind_tilt_and_lift,
    )

    # start state restore timer
    entity = get_entity(zha_device, platform=Platform.COVER)
    entity.restore_external_state_attributes(state=CoverState.CLOSING)
    assert entity.state["state"] == CoverState.CLOSING

    # remove entity
    await entity.on_remove()
