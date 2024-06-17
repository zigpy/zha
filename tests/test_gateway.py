"""Test ZHA Gateway."""

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, PropertyMock, call, patch

import pytest
from zigpy.application import ControllerApplication
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl.clusters import general, lighting
import zigpy.zdo.types
from zigpy.zdo.types import LogicalType, NodeDescriptor

from tests.common import get_entity, get_group_entity
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
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
from zha.application.platforms.light.const import LightEntityFeature
from zha.zigbee.device import Device
from zha.zigbee.group import Group, GroupMemberReference

IEEE_GROUPABLE_DEVICE = "01:2d:6f:00:0a:90:69:e8"
IEEE_GROUPABLE_DEVICE2 = "02:2d:6f:00:0a:90:69:e8"


@pytest.fixture
def zigpy_dev_basic(zigpy_device_mock: Callable[..., ZigpyDevice]) -> ZigpyDevice:
    """Zigpy device with just a basic cluster."""
    return zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [general.Basic.cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: zha.DeviceType.ON_OFF_SWITCH,
                SIG_EP_PROFILE: zha.PROFILE_ID,
            }
        }
    )


@pytest.fixture
async def zha_dev_basic(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
) -> Device:
    """ZHA device with just a basic cluster."""

    zha_device = await device_joined(zigpy_dev_basic)
    return zha_device


@pytest.fixture
async def coordinator(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Test ZHA light platform."""

    zigpy_device = zigpy_device_mock(
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
        node_descriptor=b"\xf8\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff",
    )
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_1(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Test ZHA light platform."""

    zigpy_device = zigpy_device_mock(
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
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


@pytest.fixture
async def device_light_2(
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> Device:
    """Test ZHA light platform."""

    zigpy_device = zigpy_device_mock(
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
    zha_device = await device_joined(zigpy_device)
    zha_device.available = True
    return zha_device


async def test_device_left(
    zha_gateway: Gateway,
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_dev_basic: Device,  # pylint: disable=redefined-outer-name
) -> None:
    """Device leaving the network should become unavailable."""

    assert zha_dev_basic.available is True

    zha_gateway.device_left(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()
    assert zha_dev_basic.available is False
    assert zha_dev_basic.on_network is False


async def test_gateway_group_methods(
    zha_gateway: Gateway,
    device_light_1,  # pylint: disable=redefined-outer-name
    device_light_2,  # pylint: disable=redefined-outer-name
    coordinator,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test creating a group with 2 members."""

    zha_gateway.coordinator_zha_device = coordinator
    coordinator._zha_gateway = zha_gateway
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
    assert info.effect_list is None

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


async def test_gateway_create_group_with_id_without_id(
    zha_gateway: Gateway,
    device_light_1,  # pylint: disable=redefined-outer-name
    coordinator,  # pylint: disable=redefined-outer-name
) -> None:
    """Test creating a group with a specific ID."""

    assert zha_gateway is not None
    zha_gateway.coordinator_zha_device = coordinator
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


@patch(
    "zha.application.gateway.Gateway.load_devices",
    MagicMock(),
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
        assert mock_new.mock_calls[-1].kwargs["config"][CONF_USE_THREAD] is thread_state
        await zha_gw.shutdown()


@pytest.mark.parametrize("radio_concurrency", [1, 2, 8])
@pytest.mark.looptime
async def test_startup_concurrency_limit(
    radio_concurrency: int,
    zigpy_app_controller: ControllerApplication,
    zha_data: ZHAData,
    zigpy_device_mock,
):
    """Test ZHA gateway limits concurrency on startup."""
    zha_gw = Gateway(zha_data)

    with patch(
        "bellows.zigbee.application.ControllerApplication.new",
        return_value=zigpy_app_controller,
    ):
        await zha_gw.async_initialize()

    for i in range(50):
        zigpy_dev = zigpy_device_mock(
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


async def test_gateway_device_removed(
    zha_gateway: Gateway,
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_dev_basic: Device,  # pylint: disable=redefined-outer-name
) -> None:
    """Test ZHA device removal."""

    zha_gateway.device_removed(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()
    assert zha_dev_basic.ieee not in zha_gateway.devices


async def test_gateway_device_initialized(
    zha_gateway: Gateway,
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test ZHA device initialization."""

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
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
) -> None:
    """Test Zigpy raw device initialized."""

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
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
) -> None:
    """Test Zigpy raw device initialized."""

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


@pytest.mark.looptime
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


async def test_gateway_handle_message(
    zha_gateway: Gateway,
    zha_dev_basic: Device,  # pylint: disable=redefined-outer-name
) -> None:
    """Test handle message."""

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
