"""Test ZHA Gateway."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, call, patch

import pytest
from zigpy.application import ControllerApplication
from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl.clusters import general, lighting
import zigpy.zdo.types
import zigpy.zdo.types as zdo_t
from zigpy.zdo.types import LogicalType, NodeDescriptor

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    get_group_entity,
    join_zigpy_device,
)
from zha.application import Platform
from zha.application.const import (
    CONF_USE_THREAD,
    ZHA_GW_MSG,
    ZHA_GW_MSG_CONNECTION_LOST,
    RadioType,
)
from zha.application.gateway import (
    ConnectionLostEvent,
    DeviceJoinedDeviceInfo,
    DeviceJoinedEvent,
    DevicePairingStatus,
    Gateway,
    RawDeviceInitializedDeviceInfo,
    RawDeviceInitializedEvent,
)
from zha.application.helpers import ZHAData
from zha.application.platforms import GroupEntity
from zha.application.platforms.light.const import EFFECT_OFF, LightEntityFeature
from zha.zigbee.device import Device
from zha.zigbee.group import Group, GroupMemberReference

IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"


ZIGPY_DEVICE_BASIC = {
    1: {
        SIG_EP_INPUT: [general.Basic.cluster_id],
        SIG_EP_OUTPUT: [],
        SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
        SIG_EP_PROFILE: zha.PROFILE_ID,
    }
}


async def coordinator_mock(zha_gateway: Gateway) -> Device:
    """Test ZHA light platform."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee="00:15:8d:00:02:32:4f:32",
        nwk=0x0000,
        node_descriptor=zdo_t.NodeDescriptor(
            logical_type=zdo_t.LogicalType.Coordinator,
            complex_descriptor_available=0,
            user_descriptor_available=0,
            reserved=0,
            aps_flags=0,
            frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
            mac_capability_flags=(
                zdo_t.NodeDescriptor.MACCapabilityFlags.AlternatePanCoordinator
                | zdo_t.NodeDescriptor.MACCapabilityFlags.FullFunctionDevice
                | zdo_t.NodeDescriptor.MACCapabilityFlags.MainsPowered
                | zdo_t.NodeDescriptor.MACCapabilityFlags.RxOnWhenIdle
                | zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress
            ),
            manufacturer_code=43981,
            maximum_buffer_size=82,
            maximum_incoming_transfer_size=128,
            server_mask=11329,
            maximum_outgoing_transfer_size=128,
            descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
        ),
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device


async def device_light_1_mock(zha_gateway: Gateway) -> Device:
    """Test ZHA light platform."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                    lighting.Color.cluster_id,
                    general.Groups.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE,
        manufacturer="Philips",
        model="LWA004",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device


async def device_light_2_mock(zha_gateway: Gateway) -> Device:
    """Test ZHA light platform."""

    zigpy_device = create_mock_zigpy_device(
        zha_gateway,
        {
            1: {
                SIG_EP_INPUT: [
                    general.OnOff.cluster_id,
                    general.LevelControl.cluster_id,
                    lighting.Color.cluster_id,
                    general.Groups.cluster_id,
                ],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        },
        ieee=IEEE_GROUPABLE_DEVICE2,
        manufacturer="Sengled",
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)
    return zha_device


async def test_device_left(zha_gateway: Gateway) -> None:
    """Device leaving the network should become unavailable."""
    zigpy_dev_basic = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE_BASIC)
    zha_dev_basic = await join_zigpy_device(zha_gateway, zigpy_dev_basic)
    assert zha_dev_basic.available is True

    zha_gateway.device_left(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()
    assert zha_dev_basic.available is False
    assert zha_dev_basic.on_network is False


async def test_gateway_startup_failure(
    zha_data: ZHAData,
) -> None:
    """Test shutdown called when gateway init fails."""

    zha_gateway = await Gateway.async_from_config(zha_data)

    with (
        patch("zha.application.gateway.Gateway.load_devices", side_effect=Exception),
        pytest.raises(Exception),
    ):
        zha_gateway.shutdown = AsyncMock(wraps=zha_gateway.shutdown)
        await zha_gateway.async_initialize()
        await zha_gateway.async_block_till_done()

    assert zha_gateway.shutdown.await_count == 1


async def test_gateway_starts_entity_exception(
    zha_data: ZHAData,
    zigpy_app_controller: ControllerApplication,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test gateway starts when we fail to create an entity."""

    with (
        patch(
            "bellows.zigbee.application.ControllerApplication.new",
            return_value=zigpy_app_controller,
        ),
        patch(
            "bellows.zigbee.application.ControllerApplication",
            return_value=zigpy_app_controller,
        ),
        patch(
            "zha.application.platforms.sensor.DeviceCounterSensor.__init__",
            side_effect=Exception,
        ),
    ):
        zha_gateway = await Gateway.async_from_config(zha_data)
        await zha_gateway.async_initialize()
        await zha_gateway.async_block_till_done()
        await zha_gateway.async_initialize_devices_and_entities()

        assert "Failed to create entity" in caplog.text

        await zha_gateway.shutdown()


@pytest.mark.parametrize(("enabled", "await_count"), [(True, 1), (False, 0)])
async def test_mains_devices_startup_polling_config(
    zha_data: ZHAData,
    zigpy_app_controller: ControllerApplication,
    enabled: bool,
    await_count: int,
) -> None:
    """Test mains powered device startup polling config is respected."""

    with (
        patch(
            "bellows.zigbee.application.ControllerApplication.new",
            return_value=zigpy_app_controller,
        ),
        patch(
            "bellows.zigbee.application.ControllerApplication",
            return_value=zigpy_app_controller,
        ),
    ):
        zha_data.config.device_options.enable_mains_startup_polling = enabled
        zha_gateway = await Gateway.async_from_config(zha_data)
        zha_gateway.async_fetch_updated_state_mains = AsyncMock(
            wraps=zha_gateway.async_fetch_updated_state_mains
        )
        await zha_gateway.async_initialize()
        await zha_gateway.async_block_till_done()
        await zha_gateway.async_initialize_devices_and_entities()
        await zha_gateway.async_block_till_done()

        assert zha_gateway.async_fetch_updated_state_mains.await_count == await_count

        await zha_gateway.shutdown()
        await zha_gateway.async_block_till_done()


async def test_gateway_group_methods(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test creating a group with 2 members."""
    coordinator = await coordinator_mock(zha_gateway)
    zha_gateway.coordinator_zha_device = coordinator
    coordinator._zha_gateway = zha_gateway
    device_light_1 = await device_light_1_mock(zha_gateway)
    device_light_2 = await device_light_2_mock(zha_gateway)
    device_light_1._zha_gateway = zha_gateway
    device_light_2._zha_gateway = zha_gateway

    member_ieee_addresses = [device_light_1.ieee, device_light_2.ieee]
    members = [
        GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
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

    entity: GroupEntity | None = get_group_entity(zha_group, platform=Platform.LIGHT)
    assert entity is not None

    info = entity.info_object
    assert info.class_name == "LightGroup"
    assert info.platform == Platform.LIGHT
    assert info.unique_id == "light_zha_group_0x0002"
    assert info.fallback_name == "Test Group"
    assert info.group_id == zha_group.group_id
    assert info.supported_features == LightEntityFeature.TRANSITION
    assert info.min_mireds == 153
    assert info.max_mireds == 500
    assert info.effect_list == [EFFECT_OFF]

    device_1_light_entity = get_entity(device_light_1, platform=Platform.LIGHT)
    device_2_light_entity = get_entity(device_light_2, platform=Platform.LIGHT)
    assert device_1_light_entity != device_2_light_entity

    assert device_1_light_entity is not None
    assert device_2_light_entity is not None

    # test get group by name
    assert zha_group == zha_gateway.get_group(zha_group.name)

    # test removing a group
    await zha_gateway.async_remove_zigpy_group(zha_group.group_id)
    await zha_gateway.async_block_till_done()

    # we shouldn't have the group anymore
    assert zha_gateway.get_group(zha_group.name) is None

    # the group entity should be cleaned up
    with pytest.raises(KeyError):
        get_group_entity(zha_group, platform=Platform.LIGHT)

    # test creating a group with 1 member
    zha_group = await zha_gateway.async_create_zigpy_group(
        "Test Group", [GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1)]
    )
    await zha_gateway.async_block_till_done()

    assert zha_group is not None
    assert len(zha_group.members) == 1
    for member in zha_group.members:
        assert member.device.ieee in [device_light_1.ieee]

    # no entity should be created for a group with a single member
    with pytest.raises(KeyError):
        get_group_entity(zha_group, platform=Platform.LIGHT)

    with patch("zigpy.zcl.Cluster.request", side_effect=TimeoutError):
        await zha_group.members[0].async_remove_from_group()
        assert len(zha_group.members) == 1
        for member in zha_group.members:
            assert member.device.ieee in [device_light_1.ieee]

    await zha_gateway.async_remove_zigpy_group(23)
    await zha_gateway.async_block_till_done()
    assert "Group: 0x0017 could not be found" in caplog.text

    assert zha_gateway.get_group(zha_group.group_id) is not None
    assert zha_gateway.get_group(zha_group.group_id) == zha_group


async def test_gateway_create_group_with_id_without_id(zha_gateway: Gateway) -> None:
    """Test creating a group with a specific ID."""

    assert zha_gateway is not None
    coordinator = await coordinator_mock(zha_gateway)
    zha_gateway.coordinator_zha_device = coordinator
    device_light_1 = await device_light_1_mock(zha_gateway)
    coordinator._zha_gateway = zha_gateway
    device_light_1._zha_gateway = zha_gateway

    zha_group = await zha_gateway.async_create_zigpy_group(
        "Test Group",
        [GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1)],
        group_id=0x1234,
    )
    await zha_gateway.async_block_till_done()

    assert len(zha_group.members) == 1
    assert zha_group.members[0].device is device_light_1
    assert zha_group.group_id == 0x1234

    # create group with no group id passed in
    zha_group2 = await zha_gateway.async_create_zigpy_group(
        "Test Group2",
        [GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1)],
    )

    assert len(zha_group2.members) == 1
    assert zha_group2.members[0].device is device_light_1
    assert zha_group2.group_id == 0x0002

    # create group with no group id passed in
    zha_group3 = await zha_gateway.async_create_zigpy_group(
        "Test Group3",
        [GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1)],
    )

    assert len(zha_group3.members) == 1
    assert zha_group3.members[0].device is device_light_1
    assert zha_group3.group_id == 0x0003


async def test_remove_device_cleans_up_group_membership(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test group membership cleanup when removing a device in a group."""

    coordinator = await coordinator_mock(zha_gateway)
    zha_gateway.coordinator_zha_device = coordinator
    coordinator._zha_gateway = zha_gateway
    device_light_1 = await device_light_1_mock(zha_gateway)
    device_light_2 = await device_light_2_mock(zha_gateway)
    device_light_1._zha_gateway = zha_gateway
    device_light_2._zha_gateway = zha_gateway

    member_ieee_addresses = [device_light_1.ieee, device_light_2.ieee]
    members = [
        GroupMemberReference(ieee=device_light_1.ieee, endpoint_id=1),
        GroupMemberReference(ieee=device_light_2.ieee, endpoint_id=1),
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

    await zha_gateway.async_remove_device(coordinator.ieee)
    await zha_gateway.async_block_till_done()
    assert len(zha_group.members) == 2
    assert (
        f"Removing the active coordinator ({str(coordinator.ieee)}) is not allowed"
        in caplog.text
    )

    non_existent_ieee = zigpy.types.EUI64.convert("01:2d:6f:70:7a:40:79:e8")
    await zha_gateway.async_remove_device(non_existent_ieee)
    await zha_gateway.async_block_till_done()
    assert len(zha_group.members) == 2
    assert f"Device: {str(non_existent_ieee)} could not be found" in caplog.text

    await zha_gateway.async_remove_device(device_light_1.ieee)
    await zha_gateway.async_block_till_done()

    assert len(zha_group.members) == 1
    assert zha_group.members[0].device.ieee == device_light_2.ieee
    assert device_light_1.ieee not in zha_gateway.devices


@patch(
    "zha.application.gateway.Gateway.load_devices",
    AsyncMock(),
)
@patch(
    "zha.application.gateway.Gateway.load_groups",
    MagicMock(),
)
@pytest.mark.parametrize(
    ("device_path", "thread_state", "config_override"),
    [
        ("/dev/ttyUSB0", True, {}),
        ("socket://192.168.1.123:9999", False, {}),
        ("socket://192.168.1.123:9999", True, {"use_thread": True}),
    ],
)
async def test_gateway_initialize_bellows_thread(
    device_path: str,
    thread_state: bool,
    config_override: dict,
    zigpy_app_controller: ControllerApplication,
    zha_data: ZHAData,
) -> None:
    """Test ZHA disabling the UART thread when connecting to a TCP coordinator."""
    zha_data.config.coordinator_configuration.path = device_path
    zha_data.zigpy_config = config_override

    with patch(
        "bellows.zigbee.application.ControllerApplication.new",
        return_value=zigpy_app_controller,
    ) as mock_new:
        zha_gw = Gateway(zha_data)
        await zha_gw.async_initialize()
        assert (
            mock_new.mock_calls[-1].kwargs["config"].get(CONF_USE_THREAD, True)
            is thread_state
        )
        await zha_gw.shutdown()


@pytest.mark.parametrize("radio_concurrency", [1, 2, 8])
async def test_startup_concurrency_limit(
    radio_concurrency: int,
    zigpy_app_controller: ControllerApplication,
    zha_data: ZHAData,
):
    """Test ZHA gateway limits concurrency on startup."""
    zha_gw = Gateway(zha_data)

    with patch(
        "bellows.zigbee.application.ControllerApplication.new",
        return_value=zigpy_app_controller,
    ):
        await zha_gw.async_initialize()

    for i in range(50):
        zigpy_dev = create_mock_zigpy_device(
            zha_gw,
            {
                1: {
                    SIG_EP_INPUT: [
                        general.OnOff.cluster_id,
                        general.LevelControl.cluster_id,
                        lighting.Color.cluster_id,
                        general.Groups.cluster_id,
                    ],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: zha.DeviceType.COLOR_DIMMABLE_LIGHT,
                    SIG_EP_PROFILE: zha.PROFILE_ID,
                }
            },
            ieee=f"11:22:33:44:{i:08x}",
            nwk=0x1234 + i,
        )
        zigpy_dev.node_desc.mac_capability_flags |= (
            zigpy.zdo.types.NodeDescriptor.MACCapabilityFlags.MainsPowered
        )

        zha_gw.get_or_create_device(zigpy_dev)

    # Keep track of request concurrency during initialization
    current_concurrency = 0
    concurrencies = []

    async def mock_send_packet(*args, **kwargs):  # pylint: disable=unused-argument
        """Mock send packet."""
        nonlocal current_concurrency

        current_concurrency += 1
        concurrencies.append(current_concurrency)

        await asyncio.sleep(0.001)

        current_concurrency -= 1
        concurrencies.append(current_concurrency)

    type(zha_gw).radio_concurrency = PropertyMock(return_value=radio_concurrency)
    assert zha_gw.radio_concurrency == radio_concurrency

    with patch(
        "zha.zigbee.device.Device.async_initialize",
        side_effect=mock_send_packet,
    ):
        await zha_gw.async_fetch_updated_state_mains()

    await zha_gw.shutdown()

    # Make sure concurrency was always limited
    assert current_concurrency == 0
    assert min(concurrencies) == 0

    if radio_concurrency > 1:
        assert 1 <= max(concurrencies) < zha_gw.radio_concurrency
    else:
        assert 1 == max(concurrencies) == zha_gw.radio_concurrency


async def test_gateway_device_removed(zha_gateway: Gateway) -> None:
    """Test ZHA device removal."""

    zigpy_dev_basic = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE_BASIC)
    zha_dev_basic = await join_zigpy_device(zha_gateway, zigpy_dev_basic)
    zha_gateway.device_removed(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()
    assert zha_dev_basic.ieee not in zha_gateway.devices


async def test_gateway_device_initialized(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test ZHA device initialization."""

    zigpy_dev_basic = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE_BASIC)
    zha_gateway.async_device_initialized = AsyncMock(
        wraps=zha_gateway.async_device_initialized
    )
    zha_gateway.device_initialized(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()

    assert (
        "Cancelling previous initialization task for device 00:0d:6f:00:0a:90:69:e7"
        not in caplog.text
    )

    assert zha_gateway.async_device_initialized.await_count == 1
    assert zha_gateway.async_device_initialized.await_args == call(zigpy_dev_basic)

    zha_gateway.async_device_initialized.reset_mock()

    # call 2x to make sure cancellation of the task happens
    zha_gateway.device_initialized(zigpy_dev_basic)
    assert (
        "Cancelling previous initialization task for device 00:0d:6f:00:0a:90:69:e7"
        not in caplog.text
    )
    zha_gateway.device_initialized(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()

    assert (
        "Cancelling previous initialization task for device 00:0d:6f:00:0a:90:69:e7"
        in caplog.text
    )


def test_gateway_raw_device_initialized(
    zha_gateway: Gateway,
) -> None:
    """Test Zigpy raw device initialized."""

    zigpy_dev_basic = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE_BASIC)
    zha_gateway.emit = MagicMock(wraps=zha_gateway.emit)
    zha_gateway.raw_device_initialized(zigpy_dev_basic)

    assert zha_gateway.emit.call_count == 1
    assert zha_gateway.emit.call_args == call(
        "raw_device_initialized",
        RawDeviceInitializedEvent(
            device_info=RawDeviceInitializedDeviceInfo(
                ieee=zigpy.types.EUI64.convert("00:0d:6f:00:0a:90:69:e7"),
                nwk=0xB79C,
                pairing_status=DevicePairingStatus.INTERVIEW_COMPLETE,
                model="FakeModel",
                manufacturer="FakeManufacturer",
                signature={
                    "manufacturer": "FakeManufacturer",
                    "model": "FakeModel",
                    "node_desc": {
                        "logical_type": LogicalType.EndDevice,
                        "complex_descriptor_available": 0,
                        "user_descriptor_available": 0,
                        "reserved": 0,
                        "aps_flags": 0,
                        "frequency_band": NodeDescriptor.FrequencyBand.Freq2400MHz,
                        "mac_capability_flags": NodeDescriptor.MACCapabilityFlags.AllocateAddress,
                        "manufacturer_code": 4151,
                        "maximum_buffer_size": 127,
                        "maximum_incoming_transfer_size": 100,
                        "server_mask": 10752,
                        "maximum_outgoing_transfer_size": 100,
                        "descriptor_capability_field": NodeDescriptor.DescriptorCapability.NONE,
                    },
                    "endpoints": {
                        1: {
                            "profile_id": 260,
                            "device_type": zha.DeviceType.ON_OFF_SWITCH,
                            "input_clusters": [0],
                            "output_clusters": [],
                        }
                    },
                },
            ),
            event_type="zha_gateway_message",
            event="raw_device_initialized",
        ),
    )


def test_gateway_device_joined(
    zha_gateway: Gateway,
) -> None:
    """Test Zigpy raw device initialized."""

    zigpy_dev_basic = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE_BASIC)
    zha_gateway.emit = MagicMock(wraps=zha_gateway.emit)
    zha_gateway.device_joined(zigpy_dev_basic)

    assert zha_gateway.emit.call_count == 1
    assert zha_gateway.emit.call_args == call(
        "device_joined",
        DeviceJoinedEvent(
            device_info=DeviceJoinedDeviceInfo(
                ieee=zigpy.types.EUI64.convert("00:0d:6f:00:0a:90:69:e7"),
                nwk=0xB79C,
                pairing_status=DevicePairingStatus.PAIRED,
            )
        ),
    )


def test_gateway_connection_lost(zha_gateway: Gateway) -> None:
    """Test Zigpy raw device initialized."""

    exception = Exception("Test exception")
    zha_gateway.emit = MagicMock(wraps=zha_gateway.emit)
    zha_gateway.connection_lost(exception)

    assert zha_gateway.emit.call_count == 1
    assert zha_gateway.emit.call_args == call(
        ZHA_GW_MSG_CONNECTION_LOST,
        ConnectionLostEvent(
            exception=exception,
            event=ZHA_GW_MSG_CONNECTION_LOST,
            event_type=ZHA_GW_MSG,
        ),
    )


async def test_pollers_skip(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test pollers skip when they should."""

    assert "Global updater interval skipped" not in caplog.text
    assert "Device availability checker interval skipped" not in caplog.text

    assert zha_gateway.config.allow_polling is True
    zha_gateway.config.allow_polling = False
    assert zha_gateway.config.allow_polling is False

    sleep_time = max(
        zha_gateway.global_updater.__polling_interval,
        zha_gateway._device_availability_checker.__polling_interval,
    )
    sleep_time += 2

    await asyncio.sleep(sleep_time)
    await zha_gateway.async_block_till_done(wait_background_tasks=True)

    assert "Global updater interval skipped" in caplog.text
    assert "Device availability checker interval skipped" in caplog.text


async def test_global_updater_guards(
    zha_gateway: Gateway,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test global updater guards."""

    already_registered = (
        "listener already registered with global updater - nothing to register"
    )
    not_registered = "listener not registered with global updater - nothing to remove"

    assert already_registered not in caplog.text
    assert not_registered not in caplog.text

    def listener():
        pass

    zha_gateway.global_updater.register_update_listener(listener)

    assert already_registered not in caplog.text

    zha_gateway.global_updater.register_update_listener(listener)

    assert already_registered in caplog.text

    zha_gateway.global_updater.remove_update_listener(listener)

    assert not_registered not in caplog.text

    zha_gateway.global_updater.remove_update_listener(listener)

    assert not_registered in caplog.text


async def test_gateway_handle_message(
    zha_gateway: Gateway,
) -> None:
    """Test handle message."""

    zigpy_dev_basic = create_mock_zigpy_device(zha_gateway, ZIGPY_DEVICE_BASIC)
    zha_dev_basic = await join_zigpy_device(zha_gateway, zigpy_dev_basic)
    assert zha_dev_basic.available is True
    assert zha_dev_basic.on_network is True

    zha_dev_basic.on_network = False

    assert zha_dev_basic.available is False
    assert zha_dev_basic.on_network is False

    zha_gateway.handle_message(
        zha_dev_basic.device,
        zha.PROFILE_ID,
        general.Basic.cluster_id,
        1,
        1,
        b"",
    )

    assert zha_dev_basic.available is True
    assert zha_dev_basic.on_network is True


def test_radio_type():
    """Test radio type."""

    assert RadioType.list() == [
        "EZSP = Silicon Labs EmberZNet protocol: Elelabs, HUSBZB-1, Telegesis",
        "ZNP = Texas Instruments Z-Stack ZNP protocol: CC253x, CC26x2, CC13x2",
        "deCONZ = dresden elektronik deCONZ protocol: ConBee I/II, RaspBee I/II",
        "ZiGate = ZiGate Zigbee radios: PiZiGate, ZiGate USB-TTL, ZiGate WiFi",
        "XBee = Digi XBee Zigbee radios: Digi XBee Series 2, 2C, 3",
    ]

    assert (
        RadioType.get_by_description(
            "EZSP = Silicon Labs EmberZNet protocol: Elelabs, HUSBZB-1, Telegesis"
        )
        == RadioType.ezsp
    )

    assert RadioType.ezsp.description == (
        "EZSP = Silicon Labs EmberZNet protocol: Elelabs, HUSBZB-1, Telegesis"
    )

    with pytest.raises(ValueError):
        RadioType.get_by_description("Invalid description")
