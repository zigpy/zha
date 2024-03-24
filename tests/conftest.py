"""Test configuration for the ZHA component."""

import asyncio
from collections.abc import Callable
import itertools
import logging
import time
from types import TracebackType
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch
import warnings

import pytest
import zigpy
from zigpy.application import ControllerApplication
import zigpy.config
from zigpy.const import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
import zigpy.device
import zigpy.group
import zigpy.profiles
from zigpy.quirks import get_device
import zigpy.types
from zigpy.zcl.clusters.general import Basic, Groups
from zigpy.zcl.foundation import Status
import zigpy.zdo.types as zdo_t

from tests import common
from zha.application.const import (
    CONF_ALARM_ARM_REQUIRES_CODE,
    CONF_ALARM_FAILED_TRIES,
    CONF_ALARM_MASTER_CODE,
    CONF_ENABLE_ENHANCED_LIGHT_TRANSITION,
    CONF_GROUP_MEMBERS_ASSUME_STATE,
    CONF_RADIO_TYPE,
    CUSTOM_CONFIGURATION,
    ZHA_ALARM_OPTIONS,
    ZHA_OPTIONS,
)
from zha.application.gateway import ZHAGateway
from zha.application.helpers import ZHAData
from zha.zigbee.device import Device

FIXTURE_GRP_ID = 0x1001
FIXTURE_GRP_NAME = "fixture group"
COUNTER_NAMES = ["counter_1", "counter_2", "counter_3"]
_LOGGER = logging.getLogger(__name__)


class _FakeApp(ControllerApplication):
    async def add_endpoint(self, descriptor: zdo_t.SimpleDescriptor):
        pass

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def force_remove(self, dev: zigpy.device.Device):
        pass

    async def load_network_info(self, *, load_devices: bool = False):
        pass

    async def permit_ncp(self, time_s: int = 60):
        pass

    async def permit_with_link_key(
        self, node: zigpy.types.EUI64, link_key: zigpy.types.KeyData, time_s: int = 60
    ):
        pass

    async def reset_network_info(self):
        pass

    async def send_packet(self, packet: zigpy.types.ZigbeePacket):
        pass

    async def start_network(self):
        pass

    async def write_network_info(
        self, *, network_info: zigpy.state.NetworkInfo, node_info: zigpy.state.NodeInfo
    ) -> None:
        pass

    async def request(
        self,
        device: zigpy.device.Device,
        profile: zigpy.types.uint16_t,
        cluster: zigpy.types.uint16_t,
        src_ep: zigpy.types.uint8_t,
        dst_ep: zigpy.types.uint8_t,
        sequence: zigpy.types.uint8_t,
        data: bytes,
        *,
        expect_reply: bool = True,
        use_ieee: bool = False,
        extended_timeout: bool = False,
    ):
        pass

    async def move_network_to_channel(
        self, new_channel: int, *, num_broadcasts: int = 5
    ) -> None:
        pass


def _wrap_mock_instance(obj: Any) -> MagicMock:
    """Auto-mock every attribute and method in an object."""
    mock = create_autospec(obj, spec_set=True, instance=True)

    for attr_name in dir(obj):
        if attr_name.startswith("__") and attr_name not in {"__getitem__"}:
            continue

        real_attr = getattr(obj, attr_name)
        mock_attr = getattr(mock, attr_name)

        if callable(real_attr) and not hasattr(real_attr, "__aenter__"):
            mock_attr.side_effect = real_attr
        else:
            setattr(mock, attr_name, real_attr)

    return mock


@pytest.fixture
async def zigpy_app_controller():
    """Zigpy ApplicationController fixture."""
    app = _FakeApp(
        {
            zigpy.config.CONF_DATABASE: None,
            zigpy.config.CONF_DEVICE: {zigpy.config.CONF_DEVICE_PATH: "/dev/null"},
            zigpy.config.CONF_STARTUP_ENERGY_SCAN: False,
            zigpy.config.CONF_NWK_BACKUP_ENABLED: False,
            zigpy.config.CONF_TOPO_SCAN_ENABLED: False,
            zigpy.config.CONF_OTA: {
                zigpy.config.CONF_OTA_ENABLED: False,
            },
        }
    )

    app.groups.add_group(FIXTURE_GRP_ID, FIXTURE_GRP_NAME, suppress_event=True)

    app.state.node_info.nwk = 0x0000
    app.state.node_info.ieee = zigpy.types.EUI64.convert("00:15:8d:00:02:32:4f:32")
    app.state.network_info.pan_id = 0x1234
    app.state.network_info.extended_pan_id = app.state.node_info.ieee
    app.state.network_info.channel = 15
    app.state.network_info.network_key.key = zigpy.types.KeyData(range(16))
    app.state.counters = zigpy.state.CounterGroups()
    app.state.counters["ezsp_counters"] = zigpy.state.CounterGroup("ezsp_counters")
    for name in COUNTER_NAMES:
        app.state.counters["ezsp_counters"][name].increment()

    # Create a fake coordinator device
    dev = app.add_device(nwk=app.state.node_info.nwk, ieee=app.state.node_info.ieee)
    dev.node_desc = zdo_t.NodeDescriptor()
    dev.node_desc.logical_type = zdo_t.LogicalType.Coordinator
    dev.manufacturer = "Coordinator Manufacturer"
    dev.model = "Coordinator Model"

    ep = dev.add_endpoint(1)
    ep.add_input_cluster(Basic.cluster_id)
    ep.add_input_cluster(Groups.cluster_id)

    with patch("zigpy.device.Device.request", return_value=[Status.SUCCESS]):
        # The mock wrapping accesses deprecated attributes, so we suppress the warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mock_app = _wrap_mock_instance(app)
            mock_app.backups = _wrap_mock_instance(app.backups)

        yield mock_app


@pytest.fixture(name="caplog")
def caplog_fixture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Set log level to debug for tests using the caplog fixture."""
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture
def zha_data() -> ZHAData:
    """Fixture representing zha configuration data."""
    return ZHAData(
        yaml_config={},
        config_entry_data={
            "data": {
                zigpy.config.CONF_DEVICE: {
                    zigpy.config.CONF_DEVICE_PATH: "/dev/ttyUSB0"
                },
                CONF_RADIO_TYPE: "ezsp",
            },
            "options": {
                CUSTOM_CONFIGURATION: {
                    ZHA_OPTIONS: {
                        CONF_ENABLE_ENHANCED_LIGHT_TRANSITION: True,
                        CONF_GROUP_MEMBERS_ASSUME_STATE: False,
                    },
                    ZHA_ALARM_OPTIONS: {
                        CONF_ALARM_ARM_REQUIRES_CODE: False,
                        CONF_ALARM_MASTER_CODE: "4321",
                        CONF_ALARM_FAILED_TRIES: 2,
                    },
                }
            },
        },
    )


class TestGateway:
    """Test ZHA gateway context manager."""

    def __init__(self, data: ZHAData):
        """Initialize the ZHA gateway."""
        self.zha_data: ZHAData = data
        self.zha_gateway: ZHAGateway

    async def __aenter__(self) -> ZHAGateway:
        """Start the ZHA gateway."""
        self.zha_gateway = await ZHAGateway.async_from_config(self.zha_data)
        await self.zha_gateway.async_block_till_done()
        await self.zha_gateway.async_initialize_devices_and_entities()
        return self.zha_gateway

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Shutdown the ZHA gateway."""
        await self.zha_gateway.shutdown()
        await asyncio.sleep(0)


@pytest.fixture
async def zha_gateway(zha_data: ZHAData, zigpy_app_controller, caplog):
    """Set up ZHA component."""

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
        async with TestGateway(zha_data) as gateway:
            yield gateway


@pytest.fixture(scope="session", autouse=True)
def disable_request_retry_delay():
    """Disable ZHA request retrying delay to speed up failures."""

    with patch(
        "zha.zigbee.cluster_handlers.RETRYABLE_REQUEST_DECORATOR",
        zigpy.util.retryable_request(tries=3, delay=0),
    ):
        yield


@pytest.fixture(scope="session", autouse=True)
def globally_load_quirks():
    """Load quirks automatically so that ZHA tests run deterministically in isolation.

    If portions of the ZHA test suite that do not happen to load quirks are run
    independently, bugs can emerge that will show up only when more of the test suite is
    run.
    """

    import zhaquirks  # pylint: disable=import-outside-toplevel

    zhaquirks.setup()


@pytest.fixture
def device_joined(
    zha_gateway: ZHAGateway,  # pylint: disable=redefined-outer-name
) -> Callable[[zigpy.device.Device], Device]:
    """Return a newly joined ZHAWS device."""

    async def _zha_device(zigpy_dev: zigpy.device.Device) -> Device:
        await zha_gateway.async_device_initialized(zigpy_dev)
        await zha_gateway.async_block_till_done()
        return zha_gateway.get_device(zigpy_dev.ieee)

    return _zha_device


@pytest.fixture
def cluster_handler() -> Callable:
    """Clueter handler mock factory fixture."""

    def cluster_handler_factory(
        name: str, cluster_id: int, endpoint_id: int = 1
    ) -> MagicMock:
        ch = MagicMock()
        ch.name = name
        ch.generic_id = f"cluster_handler_0x{cluster_id:04x}"
        ch.id = f"{endpoint_id}:0x{cluster_id:04x}"
        ch.async_configure = AsyncMock()
        ch.async_initialize = AsyncMock()
        return ch

    return cluster_handler_factory


@pytest.fixture
def zigpy_device_mock(
    zigpy_app_controller: ControllerApplication,
) -> Callable[..., zigpy.device.Device]:
    """Make a fake device using the specified cluster classes."""

    def _mock_dev(
        endpoints: dict[int, dict[str, Any]],
        ieee: str = "00:0d:6f:00:0a:90:69:e7",
        manufacturer: str = "FakeManufacturer",
        model: str = "FakeModel",
        node_descriptor: bytes = b"\x02@\x807\x10\x7fd\x00\x00*d\x00\x00",
        nwk: int = 0xB79C,
        patch_cluster: bool = True,
        quirk: Optional[Callable] = None,
        attributes: dict[int, dict[str, dict[str, Any]]] = None,
    ) -> zigpy.device.Device:
        """Make a fake device using the specified cluster classes."""
        device = zigpy.device.Device(
            zigpy_app_controller, zigpy.types.EUI64.convert(ieee), nwk
        )
        device.manufacturer = manufacturer
        device.model = model
        device.node_desc = zdo_t.NodeDescriptor.deserialize(node_descriptor)[0]
        device.last_seen = time.time()

        for epid, ep in endpoints.items():
            endpoint = device.add_endpoint(epid)
            endpoint.device_type = ep[SIG_EP_TYPE]
            endpoint.profile_id = ep.get(SIG_EP_PROFILE)
            endpoint.request = AsyncMock(return_value=[0])

            for cluster_id in ep.get(SIG_EP_INPUT, []):
                endpoint.add_input_cluster(cluster_id)

            for cluster_id in ep.get(SIG_EP_OUTPUT, []):
                endpoint.add_output_cluster(cluster_id)

        if quirk:
            device = quirk(zigpy_app_controller, device.ieee, device.nwk, device)
        else:
            device = get_device(device)

        if patch_cluster:
            for endpoint in (ep for epid, ep in device.endpoints.items() if epid):
                endpoint.request = AsyncMock(return_value=[0])
                for cluster in itertools.chain(
                    endpoint.in_clusters.values(), endpoint.out_clusters.values()
                ):
                    common.patch_cluster(cluster)

        if attributes is not None:
            for ep_id, clusters in attributes.items():
                for cluster_name, attrs in clusters.items():
                    cluster = getattr(device.endpoints[ep_id], cluster_name)

                    for name, value in attrs.items():
                        attr_id = cluster.find_attribute(name).id
                        cluster._attr_cache[attr_id] = value

        return device

    return _mock_dev
