"""Test ZHA Core cluster_handlers."""
import math
from typing import Any, Awaitable, Callable
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from zigpy.device import Device as ZigpyDevice
from zigpy.endpoint import Endpoint as ZigpyEndpoint
import zigpy.profiles.zha
import zigpy.types as t
import zigpy.zcl.clusters

from zhaws.server.zigbee import registries
from zhaws.server.zigbee.cluster import ClusterHandler
import zhaws.server.zigbee.cluster.const as zha_const
from zhaws.server.zigbee.cluster.general import PollControl
from zhaws.server.zigbee.device import Device
from zhaws.server.zigbee.endpoint import Endpoint

from .conftest import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE

from tests.common import make_zcl_header


@pytest.fixture
def ieee():
    """IEEE fixture."""
    return t.EUI64.deserialize(b"ieeeaddr")[0]


@pytest.fixture
def nwk():
    """NWK fixture."""
    return t.NWK(0xBEEF)


@pytest.fixture
def zigpy_coordinator_device(
    zigpy_device_mock: Callable[..., ZigpyDevice]
) -> ZigpyDevice:
    """Coordinator device fixture."""

    coordinator = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [0x1000],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
        nwk=0x0000,
    )
    coordinator.add_to_group = AsyncMock(return_value=[0])
    return coordinator


@pytest.fixture
def endpoint(zigpy_coordinator_device: ZigpyDevice) -> Endpoint:
    """Endpoint cluster_handlers fixture."""
    endpoint_mock = mock.MagicMock(spec_set=Endpoint)
    endpoint_mock.zigpy_endpoint.device.application.get_device.return_value = (
        zigpy_coordinator_device
    )
    endpoint_mock.device.skip_configuration = False
    endpoint_mock.id = 1
    return endpoint_mock


@pytest.fixture
def poll_control_ch(
    endpoint: Endpoint, zigpy_device_mock: Callable[..., ZigpyDevice]
) -> PollControl:
    """Poll control cluster_handler fixture."""
    cluster_id = zigpy.zcl.clusters.general.PollControl.cluster_id
    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster = zigpy_dev.endpoints[1].in_clusters[cluster_id]
    cluster_handler_class = registries.CLUSTER_HANDLER_REGISTRY.get(cluster_id)
    return cluster_handler_class(cluster, endpoint)


@pytest.fixture
async def poll_control_device(
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> Device:
    """Poll control device fixture."""
    cluster_id = zigpy.zcl.clusters.general.PollControl.cluster_id
    zigpy_dev = zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [cluster_id],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    zha_device = await device_joined(zigpy_dev)
    return zha_device


@pytest.mark.parametrize(
    "cluster_id, bind_count, attrs",
    [
        (0x0000, 0, {}),
        (0x0001, 1, {"battery_voltage", "battery_percentage_remaining"}),
        (0x0003, 0, {}),
        (0x0004, 0, {}),
        (0x0005, 1, {}),
        (0x0006, 1, {"on_off"}),
        (0x0007, 1, {}),
        (0x0008, 1, {"current_level"}),
        (0x0009, 1, {}),
        (0x000C, 1, {"present_value"}),
        (0x000D, 1, {"present_value"}),
        (0x000E, 1, {"present_value"}),
        (0x000D, 1, {"present_value"}),
        (0x0010, 1, {"present_value"}),
        (0x0011, 1, {"present_value"}),
        (0x0012, 1, {"present_value"}),
        (0x0013, 1, {"present_value"}),
        (0x0014, 1, {"present_value"}),
        (0x0015, 1, {}),
        (0x0016, 1, {}),
        (0x0019, 0, {}),
        (0x001A, 1, {}),
        (0x001B, 1, {}),
        (0x0020, 1, {}),
        (0x0021, 0, {}),
        (0x0101, 1, {"lock_state"}),
        (
            0x0201,
            1,
            {
                "local_temperature",
                "occupied_cooling_setpoint",
                "occupied_heating_setpoint",
                "unoccupied_cooling_setpoint",
                "unoccupied_heating_setpoint",
                "running_mode",
                "running_state",
                "system_mode",
                "occupancy",
                "pi_cooling_demand",
                "pi_heating_demand",
            },
        ),
        (0x0202, 1, {"fan_mode"}),
        (0x0300, 1, {"current_x", "current_y", "color_temperature"}),
        (0x0400, 1, {"measured_value"}),
        (0x0401, 1, {"level_status"}),
        (0x0402, 1, {"measured_value"}),
        (0x0403, 1, {"measured_value"}),
        (0x0404, 1, {"measured_value"}),
        (0x0405, 1, {"measured_value"}),
        (0x0406, 1, {"occupancy"}),
        (0x0702, 1, {"instantaneous_demand"}),
        (
            0x0B04,
            1,
            {
                "active_power",
                "active_power_max",
                "apparent_power",
                "rms_current",
                "rms_current_max",
                "rms_voltage",
                "rms_voltage_max",
            },
        ),
    ],
)
async def test_in_cluster_handler_config(
    cluster_id: int,
    bind_count: int,
    attrs: dict[str, Any],
    endpoint: Endpoint,
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> None:
    """Test ZHA core cluster_handler configuration for input clusters."""
    zigpy_dev = zigpy_device_mock(
        {1: {SIG_EP_INPUT: [cluster_id], SIG_EP_OUTPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster = zigpy_dev.endpoints[1].in_clusters[cluster_id]
    cluster_handler_class = registries.CLUSTER_HANDLER_REGISTRY.get(
        cluster_id, ClusterHandler
    )
    cluster_handler = cluster_handler_class(cluster, endpoint)

    await cluster_handler.async_configure()

    assert cluster.bind.call_count == bind_count
    assert cluster.configure_reporting.call_count == 0
    assert cluster.configure_reporting_multiple.call_count == math.ceil(len(attrs) / 3)
    reported_attrs = {
        a
        for a in attrs
        for attr in cluster.configure_reporting_multiple.call_args_list
        for attrs in attr[0][0]
    }
    assert set(attrs) == reported_attrs


@pytest.mark.parametrize(
    "cluster_id, bind_count",
    [
        (0x0000, 0),
        (0x0001, 1),
        (0x0002, 1),
        (0x0003, 0),
        (0x0004, 0),
        (0x0005, 1),
        (0x0006, 1),
        (0x0007, 1),
        (0x0008, 1),
        (0x0009, 1),
        (0x0015, 1),
        (0x0016, 1),
        (0x0019, 0),
        (0x001A, 1),
        (0x001B, 1),
        (0x0020, 1),
        (0x0021, 0),
        (0x0101, 1),
        (0x0202, 1),
        (0x0300, 1),
        (0x0400, 1),
        (0x0402, 1),
        (0x0403, 1),
        (0x0405, 1),
        (0x0406, 1),
        (0x0702, 1),
        (0x0B04, 1),
    ],
)
async def test_out_cluster_handler_config(
    cluster_id: int,
    bind_count: int,
    endpoint: Endpoint,
    zigpy_device_mock: Callable[..., ZigpyDevice],
) -> None:
    """Test ZHA core cluster_handler configuration for output clusters."""
    zigpy_dev = zigpy_device_mock(
        {1: {SIG_EP_OUTPUT: [cluster_id], SIG_EP_INPUT: [], SIG_EP_TYPE: 0x1234}},
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )

    cluster = zigpy_dev.endpoints[1].out_clusters[cluster_id]
    cluster.bind_only = True
    cluster_handler_class = registries.CLUSTER_HANDLER_REGISTRY.get(
        cluster_id, ClusterHandler
    )
    cluster_handler = cluster_handler_class(cluster, endpoint)

    await cluster_handler.async_configure()

    assert cluster.bind.call_count == bind_count
    assert cluster.configure_reporting.call_count == 0


def test_cluster_handler_registry() -> None:
    """Test ZIGBEE cluster_handler Registry."""
    for (
        cluster_id,
        cluster_handler,
    ) in registries.CLUSTER_HANDLER_REGISTRY.items():
        assert isinstance(cluster_id, int)
        assert 0 <= cluster_id <= 0xFFFF
        assert issubclass(cluster_handler, ClusterHandler)


def test_epch_unclaimed_cluster_handlers(cluster_handler: ClusterHandler) -> None:
    """Test unclaimed cluster_handlers."""

    ch_1 = cluster_handler(zha_const.CLUSTER_HANDLER_ON_OFF, 6)
    ch_2 = cluster_handler(zha_const.CLUSTER_HANDLER_LEVEL, 8)
    ch_3 = cluster_handler(zha_const.CLUSTER_HANDLER_COLOR, 768)

    ep_cluster_handlers = Endpoint(
        mock.MagicMock(spec_set=ZigpyEndpoint), mock.MagicMock(spec_set=Device)
    )
    all_cluster_handlers = {ch_1.id: ch_1, ch_2.id: ch_2, ch_3.id: ch_3}
    with mock.patch.dict(
        ep_cluster_handlers.all_cluster_handlers, all_cluster_handlers, clear=True
    ):
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 in available
        assert ch_2 in available
        assert ch_3 in available

        ep_cluster_handlers.claimed_cluster_handlers[ch_2.id] = ch_2
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 in available
        assert ch_2 not in available
        assert ch_3 in available

        ep_cluster_handlers.claimed_cluster_handlers[ch_1.id] = ch_1
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 not in available
        assert ch_2 not in available
        assert ch_3 in available

        ep_cluster_handlers.claimed_cluster_handlers[ch_3.id] = ch_3
        available = ep_cluster_handlers.unclaimed_cluster_handlers()
        assert ch_1 not in available
        assert ch_2 not in available
        assert ch_3 not in available


def test_epch_claim_cluster_handlers(cluster_handler: ClusterHandler) -> None:
    """Test cluster_handler claiming."""

    ch_1 = cluster_handler(zha_const.CLUSTER_HANDLER_ON_OFF, 6)
    ch_2 = cluster_handler(zha_const.CLUSTER_HANDLER_LEVEL, 8)
    ch_3 = cluster_handler(zha_const.CLUSTER_HANDLER_COLOR, 768)

    ep_cluster_handlers = Endpoint(
        mock.MagicMock(spec_set=ZigpyEndpoint), mock.MagicMock(spec_set=Device)
    )
    all_cluster_handlers = {ch_1.id: ch_1, ch_2.id: ch_2, ch_3.id: ch_3}
    with mock.patch.dict(
        ep_cluster_handlers.all_cluster_handlers, all_cluster_handlers, clear=True
    ):
        assert ch_1.id not in ep_cluster_handlers.claimed_cluster_handlers
        assert ch_2.id not in ep_cluster_handlers.claimed_cluster_handlers
        assert ch_3.id not in ep_cluster_handlers.claimed_cluster_handlers

        ep_cluster_handlers.claim_cluster_handlers([ch_2])
        assert ch_1.id not in ep_cluster_handlers.claimed_cluster_handlers
        assert ch_2.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_2.id] is ch_2
        assert ch_3.id not in ep_cluster_handlers.claimed_cluster_handlers

        ep_cluster_handlers.claim_cluster_handlers([ch_3, ch_1])
        assert ch_1.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_1.id] is ch_1
        assert ch_2.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_2.id] is ch_2
        assert ch_3.id in ep_cluster_handlers.claimed_cluster_handlers
        assert ep_cluster_handlers.claimed_cluster_handlers[ch_3.id] is ch_3
        assert "1:0x0300" in ep_cluster_handlers.claimed_cluster_handlers


@mock.patch("zhaws.server.zigbee.endpoint.Endpoint.add_client_cluster_handlers")
@mock.patch(
    "zhaws.server.platforms.discovery.PROBE.discover_entities",
    mock.MagicMock(),
)
async def test_ep_cluster_handlers_all_cluster_handlers(
    m1,
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> None:
    """Test Endpointcluster_handlers adding all cluster_handlers."""
    zha_device = await device_joined(
        zigpy_device_mock(
            {
                1: {
                    SIG_EP_INPUT: [0, 1, 6, 8],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.ON_OFF_SWITCH,
                    SIG_EP_PROFILE: 0x0104,
                },
                2: {
                    SIG_EP_INPUT: [0, 1, 6, 8, 768],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
            }
        )
    )
    assert "1:0x0000" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0001" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0006" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0008" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0300" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0000" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0001" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0006" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0008" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0300" not in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0000" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0001" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0006" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0008" not in zha_device._endpoints[2].all_cluster_handlers
    assert "1:0x0300" not in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0000" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0006" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0008" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0300" in zha_device._endpoints[2].all_cluster_handlers


@mock.patch("zhaws.server.zigbee.endpoint.Endpoint.add_client_cluster_handlers")
@mock.patch(
    "zhaws.server.platforms.discovery.PROBE.discover_entities",
    mock.MagicMock(),
)
async def test_cluster_handler_power_config(
    m1,
    zigpy_device_mock: Callable[..., ZigpyDevice],
    device_joined: Callable[[ZigpyDevice], Awaitable[Device]],
) -> None:
    """Test that cluster_handlers only get a single power cluster_handler."""
    in_clusters = [0, 1, 6, 8]
    zha_device: Device = await device_joined(
        zigpy_device_mock(
            endpoints={
                1: {
                    SIG_EP_INPUT: in_clusters,
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
                2: {
                    SIG_EP_INPUT: [*in_clusters, 768],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
            },
            ieee="01:2d:6f:00:0a:90:69:e8",
        )
    )
    assert "1:0x0000" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0001" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0006" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0008" in zha_device._endpoints[1].all_cluster_handlers
    assert "1:0x0300" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0000" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0006" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0008" in zha_device._endpoints[2].all_cluster_handlers
    assert "2:0x0300" in zha_device._endpoints[2].all_cluster_handlers

    zha_device = await device_joined(
        zigpy_device_mock(
            endpoints={
                1: {
                    SIG_EP_INPUT: [],
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
                2: {
                    SIG_EP_INPUT: in_clusters,
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                },
            },
            ieee="02:2d:6f:00:0a:90:69:e8",
        )
    )
    assert "1:0x0001" not in zha_device._endpoints[1].all_cluster_handlers
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers

    zha_device = await device_joined(
        zigpy_device_mock(
            endpoints={
                2: {
                    SIG_EP_INPUT: in_clusters,
                    SIG_EP_OUTPUT: [],
                    SIG_EP_TYPE: 0x0000,
                    SIG_EP_PROFILE: 0x0104,
                }
            },
            ieee="03:2d:6f:00:0a:90:69:e8",
        )
    )
    assert "2:0x0001" in zha_device._endpoints[2].all_cluster_handlers


"""
async def test_ep_cluster_handlers_configure(cluster_handler: ClusterHandler) -> None:
    # Test unclaimed cluster_handlers.

    ch_1 = cluster_handler(zha_const.CLUSTER_HANDLER_ON_OFF, 6)
    ch_2 = cluster_handler(zha_const.CLUSTER_HANDLER_LEVEL, 8)
    ch_3 = cluster_handler(zha_const.CLUSTER_HANDLER_COLOR, 768)
    ch_3.async_configure = AsyncMock(side_effect=asyncio.TimeoutError)
    ch_3.async_initialize = AsyncMock(side_effect=asyncio.TimeoutError)
    ch_4 = cluster_handler(zha_const.CLUSTER_HANDLER_ON_OFF, 6)
    ch_5 = cluster_handler(zha_const.CLUSTER_HANDLER_LEVEL, 8)
    ch_5.async_configure = AsyncMock(side_effect=asyncio.TimeoutError)
    ch_5.async_initialize = AsyncMock(side_effect=asyncio.TimeoutError)
    ep_cluster_handlers = Endpoint(
        mock.MagicMock(spec_set=ZigpyEndpoint), mock.MagicMock(spec_set=Device)
    )
    type(ep_cluster_handlers.device.return_value).semaphore = PropertyMock(
        return_value=asyncio.Semaphore(3)
    )

    claimed = {ch_1.id: ch_1, ch_2.id: ch_2, ch_3.id: ch_3}
    client_chans = {ch_4.id: ch_4, ch_5.id: ch_5}

    with mock.patch.dict(
        ep_cluster_handlers.claimed_cluster_handlers, claimed, clear=True
    ), mock.patch.dict(
        ep_cluster_handlers.client_cluster_handlers, client_chans, clear=True
    ):
        await ep_cluster_handlers.async_configure()
        await ep_cluster_handlers.async_initialize(False)

    for ch in [*claimed.values(), *client_chans.values()]:
        assert ch.async_configure.call_count == 1
        assert ch.async_configure.await_count == 1
        assert ch.async_initialize.call_count == 1
        assert ch.async_initialize.await_count == 1
        assert ch.async_initialize.call_args[0][0] is False

    assert ch_3.warning.call_count == 2
    assert ch_5.warning.call_count == 2
"""


async def test_poll_control_configure(poll_control_ch: PollControl) -> None:
    """Test poll control cluster_handler configuration."""
    await poll_control_ch.async_configure()
    assert poll_control_ch.cluster.write_attributes.call_count == 1
    assert poll_control_ch.cluster.write_attributes.call_args[0][0] == {
        "checkin_interval": poll_control_ch.CHECKIN_INTERVAL
    }


async def test_poll_control_checkin_response(poll_control_ch: PollControl) -> None:
    """Test poll control cluster_handler checkin response."""
    rsp_mock = AsyncMock()
    set_interval_mock = AsyncMock()
    fast_poll_mock = AsyncMock()
    cluster = poll_control_ch.cluster
    patch_1 = mock.patch.object(cluster, "checkin_response", rsp_mock)
    patch_2 = mock.patch.object(cluster, "set_long_poll_interval", set_interval_mock)
    patch_3 = mock.patch.object(cluster, "fast_poll_stop", fast_poll_mock)

    with patch_1, patch_2, patch_3:
        await poll_control_ch.check_in_response(33)

    assert rsp_mock.call_count == 1
    assert set_interval_mock.call_count == 1
    assert fast_poll_mock.call_count == 1

    await poll_control_ch.check_in_response(33)
    assert cluster.endpoint.request.call_count == 3
    assert cluster.endpoint.request.await_count == 3
    assert cluster.endpoint.request.call_args_list[0][0][1] == 33
    assert cluster.endpoint.request.call_args_list[0][0][0] == 0x0020
    assert cluster.endpoint.request.call_args_list[1][0][0] == 0x0020


async def test_poll_control_cluster_command(poll_control_device: Device) -> None:
    """Test poll control cluster_handler response to cluster command."""
    checkin_mock = AsyncMock()
    poll_control_ch = poll_control_device._endpoints[1].all_cluster_handlers["1:0x0020"]
    cluster = poll_control_ch.cluster
    # events = async_capture_events("zha_event")

    with mock.patch.object(poll_control_ch, "check_in_response", checkin_mock):
        tsn = 22
        hdr = make_zcl_header(0, global_command=False, tsn=tsn)
        cluster.handle_message(
            hdr, [mock.sentinel.args, mock.sentinel.args2, mock.sentinel.args3]
        )
        await poll_control_device.controller.server.block_till_done()

    assert checkin_mock.call_count == 1
    assert checkin_mock.await_count == 1
    assert checkin_mock.await_args[0][0] == tsn

    """
    assert len(events) == 1
    data = events[0].data
    assert data["command"] == "checkin"
    assert data["args"][0] is mock.sentinel.args
    assert data["args"][1] is mock.sentinel.args2
    assert data["args"][2] is mock.sentinel.args3
    assert data["unique_id"] == "00:11:22:33:44:55:66:77:1:0x0020"
    assert data["device_id"] == poll_control_device.device_id
    """


async def test_poll_control_ignore_list(poll_control_device: Device) -> None:
    """Test poll control cluster_handler ignore list."""
    set_long_poll_mock = AsyncMock()
    poll_control_ch = poll_control_device._endpoints[1].all_cluster_handlers["1:0x0020"]
    cluster = poll_control_ch.cluster

    with mock.patch.object(cluster, "set_long_poll_interval", set_long_poll_mock):
        await poll_control_ch.check_in_response(33)

    assert set_long_poll_mock.call_count == 1

    set_long_poll_mock.reset_mock()
    poll_control_ch.skip_manufacturer_id(4151)
    with mock.patch.object(cluster, "set_long_poll_interval", set_long_poll_mock):
        await poll_control_ch.check_in_response(33)

    assert set_long_poll_mock.call_count == 0


async def test_poll_control_ikea(poll_control_device: Device) -> None:
    """Test poll control cluster_handler ignore list for ikea."""
    set_long_poll_mock = AsyncMock()
    poll_control_ch = poll_control_device._endpoints[1].all_cluster_handlers["1:0x0020"]
    cluster = poll_control_ch.cluster

    poll_control_device.device.node_desc.manufacturer_code = 4476
    with mock.patch.object(cluster, "set_long_poll_interval", set_long_poll_mock):
        await poll_control_ch.check_in_response(33)

    assert set_long_poll_mock.call_count == 0


@pytest.fixture
def zigpy_zll_device(zigpy_device_mock: Callable[..., ZigpyDevice]) -> ZigpyDevice:
    """ZLL device fixture."""

    return zigpy_device_mock(
        {
            1: {
                SIG_EP_INPUT: [0x1000],
                SIG_EP_OUTPUT: [],
                SIG_EP_TYPE: 0x1234,
                SIG_EP_PROFILE: 0x0104,
            }
        },
        "00:11:22:33:44:55:66:77",
        "test manufacturer",
        "test model",
    )


"""
async def test_zll_device_groups(
    zigpy_zll_device: ZigpyDevice,
    endpoint: Endpoint,
    zigpy_coordinator_device: ZigpyDevice,
) -> None:
    #Test adding coordinator to ZLL groups.

    cluster = zigpy_zll_device.endpoints[1].lightlink
    cluster_handler = LightLink(cluster, endpoint)
    get_group_identifiers_rsp = zigpy.zcl.clusters.lightlink.LightLink.commands_by_name[
        "get_group_identifiers_rsp"
    ].schema

    with patch.object(
        cluster,
        "get_group_identifiers",
        AsyncMock(
            return_value=get_group_identifiers_rsp(
                total=0, start_index=0, group_info_records=[]
            )
        ),
    ) as cmd_mock:
        await cluster_handler.async_configure()
        assert cmd_mock.await_count == 1
        assert (
            cluster.server_commands[cmd_mock.await_args[0][0]].name
            == "get_group_identifiers"
        )
        assert cluster.bind.call_count == 0
        assert zigpy_coordinator_device.add_to_group.await_count == 1
        assert zigpy_coordinator_device.add_to_group.await_args[0][0] == 0x0000

    zigpy_coordinator_device.add_to_group.reset_mock()
    group_1 = zigpy.zcl.clusters.lightlink.GroupInfoRecord(0xABCD, 0x00)
    group_2 = zigpy.zcl.clusters.lightlink.GroupInfoRecord(0xAABB, 0x00)
    with patch.object(
        cluster,
        "get_group_identifiers",
        AsyncMock(
            return_value=get_group_identifiers_rsp(
                total=2, start_index=0, group_info_records=[group_1, group_2]
            )
        ),
    ) as cmd_mock:
        await cluster_handler.async_configure()
        assert cmd_mock.await_count == 1
        assert (
            cluster.server_commands[cmd_mock.await_args[0][0]].name
            == "get_group_identifiers"
        )
        assert cluster.bind.call_count == 0
        assert zigpy_coordinator_device.add_to_group.await_count == 2
        assert (
            zigpy_coordinator_device.add_to_group.await_args_list[0][0][0]
            == group_1.group_id
        )
        assert (
            zigpy_coordinator_device.add_to_group.await_args_list[1][0][0]
            == group_2.group_id
        )
"""
