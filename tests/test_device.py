"""Test ZHA device switch."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from unittest import mock
from unittest.mock import call, patch

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.exceptions import ZigbeeException
import zigpy.profiles.zha
import zigpy.types
from zigpy.zcl.clusters import general
from zigpy.zcl.foundation import Status, WriteAttributesResponse
import zigpy.zdo.types as zdo_t

from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_TYPE
from zha.application.const import (
    CLUSTER_COMMAND_SERVER,
    CLUSTER_COMMANDS_CLIENT,
    CLUSTER_COMMANDS_SERVER,
    CLUSTER_TYPE_IN,
    CLUSTER_TYPE_OUT,
    UNKNOWN,
)
from zha.application.gateway import Gateway
from zha.application.platforms.sensor import LQISensor, RSSISensor
from zha.application.platforms.switch import Switch
from zha.exceptions import ZHAException
from zha.zigbee.device import ClusterBinding, Device, get_device_automation_triggers
from zha.zigbee.group import Group


@pytest.fixture
def zigpy_device(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Callable[..., ZigpyDevice]:
    """Device tracker zigpy device."""

    def _dev(with_basic_cluster_handler: bool = True, **kwargs):
        in_clusters = [general.OnOff.cluster_id]
        if with_basic_cluster_handler:
            in_clusters.append(general.Basic.cluster_id)

        endpoints = {
            3: {
                SIG_EP_INPUT: in_clusters,
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
            }
        }
        return zigpy_device_mock(endpoints, **kwargs)

    return _dev


@pytest.fixture
def zigpy_device_mains(
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Callable[..., ZigpyDevice]:
    """Device tracker zigpy device."""

    def _dev(with_basic_cluster_handler: bool = True):
        in_clusters = [general.OnOff.cluster_id]
        if with_basic_cluster_handler:
            in_clusters.append(general.Basic.cluster_id)

        endpoints = {
            3: {
                SIG_EP_INPUT: in_clusters,
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
            }
        }
        return zigpy_device_mock(
            endpoints, node_descriptor=b"\x02@\x84_\x11\x7fd\x00\x00,d\x00\x00"
        )

    return _dev


@pytest.fixture
def device_with_basic_cluster_handler(
    zigpy_device_mains: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> ZigpyDevice:
    """Return a ZHA device with a basic cluster handler present."""
    return zigpy_device_mains(with_basic_cluster_handler=True)


@pytest.fixture
def device_without_basic_cluster_handler(
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> ZigpyDevice:
    """Return a ZHA device without a basic cluster handler present."""
    return zigpy_device(with_basic_cluster_handler=False)


@pytest.fixture
async def ota_zha_device(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Device:
    """ZHA device with OTA cluster fixture."""
    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [general.Ota.cluster_id],
                SIG_EP_TYPE: 0x1234,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    zha_device = await device_joined(zigpy_dev)
    return zha_device


async def _send_time_changed(zha_gateway: Gateway, seconds: int):
    """Send a time changed event."""
    await asyncio.sleep(seconds)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)


@patch(
    "zha.zigbee.cluster_handlers.general.BasicClusterHandler.async_initialize",
    new=mock.AsyncMock(),
)
@pytest.mark.looptime
async def test_check_available_success(
    zha_gateway: Gateway,
    device_with_basic_cluster_handler: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check device availability success on 1st try."""
    zha_device = await device_joined(device_with_basic_cluster_handler)
    basic_ch = device_with_basic_cluster_handler.endpoints[3].basic

    assert not zha_device.is_coordinator
    assert not zha_device.is_active_coordinator

    basic_ch.read_attributes.reset_mock()
    device_with_basic_cluster_handler.last_seen = None
    assert zha_device.available is True
    await _send_time_changed(zha_gateway, zha_device.consider_unavailable_time + 2)
    assert zha_device.available is False
    assert basic_ch.read_attributes.await_count == 0

    device_with_basic_cluster_handler.last_seen = (
        time.time() - zha_device.consider_unavailable_time - 100
    )
    _seens = [time.time(), device_with_basic_cluster_handler.last_seen]

    def _update_last_seen(*args, **kwargs):  # pylint: disable=unused-argument
        new_last_seen = _seens.pop()
        device_with_basic_cluster_handler.last_seen = new_last_seen

    basic_ch.read_attributes.side_effect = _update_last_seen

    # successfully ping zigpy device, but zha_device is not yet available
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )
    assert basic_ch.read_attributes.await_count == 1
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is False

    # There was traffic from the device: pings, but not yet available
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )
    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is False

    # There was traffic from the device: don't try to ping, marked as available
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )
    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is True
    assert zha_device.on_network is True

    assert "Device is not on the network, marking unavailable" not in caplog.text
    zha_device.on_network = False

    assert zha_device.available is False
    assert zha_device.on_network is False

    sleep_time = max(
        zha_gateway.global_updater.__polling_interval,
        zha_gateway._device_availability_checker.__polling_interval,
    )
    sleep_time += 2

    await asyncio.sleep(sleep_time)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert "Device is not on the network, marking unavailable" in caplog.text


@patch(
    "zha.zigbee.cluster_handlers.general.BasicClusterHandler.async_initialize",
    new=mock.AsyncMock(),
)
@pytest.mark.looptime
async def test_check_available_unsuccessful(
    zha_gateway: Gateway,
    device_with_basic_cluster_handler: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> None:
    """Check device availability all tries fail."""

    zha_device = await device_joined(device_with_basic_cluster_handler)
    basic_ch = device_with_basic_cluster_handler.endpoints[3].basic

    assert zha_device.available is True
    assert basic_ch.read_attributes.await_count == 0

    device_with_basic_cluster_handler.last_seen = (
        time.time() - zha_device.consider_unavailable_time - 2
    )

    # unsuccessfully ping zigpy device, but zha_device is still available
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )

    assert basic_ch.read_attributes.await_count == 1
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is True

    # still no traffic, but zha_device is still available
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )

    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is True

    # not even trying to update, device is unavailable
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )

    assert basic_ch.read_attributes.await_count == 2
    assert basic_ch.read_attributes.await_args[0][0] == ["manufacturer"]
    assert zha_device.available is False


@patch(
    "zha.zigbee.cluster_handlers.general.BasicClusterHandler.async_initialize",
    new=mock.AsyncMock(),
)
@pytest.mark.looptime
async def test_check_available_no_basic_cluster_handler(
    zha_gateway: Gateway,
    device_without_basic_cluster_handler: ZigpyDevice,  # pylint: disable=redefined-outer-name
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Check device availability for a device without basic cluster."""
    caplog.set_level(logging.DEBUG, logger="homeassistant.components.zha")

    zha_device = await device_joined(device_without_basic_cluster_handler)

    assert zha_device.available is True

    device_without_basic_cluster_handler.last_seen = (
        time.time() - zha_device.consider_unavailable_time - 2
    )

    assert "does not have a mandatory basic cluster" not in caplog.text
    await _send_time_changed(
        zha_gateway, zha_gateway._device_availability_checker.__polling_interval + 1
    )

    assert zha_device.available is False
    assert "does not have a mandatory basic cluster" in caplog.text


async def test_device_is_active_coordinator(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test that the current coordinator is uniquely detected."""

    current_coord_dev = zigpy_device(ieee="aa:bb:cc:dd:ee:ff:00:11", nwk=0x0000)
    current_coord_dev.node_desc = current_coord_dev.node_desc.replace(
        logical_type=zdo_t.LogicalType.Coordinator
    )

    old_coord_dev = zigpy_device(ieee="aa:bb:cc:dd:ee:ff:00:12", nwk=0x0000)
    old_coord_dev.node_desc = old_coord_dev.node_desc.replace(
        logical_type=zdo_t.LogicalType.Coordinator
    )

    # The two coordinators have different IEEE addresses
    assert current_coord_dev.ieee != old_coord_dev.ieee

    current_coordinator = await device_joined(current_coord_dev)
    stale_coordinator = await device_joined(old_coord_dev)

    # Ensure the current ApplicationController's IEEE matches our coordinator's
    current_coordinator.gateway.application_controller.state.node_info.ieee = (
        current_coord_dev.ieee
    )

    assert current_coordinator.is_active_coordinator
    assert not stale_coordinator.is_active_coordinator


async def test_async_get_clusters(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test async_get_clusters method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    assert zha_device.async_get_clusters() == {
        3: {
            CLUSTER_TYPE_IN: {
                general.Basic.cluster_id: zigpy_dev.endpoints[3].in_clusters[
                    general.Basic.cluster_id
                ],
                general.OnOff.cluster_id: zigpy_dev.endpoints[3].in_clusters[
                    general.OnOff.cluster_id
                ],
            },
            CLUSTER_TYPE_OUT: {},
        }
    }


async def test_async_get_groupable_endpoints(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test async_get_groupable_endpoints method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zigpy_dev.endpoints[3].add_input_cluster(general.Groups.cluster_id)
    zha_device = await device_joined(zigpy_dev)

    assert zha_device.async_get_groupable_endpoints() == [3]


async def test_async_get_std_clusters(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test async_get_std_clusters method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zigpy_dev.endpoints[3].profile_id = zigpy.profiles.zha.PROFILE_ID
    zha_device = await device_joined(zigpy_dev)

    assert zha_device.async_get_std_clusters() == {
        3: {
            CLUSTER_TYPE_IN: {
                general.Basic.cluster_id: zigpy_dev.endpoints[3].in_clusters[
                    general.Basic.cluster_id
                ],
                general.OnOff.cluster_id: zigpy_dev.endpoints[3].in_clusters[
                    general.OnOff.cluster_id
                ],
            },
            CLUSTER_TYPE_OUT: {},
        }
    }


async def test_async_get_cluster(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test async_get_cluster method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    assert zha_device.async_get_cluster(3, general.OnOff.cluster_id) == (
        zigpy_dev.endpoints[3].on_off
    )


async def test_async_get_cluster_attributes(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test async_get_cluster_attributes method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    assert (
        zha_device.async_get_cluster_attributes(3, general.OnOff.cluster_id)
        == zigpy_dev.endpoints[3].on_off.attributes
    )

    with pytest.raises(KeyError):
        assert (
            zha_device.async_get_cluster_attributes(3, general.BinaryValue.cluster_id)
            is None
        )


async def test_async_get_cluster_commands(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test async_get_cluster_commands method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    assert zha_device.async_get_cluster_commands(3, general.OnOff.cluster_id) == {
        CLUSTER_COMMANDS_CLIENT: zigpy_dev.endpoints[3].on_off.client_commands,
        CLUSTER_COMMANDS_SERVER: zigpy_dev.endpoints[3].on_off.server_commands,
    }


async def test_write_zigbee_attribute(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test write_zigbee_attribute method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    with pytest.raises(
        ValueError,
        match="Cluster 8 not found on endpoint 3 while writing attribute 0 with value 20",
    ):
        await zha_device.write_zigbee_attribute(
            3,
            general.LevelControl.cluster_id,
            general.LevelControl.AttributeDefs.current_level.id,
            20,
        )

    cluster = zigpy_dev.endpoints[3].on_off
    cluster.write_attributes.reset_mock()

    response: WriteAttributesResponse = await zha_device.write_zigbee_attribute(
        3,
        general.OnOff.cluster_id,
        general.OnOff.AttributeDefs.start_up_on_off.id,
        general.OnOff.StartUpOnOff.PreviousValue,
    )

    assert response is not None
    assert len(response) == 1
    status_record = response[0][0]
    assert status_record.status == Status.SUCCESS

    assert cluster.write_attributes.await_count == 1
    assert cluster.write_attributes.await_args == call(
        {
            general.OnOff.AttributeDefs.start_up_on_off.id: general.OnOff.StartUpOnOff.PreviousValue
        },
        manufacturer=None,
    )

    cluster.write_attributes.reset_mock()
    cluster.write_attributes.side_effect = ZigbeeException
    m1 = "Failed to set attribute: value: <StartUpOnOff.PreviousValue: 255> "
    m2 = "attribute: 16387 cluster_id: 6 endpoint_id: 3"
    with pytest.raises(
        ZHAException,
        match=f"{m1}{m2}",
    ):
        await zha_device.write_zigbee_attribute(
            3,
            general.OnOff.cluster_id,
            general.OnOff.AttributeDefs.start_up_on_off.id,
            general.OnOff.StartUpOnOff.PreviousValue,
        )

    cluster = zigpy_dev.endpoints[3].on_off
    cluster.write_attributes.reset_mock()


async def test_issue_cluster_command(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test issue_cluster_command method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    with pytest.raises(
        ValueError,
        match="Cluster 8 not found on endpoint 3 while issuing command 0 with args \\[20\\]",
    ):
        await zha_device.issue_cluster_command(
            3,
            general.LevelControl.cluster_id,
            general.LevelControl.ServerCommandDefs.move_to_level.id,
            CLUSTER_COMMAND_SERVER,
            [20],
            None,
        )

    cluster = zigpy_dev.endpoints[3].on_off

    with patch("zigpy.zcl.Cluster.request", return_value=[0x5, Status.SUCCESS]):
        await zha_device.issue_cluster_command(
            3,
            general.OnOff.cluster_id,
            general.OnOff.ServerCommandDefs.on.id,
            CLUSTER_COMMAND_SERVER,
            None,
            {},
        )

        assert cluster.request.await_count == 1


async def test_async_add_to_group_remove_from_group(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test async_add_to_group and async_remove_from_group methods."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zigpy_dev.endpoints[3].add_input_cluster(general.Groups.cluster_id)
    zha_device = await device_joined(zigpy_dev)

    group: Group = zha_device.gateway.groups[0x1001]

    assert (zha_device.ieee, 3) not in group.zigpy_group.members

    await zha_device.async_add_to_group(group.group_id)

    assert (zha_device.ieee, 3) in group.zigpy_group.members

    await zha_device.async_remove_from_group(group.group_id)

    assert (zha_device.ieee, 3) not in group.zigpy_group.members

    await zha_device.async_add_endpoint_to_group(3, group.group_id)

    assert (zha_device.ieee, 3) in group.zigpy_group.members

    await zha_device.async_remove_endpoint_from_group(3, group.group_id)

    assert (zha_device.ieee, 3) not in group.zigpy_group.members

    with patch("zigpy.device.Device.add_to_group", side_effect=ZigbeeException):
        await zha_device.async_add_to_group(group.group_id)
        assert (zha_device.ieee, 3) not in group.zigpy_group.members
        assert (
            "Failed to add device '00:0d:6f:00:0a:90:69:e7' to group: 0x1001"
            in caplog.text
        )

    with patch("zigpy.endpoint.Endpoint.add_to_group", side_effect=ZigbeeException):
        await zha_device.async_add_endpoint_to_group(3, group.group_id)
        assert (zha_device.ieee, 3) not in group.zigpy_group.members
        assert (
            "Failed to add endpoint: 3 for device: '00:0d:6f:00:0a:90:69:e7' to group: 0x1001"
            in caplog.text
        )

    # add it
    assert (zha_device.ieee, 3) not in group.zigpy_group.members
    await zha_device.async_add_to_group(group.group_id)
    assert (zha_device.ieee, 3) in group.zigpy_group.members

    with patch("zigpy.device.Device.remove_from_group", side_effect=ZigbeeException):
        await zha_device.async_remove_from_group(group.group_id)
        assert (zha_device.ieee, 3) in group.zigpy_group.members
        assert (
            "Failed to remove device '00:0d:6f:00:0a:90:69:e7' from group: 0x1001"
            in caplog.text
        )

    with patch(
        "zigpy.endpoint.Endpoint.remove_from_group", side_effect=ZigbeeException
    ):
        await zha_device.async_remove_endpoint_from_group(3, group.group_id)
        assert (zha_device.ieee, 3) in group.zigpy_group.members
        assert (
            "Failed to remove endpoint: 3 for device '00:0d:6f:00:0a:90:69:e7' from group: 0x1001"
            in caplog.text
        )


async def test_async_bind_to_group(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test async_bind_to_group method."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zigpy_dev.endpoints[3].add_input_cluster(general.Groups.cluster_id)
    zha_device = await device_joined(zigpy_dev)

    zigpy_dev_remote = zigpy_device(with_basic_cluster_handler=True)
    zigpy_dev_remote._ieee = zigpy.types.EUI64.convert("00:0d:7f:00:0a:90:69:e8")
    zigpy_dev_remote.endpoints[3].add_output_cluster(general.OnOff.cluster_id)
    zha_device_remote = await device_joined(zigpy_dev_remote)
    assert zha_device_remote is not None

    group: Group = zha_device.gateway.groups[0x1001]

    # add a device to the group for binding
    assert (zha_device.ieee, 3) not in group.zigpy_group.members
    await zha_device.async_add_to_group(group.group_id)
    assert (zha_device.ieee, 3) in group.zigpy_group.members

    await zha_device_remote.async_bind_to_group(
        group.group_id,
        [ClusterBinding(name="on_off", type=CLUSTER_TYPE_OUT, id=6, endpoint_id=3)],
    )
    assert (
        "0xb79c: Bind_req 00:0d:7f:00:0a:90:69:e8, ep: 3, cluster: 6 to group: 0x1001 completed: [<Status.SUCCESS: 0>]"
        in caplog.text
    )

    await zha_device_remote.async_unbind_from_group(
        group.group_id,
        [ClusterBinding(name="on_off", type=CLUSTER_TYPE_OUT, id=6, endpoint_id=3)],
    )

    m1 = "0xb79c: Unbind_req 00:0d:7f:00:0a:90:69:e8, ep: 3, cluster: 6"
    assert f"{m1} to group: 0x1001 completed: [<Status.SUCCESS: 0>]" in caplog.text


async def test_device_automation_triggers(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test device automation triggers."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    assert get_device_automation_triggers(zha_device) == {
        ("device_offline", "device_offline"): {"device_event_type": "device_offline"}
    }

    assert zha_device.device_automation_commands == {}
    assert zha_device.device_automation_triggers == {
        ("device_offline", "device_offline"): {"device_event_type": "device_offline"}
    }


async def test_device_properties(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device: Callable[..., ZigpyDevice],  # pylint: disable=redefined-outer-name
) -> None:
    """Test device properties."""
    zigpy_dev = zigpy_device(with_basic_cluster_handler=True)
    zha_device = await device_joined(zigpy_dev)

    assert zha_device.is_mains_powered is False
    assert zha_device.is_end_device is True
    assert zha_device.is_router is False
    assert zha_device.is_coordinator is False
    assert zha_device.is_active_coordinator is False
    assert zha_device.device_type == "EndDevice"
    assert zha_device.power_source == "Battery or Unknown"
    assert zha_device.available is True
    assert zha_device.on_network is True
    assert zha_device.last_seen is not None
    assert zha_device.last_seen < time.time()

    assert zha_device.ieee == zigpy_dev.ieee
    assert zha_device.nwk == zigpy_dev.nwk
    assert zha_device.manufacturer_code == 0x1037
    assert zha_device.name == "FakeManufacturer FakeModel"
    assert zha_device.manufacturer == "FakeManufacturer"
    assert zha_device.model == "FakeModel"
    assert zha_device.is_groupable is False

    assert zha_device.power_configuration_ch is None
    assert zha_device.basic_ch is not None
    assert zha_device.sw_version is None

    assert len(zha_device.platform_entities) == 3
    assert "00:0d:6f:00:0a:90:69:e7-3-0-lqi" in zha_device.platform_entities
    assert "00:0d:6f:00:0a:90:69:e7-3-0-rssi" in zha_device.platform_entities
    assert "00:0d:6f:00:0a:90:69:e7-3-6" in zha_device.platform_entities

    assert isinstance(
        zha_device.platform_entities["00:0d:6f:00:0a:90:69:e7-3-0-lqi"], LQISensor
    )
    assert isinstance(
        zha_device.platform_entities["00:0d:6f:00:0a:90:69:e7-3-0-rssi"], RSSISensor
    )
    assert isinstance(
        zha_device.platform_entities["00:0d:6f:00:0a:90:69:e7-3-6"], Switch
    )

    assert zha_device.get_platform_entity("00:0d:6f:00:0a:90:69:e7-3-0-lqi") is not None
    assert isinstance(
        zha_device.get_platform_entity("00:0d:6f:00:0a:90:69:e7-3-0-lqi"), LQISensor
    )

    with pytest.raises(KeyError, match="Entity foo not found"):
        zha_device.get_platform_entity("foo")

    # test things are none when they aren't returned by Zigpy
    zigpy_dev.node_desc = None
    delattr(zha_device, "manufacturer_code")
    delattr(zha_device, "is_mains_powered")
    delattr(zha_device, "device_type")
    delattr(zha_device, "is_router")
    delattr(zha_device, "is_end_device")
    delattr(zha_device, "is_coordinator")

    assert zha_device.manufacturer_code is None
    assert zha_device.is_mains_powered is None
    assert zha_device.device_type is UNKNOWN
    assert zha_device.is_router is None
    assert zha_device.is_end_device is None
    assert zha_device.is_coordinator is None
