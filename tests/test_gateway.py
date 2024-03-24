"""Test ZHA Gateway."""

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from slugify import slugify
from zigpy.application import ControllerApplication
from zigpy.device import Device as ZigpyDevice
from zigpy.profiles import zha
import zigpy.types
from zigpy.zcl.clusters import general, lighting
import zigpy.zdo.types

from tests.common import async_find_group_entity_id, find_entity_id
from tests.conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
from zha.application import Platform
from zha.application.gateway import ZHAGateway
from zha.application.helpers import ZHAData
from zha.application.platforms import GroupEntity, PlatformEntity
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


def get_entity(zha_dev: Device, entity_id: str) -> PlatformEntity:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in zha_dev.platform_entities.values()
    }
    return entities[entity_id]


def get_group_entity(group: Group, entity_id: str) -> GroupEntity | None:
    """Get entity."""
    entities = {
        entity.PLATFORM + "." + slugify(entity.name, separator="_"): entity
        for entity in group.group_entities.values()
    }

    return entities.get(entity_id)


async def test_device_left(
    zha_gateway: ZHAGateway,
    zigpy_dev_basic: ZigpyDevice,  # pylint: disable=redefined-outer-name
    zha_dev_basic: Device,  # pylint: disable=redefined-outer-name
) -> None:
    """Device leaving the network should become unavailable."""

    assert zha_dev_basic.available is True

    zha_gateway.device_left(zigpy_dev_basic)
    await zha_gateway.async_block_till_done()
    assert zha_dev_basic.available is False


async def test_gateway_group_methods(
    zha_gateway: ZHAGateway,
    device_light_1,  # pylint: disable=redefined-outer-name
    device_light_2,  # pylint: disable=redefined-outer-name
    coordinator,  # pylint: disable=redefined-outer-name
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

    entity_id = async_find_group_entity_id(Platform.LIGHT, zha_group)
    assert entity_id is not None

    entity: GroupEntity | None = get_group_entity(zha_group, entity_id)
    assert entity is not None

    assert isinstance(entity, GroupEntity)
    assert entity is not None

    device_1_entity_id = find_entity_id(Platform.LIGHT, device_light_1)
    device_2_entity_id = find_entity_id(Platform.LIGHT, device_light_2)

    assert device_1_entity_id != device_2_entity_id

    device_1_light_entity = get_entity(device_light_1, device_1_entity_id)
    device_2_light_entity = get_entity(device_light_2, device_2_entity_id)

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
    entity = get_group_entity(zha_group, entity_id)
    assert entity is None

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
    entity = get_group_entity(zha_group, entity_id)
    assert entity is None

    with patch("zigpy.zcl.Cluster.request", side_effect=TimeoutError):
        await zha_group.members[0].async_remove_from_group()
        assert len(zha_group.members) == 1
        for member in zha_group.members:
            assert member.device.ieee in [device_light_1.ieee]


async def test_gateway_create_group_with_id(
    zha_gateway: ZHAGateway,
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


@patch(
    "zha.application.gateway.ZHAGateway.load_devices",
    MagicMock(),
)
@patch(
    "zha.application.gateway.ZHAGateway.load_groups",
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
    zha_data.config_entry_data["data"]["device"]["path"] = device_path
    zha_data.yaml_config["zigpy_config"] = config_override

    with patch(
        "bellows.zigbee.application.ControllerApplication.new",
        return_value=zigpy_app_controller,
    ) as mock_new:
        zha_gw = ZHAGateway(zha_data)
        await zha_gw.async_initialize()
        assert mock_new.mock_calls[-1].kwargs["config"]["use_thread"] is thread_state
        await zha_gw.shutdown()


# pylint: disable=pointless-string-statement
"""TODO
@pytest.mark.parametrize(
    ("device_path", "config_override", "expected_channel"),
    [
        ("/dev/ttyUSB0", {}, None),
        ("socket://192.168.1.123:9999", {}, None),
        ("socket://192.168.1.123:9999", {"network": {"channel": 20}}, 20),
        ("socket://core-silabs-multiprotocol:9999", {}, 15),
        ("socket://core-silabs-multiprotocol:9999", {"network": {"channel": 20}}, 20),
    ],
)
async def test_gateway_force_multi_pan_channel(
    device_path: str,
    config_override: dict,
    expected_channel: int | None,
    zha_data: ZHAData,
) -> None:
    #Test ZHA disabling the UART thread when connecting to a TCP coordinator.
    zha_data.config_entry_data["data"]["device"]["path"] = device_path
    zha_data.yaml_config["zigpy_config"] = config_override
    zha_gw = ZHAGateway(zha_data)

    _, config = zha_gw.get_application_controller_data()
    assert config["network"]["channel"] == expected_channel
"""


@pytest.mark.parametrize("radio_concurrency", [1, 2, 8])
async def test_startup_concurrency_limit(
    radio_concurrency: int,
    zigpy_app_controller: ControllerApplication,
    zha_data: ZHAData,
    zigpy_device_mock,
):
    """Test ZHA gateway limits concurrency on startup."""
    zha_gw = ZHAGateway(zha_data)

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
