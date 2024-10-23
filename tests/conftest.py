"""Test configuration for the ZHA component."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import contextmanager
import logging
import os
import reprlib
import threading
from types import TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp.test_utils
import pytest
import zigpy
from zigpy.application import ControllerApplication
import zigpy.config
import zigpy.device
import zigpy.group
import zigpy.profiles
import zigpy.types
from zigpy.zcl.clusters.general import Basic, Groups
from zigpy.zcl.foundation import Status
import zigpy.zdo.types as zdo_t

from zha.application import Platform
from zha.application.gateway import Gateway, WebSocketServerGateway
from zha.application.helpers import (
    AlarmControlPanelOptions,
    CoordinatorConfiguration,
    LightOptions,
    ServerConfiguration,
    ZHAConfiguration,
    ZHAData,
)
from zha.async_ import ZHAJob
from zha.websocket.client.controller import Controller

FIXTURE_GRP_ID = 0x1001
FIXTURE_GRP_NAME = "fixture group"
COUNTER_NAMES = ["counter_1", "counter_2", "counter_3"]
INSTANCES: list[Gateway] = []
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


@contextmanager
def long_repr_strings() -> Generator[None, None, None]:
    """Increase reprlib maxstring and maxother to 300."""
    arepr = reprlib.aRepr
    original_maxstring = arepr.maxstring
    original_maxother = arepr.maxother
    arepr.maxstring = 300
    arepr.maxother = 300
    try:
        yield
    finally:
        arepr.maxstring = original_maxstring
        arepr.maxother = original_maxother


@pytest.fixture(autouse=True)
def expected_lingering_tasks() -> bool:
    """Temporary ability to bypass test failures.

    Parametrize to True to bypass the pytest failure.
    @pytest.mark.parametrize("expected_lingering_tasks", [True])

    This should be removed when all lingering tasks have been cleaned up.
    """
    return False


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Temporary ability to bypass test failures.

    Parametrize to True to bypass the pytest failure.
    @pytest.mark.parametrize("expected_lingering_timers", [True])

    This should be removed when all lingering timers have been cleaned up.
    """
    current_test = os.getenv("PYTEST_CURRENT_TEST")
    if (
        current_test
        and current_test.startswith("tests/components/")
        and current_test.split("/")[2] not in {platform.value for platform in Platform}
    ):
        # As a starting point, we ignore non-platform components
        return True
    return False


@pytest.fixture(autouse=True)
def verify_cleanup(
    event_loop: asyncio.AbstractEventLoop,
    expected_lingering_tasks: bool,  # pylint: disable=redefined-outer-name
    expected_lingering_timers: bool,  # pylint: disable=redefined-outer-name
) -> Generator[None, None, None]:
    """Verify that the test has cleaned up resources correctly."""
    threads_before = frozenset(threading.enumerate())
    tasks_before = asyncio.all_tasks(event_loop)
    yield

    event_loop.run_until_complete(event_loop.shutdown_default_executor())

    if len(INSTANCES) >= 2:
        count = len(INSTANCES)
        for inst in INSTANCES:
            inst.stop()
        pytest.exit(f"Detected non stopped instances ({count}), aborting test run")

    # Warn and clean-up lingering tasks and timers
    # before moving on to the next test.
    tasks = asyncio.all_tasks(event_loop) - tasks_before
    for task in tasks:
        if expected_lingering_tasks:
            _LOGGER.warning("Lingering task after test %r", task)
        else:
            pytest.fail(f"Lingering task after test {task!r}")
        task.cancel()
    if tasks:
        event_loop.run_until_complete(asyncio.wait(tasks))

    for handle in event_loop._scheduled:  # type: ignore[attr-defined]
        if not handle.cancelled():
            with long_repr_strings():
                if expected_lingering_timers:
                    _LOGGER.warning("Lingering timer after test %r", handle)
                elif handle._args and isinstance(job := handle._args[-1], ZHAJob):
                    if job.cancel_on_shutdown:
                        continue
                    pytest.fail(f"Lingering timer after job {job!r}")
                else:
                    pytest.fail(f"Lingering timer after test {handle!r}")
                handle.cancel()

    # Verify no threads where left behind.
    threads = frozenset(threading.enumerate()) - threads_before
    for thread in threads:
        assert isinstance(thread, threading._DummyThread) or thread.name.startswith(
            "waitpid-"
        )


@pytest.fixture(name="zigpy_app_controller")
async def zigpy_app_controller_fixture():
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
    dev.node_desc = zdo_t.NodeDescriptor(
        logical_type=zdo_t.LogicalType.Coordinator,
        complex_descriptor_available=0,
        user_descriptor_available=0,
        reserved=0,
        aps_flags=0,
        frequency_band=zdo_t.NodeDescriptor.FrequencyBand.Freq2400MHz,
        mac_capability_flags=zdo_t.NodeDescriptor.MACCapabilityFlags.AllocateAddress,
        manufacturer_code=0x1234,
        maximum_buffer_size=127,
        maximum_incoming_transfer_size=100,
        server_mask=10752,
        maximum_outgoing_transfer_size=100,
        descriptor_capability_field=zdo_t.NodeDescriptor.DescriptorCapability.NONE,
    )
    dev.node_desc.logical_type = zdo_t.LogicalType.Coordinator
    dev.manufacturer = "Coordinator Manufacturer"
    dev.model = "Coordinator Model"

    ep = dev.add_endpoint(1)
    ep.add_input_cluster(Basic.cluster_id)
    ep.add_input_cluster(Groups.cluster_id)

    with patch("zigpy.device.Device.request", return_value=[Status.SUCCESS]):
        yield app


@pytest.fixture(name="caplog")
def caplog_fixture(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Set log level to debug for tests using the caplog fixture."""
    caplog.set_level(logging.DEBUG)
    return caplog


@pytest.fixture(name="zha_data")
def zha_data_fixture() -> ZHAData:
    """Fixture representing zha configuration data."""
    port = aiohttp.test_utils.unused_port()
    return ZHAData(
        config=ZHAConfiguration(
            coordinator_configuration=CoordinatorConfiguration(
                radio_type="ezsp",
                path="/dev/ttyUSB0",
            ),
            light_options=LightOptions(
                enable_enhanced_light_transition=True,
                group_members_assume_state=True,
            ),
            alarm_control_panel_options=AlarmControlPanelOptions(
                arm_requires_code=False,
                master_code="4321",
                failed_tries=2,
            ),
        ),
        server_config=ServerConfiguration(
            host="localhost",
            port=port,
            network_auto_start=False,
        ),
    )


class TestGateway:
    """Test ZHA gateway context manager."""

    def __init__(self, data: ZHAData):
        """Initialize the ZHA gateway."""
        self.zha_data: ZHAData = data
        self.zha_gateway: Gateway

    async def __aenter__(self) -> Gateway:
        """Start the ZHA gateway."""
        self.zha_gateway = await Gateway.async_from_config(self.zha_data)
        await self.zha_gateway.async_initialize()
        await self.zha_gateway.async_block_till_done()
        await self.zha_gateway.async_initialize_devices_and_entities()
        INSTANCES.append(self.zha_gateway)
        return self.zha_gateway

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Shutdown the ZHA gateway."""
        INSTANCES.remove(self.zha_gateway)
        await self.zha_gateway.shutdown()
        await asyncio.sleep(0)


@pytest.fixture
async def connected_client_and_server(
    zha_data: ZHAData,
    zigpy_app_controller: ControllerApplication,
    caplog: pytest.LogCaptureFixture,  # pylint: disable=unused-argument
) -> AsyncGenerator[tuple[Controller, WebSocketServerGateway], None]:
    """Return the connected client and server fixture."""

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
        ws_gateway = await WebSocketServerGateway.async_from_config(zha_data)
        await ws_gateway.async_initialize()
        await ws_gateway.async_block_till_done()
        await ws_gateway.async_initialize_devices_and_entities()
        async with (
            ws_gateway as gateway,
            Controller(f"ws://localhost:{zha_data.server_config.port}") as controller,
        ):
            await controller.clients.listen()
            yield controller, gateway


@pytest.fixture
async def zha_gateway(
    zha_data: ZHAData,
    zigpy_app_controller,
    caplog,  # pylint: disable=unused-argument
):
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

    # Disable gateway built in quirks loading
    with patch("zha.application.gateway.setup_quirks"):
        yield


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
