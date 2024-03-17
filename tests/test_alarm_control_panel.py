"""Test zha alarm control panel."""
import logging
from typing import Awaitable, Callable, Optional
from unittest.mock import AsyncMock, call, patch, sentinel

import pytest
from zigpy.device import Device as ZigpyDevice
import zigpy.profiles.zha as zha
import zigpy.zcl.clusters.security as security
import zigpy.zcl.foundation as zcl_f

from zhaws.client.controller import Controller
from zhaws.client.model.types import AlarmControlPanelEntity
from zhaws.client.proxy import DeviceProxy
from zhaws.server.websocket.server import Server
from zhaws.server.zigbee.device import Device

from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

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
    zigpy_device: ZigpyDevice,
    connected_client_and_server: tuple[Controller, Server],
) -> None:
    """Test zhaws alarm control panel platform."""
    controller, server = connected_client_and_server
    zhaws_device: Device = await device_joined(zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints.get(1).ias_ace
    client_device: Optional[DeviceProxy] = controller.devices.get(zhaws_device.ieee)
    assert client_device is not None
    alarm_entity: AlarmControlPanelEntity = client_device.device_model.entities.get(
        "00:0d:6f:00:0a:90:69:e7-1"
    )  # type: ignore
    assert alarm_entity is not None
    assert isinstance(alarm_entity, AlarmControlPanelEntity)

    # test that the state is STATE_ALARM_DISARMED
    assert alarm_entity.state.state == "disarmed"

    # arm_away
    cluster.client_command.reset_mock()
    await controller.alarm_control_panels.arm_away(alarm_entity, "1234")
    assert cluster.client_command.call_count == 2
    assert cluster.client_command.await_count == 2
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.Armed_Away,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.No_Alarm,
    )
    assert alarm_entity.state.state == "armed_away"

    # disarm
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # trip alarm from faulty code entry. First we need to arm away
    cluster.client_command.reset_mock()
    await controller.alarm_control_panels.arm_away(alarm_entity, "1234")
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_away"
    cluster.client_command.reset_mock()

    # now simulate a faulty code entry sequence
    await controller.alarm_control_panels.disarm(alarm_entity, "0000")
    await controller.alarm_control_panels.disarm(alarm_entity, "0000")
    await controller.alarm_control_panels.disarm(alarm_entity, "0000")
    await server.block_till_done()

    assert alarm_entity.state.state == "triggered"
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
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # arm_home
    await controller.alarm_control_panels.arm_home(alarm_entity, "1234")
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_home"
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
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # arm_night
    await controller.alarm_control_panels.arm_night(alarm_entity, "1234")
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_night"
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
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # arm from panel
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Arm_All_Zones, "", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_away"

    # reset the panel
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # arm day home only from panel
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Arm_Day_Home_Only, "", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_home"

    # reset the panel
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # arm night sleep only from panel
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Arm_Night_Sleep_Only, "", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_night"

    # disarm from panel with bad code
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_night"

    # disarm from panel with bad code for 2nd time still armed
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "armed_night"

    # disarm from panel with bad code for 3rd time trips alarm
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "triggered"

    # disarm from panel with good code
    cluster.listener_event(
        "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "1234", 0]
    )
    await server.block_till_done()
    assert alarm_entity.state.state == "disarmed"

    # panic from panel
    cluster.listener_event("cluster_command", 1, 4, [])
    await server.block_till_done()
    assert alarm_entity.state.state == "triggered"

    # reset the panel
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # fire from panel
    cluster.listener_event("cluster_command", 1, 3, [])
    await server.block_till_done()
    assert alarm_entity.state.state == "triggered"

    # reset the panel
    await reset_alarm_panel(server, controller, cluster, alarm_entity)

    # emergency from panel
    cluster.listener_event("cluster_command", 1, 2, [])
    await server.block_till_done()
    assert alarm_entity.state.state == "triggered"

    # reset the panel
    await reset_alarm_panel(server, controller, cluster, alarm_entity)
    assert alarm_entity.state.state == "disarmed"

    await controller.alarm_control_panels.trigger(alarm_entity)
    await server.block_till_done()
    assert alarm_entity.state.state == "triggered"

    # reset the panel
    await reset_alarm_panel(server, controller, cluster, alarm_entity)
    assert alarm_entity.state.state == "disarmed"


async def reset_alarm_panel(
    server: Server,
    controller: Controller,
    cluster: security.IasAce,
    entity: AlarmControlPanelEntity,
) -> None:
    """Reset the state of the alarm panel."""
    cluster.client_command.reset_mock()
    await controller.alarm_control_panels.disarm(entity, "1234")
    await server.block_till_done()
    assert entity.state.state == "disarmed"
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
