"""Test zha alarm control panel."""

from collections.abc import Awaitable, Callable
import logging
from unittest.mock import AsyncMock, call, patch, sentinel

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters import security
import zigpy.zcl.foundation as zcl_f

from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application.gateway import Gateway
from zha.application.platforms.alarm_control_panel import AlarmControlPanel
from zha.application.platforms.alarm_control_panel.const import AlarmState
from zha.zigbee.device import Device

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def zigpy_device(zigpy_device_mock: Callable[..., ZigpyDevice]) -> ZigpyDevice:
    """Device tracker zigpy device."""
    endpoints = {
        1: {
            SIG_EP_INPUT: [security.IasAce.cluster_id],
            SIG_EP_OUTPUT: [],
            SIG_EP_TYPE: zha.DeviceType.IAS_ANCILLARY_CONTROL,
            SIG_EP_PROFILE: zha.PROFILE_ID,
        }
    }
    return zigpy_device_mock(
        endpoints, node_descriptor=b"\x02@\x8c\x02\x10RR\x00\x00\x00R\x00\x00"
    )


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test zhaws alarm control panel platform."""
    zha_device: Device = await device_joined(zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints.get(1).ias_ace
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        "00:0d:6f:00:0a:90:69:e7-1"
    )
    assert alarm_entity is not None
    assert isinstance(alarm_entity, AlarmControlPanel)

    # test that the state is STATE_ALARM_DISARMED
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    # arm_away
    cluster.client_command.reset_mock()
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert cluster.client_command.call_count == 2
    assert cluster.client_command.await_count == 2
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.Armed_Away,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.No_Alarm,
    )
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    # disarm
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # trip alarm from faulty code entry. First we need to arm away
    cluster.client_command.reset_mock()
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY
    cluster.client_command.reset_mock()

    # now simulate a faulty code entry sequence
    await alarm_entity.async_alarm_disarm("0000")
    await alarm_entity.async_alarm_disarm("0000")
    await alarm_entity.async_alarm_disarm("0000")
    await zha_gateway.async_block_till_done()

    assert alarm_entity.state["state"] == AlarmState.TRIGGERED
    assert cluster.client_command.call_count == 6
    assert cluster.client_command.await_count == 6
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.In_Alarm,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.Emergency,
    )

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # arm_home
    await alarm_entity.async_alarm_arm_home("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_HOME
    assert cluster.client_command.call_count == 2
    assert cluster.client_command.await_count == 2
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.Armed_Stay,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.No_Alarm,
    )

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # arm_night
    await alarm_entity.async_alarm_arm_night("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_NIGHT
    assert cluster.client_command.call_count == 2
    assert cluster.client_command.await_count == 2
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.Armed_Night,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.No_Alarm,
    )

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # arm from panel
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Arm_All_Zones, "", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # arm day home only from panel
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Arm_Day_Home_Only, "", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_HOME

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # arm night sleep only from panel
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Arm_Night_Sleep_Only, "", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_NIGHT

    # disarm from panel with bad code
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_NIGHT

    # disarm from panel with bad code for 2nd time still armed
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED

    # disarm from panel with good code
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "4321", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    # disarm when already disarmed
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "4321", 0]
    )
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED
    assert "IAS ACE already disarmed" in caplog.text

    # panic from panel
    cluster.listener_event("cluster_command", 1, 4, [])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # fire from panel
    cluster.listener_event("cluster_command", 1, 3, [])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)

    # emergency from panel
    cluster.listener_event("cluster_command", 1, 2, [])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    await alarm_entity.async_alarm_trigger()
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED

    # reset the panel
    await reset_alarm_panel(zha_gateway, cluster, alarm_entity)
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    alarm_entity._cluster_handler.code_required_arm_actions = True
    await alarm_entity.async_alarm_arm_away()
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED
    assert "Invalid code supplied to IAS ACE" in caplog.text


async def reset_alarm_panel(
    zha_gateway: Gateway,
    cluster: security.IasAce,
    entity: AlarmControlPanel,
) -> None:
    """Reset the state of the alarm panel."""
    cluster.client_command.reset_mock()
    await entity.async_alarm_disarm("4321")
    await zha_gateway.async_block_till_done()
    assert entity.state["state"] == AlarmState.DISARMED
    assert cluster.client_command.call_count == 2
    assert cluster.client_command.await_count == 2
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.Panel_Disarmed,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.No_Alarm,
    )
    cluster.client_command.reset_mock()
