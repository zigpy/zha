"""Test zha alarm control panel."""

import asyncio
import logging
from unittest.mock import AsyncMock, call, patch, sentinel

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.zcl.clusters import security
import zigpy.zcl.foundation as zcl_f

from tests.common import join_zigpy_device, zigpy_device_from_json
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms.alarm_control_panel import AlarmControlPanel
from zha.application.platforms.alarm_control_panel.const import (
    IAS_ACE_STATE_MAP,
    AlarmState,
)
from zha.zigbee.device import Device

_LOGGER = logging.getLogger(__name__)


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test zhaws alarm control panel platform."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints[44].out_clusters[
        security.IasAce.cluster_id
    ]
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
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

    alarm_entity.code_required_arm_actions = True
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


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_exit_delays(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test alarm control panel exit delay functionality."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints[44].out_clusters[
        security.IasAce.cluster_id
    ]
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    assert isinstance(alarm_entity, AlarmControlPanel)
    cluster_handler = alarm_entity

    # Configure exit delays
    cluster_handler.exit_delay_away = 3
    cluster_handler.exit_delay_home = 2
    cluster_handler.exit_delay_night = 1

    # Test arm_away with exit delay
    cluster.client_command.reset_mock()
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()

    # Should be in exit delay state
    assert alarm_entity.state["state"] == AlarmState.ARMING
    assert cluster_handler._get_seconds_remaining() == 3

    # Wait for exit delay to complete
    await asyncio.sleep(3.5)
    await zha_gateway.async_block_till_done()

    # Should now be armed away
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    # Reset
    await alarm_entity.async_alarm_disarm("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    # Test arm_home with exit delay
    cluster.client_command.reset_mock()
    await alarm_entity.async_alarm_arm_home("4321")
    await zha_gateway.async_block_till_done()

    # Should be in exit delay state
    assert alarm_entity.state["state"] == AlarmState.ARMING

    # Wait for exit delay to complete
    await asyncio.sleep(2.5)
    await zha_gateway.async_block_till_done()

    # Should now be armed home
    assert alarm_entity.state["state"] == AlarmState.ARMED_HOME

    # Reset
    await alarm_entity.async_alarm_disarm("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    # Test arm_night with exit delay
    cluster.client_command.reset_mock()
    await alarm_entity.async_alarm_arm_night("4321")
    await zha_gateway.async_block_till_done()

    # Should be in exit delay state
    assert alarm_entity.state["state"] == AlarmState.ARMING

    # Wait for exit delay to complete
    await asyncio.sleep(1.5)
    await zha_gateway.async_block_till_done()

    # Should now be armed night
    assert alarm_entity.state["state"] == AlarmState.ARMED_NIGHT


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_exit_delay_cancellation(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that disarming during exit delay cancels the timer."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    cluster_handler = alarm_entity

    # Configure exit delay
    cluster_handler.exit_delay_away = 5

    # Start arming with exit delay
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMING

    # Disarm before exit delay completes
    await asyncio.sleep(1)
    await alarm_entity.async_alarm_disarm("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    # Wait to ensure timer was cancelled and doesn't fire
    await asyncio.sleep(5)
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_entry_delay(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test alarm control panel entry delay functionality."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints[44].out_clusters[
        security.IasAce.cluster_id
    ]
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    cluster_handler = alarm_entity

    # Arm the panel first (no exit delay for this test)
    cluster_handler.exit_delay_away = 0
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    # Start entry delay (simulating zone trigger from external system like Alarmo)
    await alarm_entity.async_start_entry_delay(3)
    await zha_gateway.async_block_till_done()

    # Should be in entry delay state
    assert alarm_entity.state["state"] == AlarmState.PENDING

    # Wait for entry delay to complete
    await asyncio.sleep(3.5)
    await zha_gateway.async_block_till_done()

    # Should now be triggered
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED
    assert cluster_handler.alarm_status == security.IasAce.AlarmStatus.Burglar
    assert cluster.client_command.call_args == call(
        4,
        security.IasAce.PanelStatus.In_Alarm,
        0,
        security.IasAce.AudibleNotification.Default_Sound,
        security.IasAce.AlarmStatus.Burglar,
    )


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_entry_delay_disarm(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that disarming during entry delay prevents alarm trigger."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    cluster_handler = alarm_entity

    # Arm the panel
    cluster_handler.exit_delay_away = 0
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    # Start entry delay
    await alarm_entity.async_start_entry_delay(5)
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.PENDING

    # Disarm before entry delay completes
    await asyncio.sleep(1)
    await alarm_entity.async_alarm_disarm("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED

    # Wait to ensure timer was cancelled and alarm doesn't trigger
    await asyncio.sleep(5)
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.DISARMED


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_entry_delay_lockout_cancels_timer(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Lockout during entry delay cancels timer so it does not fire later."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints[44].out_clusters[
        security.IasAce.cluster_id
    ]
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    cluster_handler = alarm_entity

    cluster_handler.exit_delay_away = 0
    cluster_handler.max_invalid_tries = 3
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    await alarm_entity.async_start_entry_delay(5)
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.PENDING

    caplog.clear()
    for _ in range(3):
        cluster.listener_event(
            "cluster_command", 1, 0, [security.IasAce.ArmMode.Disarm, "0000", 0]
        )
        await zha_gateway.async_block_till_done()

    assert alarm_entity.state["state"] == AlarmState.TRIGGERED

    await asyncio.sleep(5.5)
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.TRIGGERED
    assert "Entry delay expired - alarm triggered" not in caplog.text


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_zero_exit_delay(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that zero exit delay arms immediately."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    cluster_handler = alarm_entity

    # Configure zero exit delay
    cluster_handler.exit_delay_away = 0

    # Arm away
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()

    # Should be armed immediately, not in arming state
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_public_exit_delay_method(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test async_start_exit_delay entity API (e.g. Alarmo integration)."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None

    await alarm_entity.async_start_exit_delay(2, arm_mode="home")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMING

    await asyncio.sleep(2.5)
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_HOME


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_zero_entry_delay(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that zero entry delay is handled gracefully."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None
    cluster_handler = alarm_entity

    # Arm the panel
    cluster_handler.exit_delay_away = 0
    await alarm_entity.async_alarm_arm_away("4321")
    await zha_gateway.async_block_till_done()
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY

    # Try to start entry delay with 0 seconds
    await alarm_entity.async_start_entry_delay(0)
    await zha_gateway.async_block_till_done()

    # Should remain armed (not enter pending state)
    assert alarm_entity.state["state"] == AlarmState.ARMED_AWAY
    assert "Entry delay called with 0 seconds" in caplog.text


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_panel_status_commands(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test panel status request/response commands."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints[44].out_clusters[
        security.IasAce.cluster_id
    ]
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None

    # Test get_panel_status command
    cluster.client_command.reset_mock()

    # Simulate get_panel_status command from keypad
    cluster.listener_event(
        "cluster_command",
        1,
        security.IasAce.ServerCommandDefs.get_panel_status.id,
        [],
    )
    await zha_gateway.async_block_till_done()

    # Should send panel_status_response
    assert cluster.client_command.call_count >= 1


@patch(
    "zigpy.zcl.clusters.security.IasAce.client_command",
    new=AsyncMock(return_value=[sentinel.data, zcl_f.Status.SUCCESS]),
)
async def test_alarm_control_panel_bypass_command(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test bypass command handling."""
    zigpy_device: ZigpyDevice = await zigpy_device_from_json(
        zha_gateway.application_controller,
        "tests/data/devices/frient-a-s-kepzb-110.json",
    )
    zha_device: Device = await join_zigpy_device(zha_gateway, zigpy_device)
    cluster: security.IasAce = zigpy_device.endpoints[44].out_clusters[
        security.IasAce.cluster_id
    ]
    alarm_entity: AlarmControlPanel = zha_device.platform_entities.get(
        (
            Platform.ALARM_CONTROL_PANEL,
            f"{zigpy_device.ieee}-44-{security.IasAce.cluster_id}",
        )
    )
    assert alarm_entity is not None

    # Simulate bypass command from keypad
    zone_list = [1, 2, 3]
    code = "4321"
    cluster.listener_event(
        "cluster_command",
        1,
        security.IasAce.ServerCommandDefs.bypass.id,
        [zone_list, code],
    )
    await zha_gateway.async_block_till_done()

    # Command should be logged/emitted as event
    # (Current implementation emits ZHA event but doesn't store bypass state)


def test_ias_ace_state_map_arming_panel_statuses() -> None:
    """Arming_* panel statuses map to HA arming (same as Exit_Delay)."""
    assert (
        IAS_ACE_STATE_MAP[security.IasAce.PanelStatus.Exit_Delay] == AlarmState.ARMING
    )
    assert (
        IAS_ACE_STATE_MAP[security.IasAce.PanelStatus.Arming_Stay] == AlarmState.ARMING
    )
    assert (
        IAS_ACE_STATE_MAP[security.IasAce.PanelStatus.Arming_Night] == AlarmState.ARMING
    )
    assert (
        IAS_ACE_STATE_MAP[security.IasAce.PanelStatus.Arming_Away] == AlarmState.ARMING
    )
