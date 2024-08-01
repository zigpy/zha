"""Test configuration for the ZHA component."""

import asyncio
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
import itertools
import logging
import os
import reprlib
import threading
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
from zigpy.zcl.foundation import GENERAL_COMMANDS, GeneralCommand, Status
import zigpy.zdo.types as zdo_t

from tests import common
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.helpers import (
    AlarmControlPanelOptions,
    CoordinatorConfiguration,
    LightOptions,
    ZHAConfiguration,
    ZHAData,
)
from zha.async_ import ZHAJob
from zha.zigbee.device import Device

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


def _wrap_mock_instance(obj: Any) -> MagicMock:
    """Auto-mock every attribute and method in an object."""
    mock = create_autospec(obj, spec_set=True, instance=True)

    for attr_name in dir(obj):
        if attr_name.startswith("__") and attr_name not in {"__getitem__"}:
            continue

        real_attr = getattr(obj, attr_name)

        if callable(real_attr) and not hasattr(real_attr, "__aenter__"):
            mock_attr = getattr(mock, attr_name)
            mock_attr.side_effect = real_attr
        else:
            setattr(mock, attr_name, real_attr)

    return mock


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
        yield app


@pytest.fixture
async def zigpy_app_controller_mock(zigpy_app_controller):
    """Zigpy ApplicationController fixture."""
    # The mock wrapping accesses deprecated attributes, so we suppress the warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        mock_app = _wrap_mock_instance(zigpy_app_controller)
        mock_app.backups = _wrap_mock_instance(zigpy_app_controller.backups)

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
        )
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
async def zha_gateway(
    zha_data: ZHAData,  # pylint: disable=redefined-outer-name
    zigpy_app_controller,  # pylint: disable=redefined-outer-name
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


@pytest.fixture
def device_joined(
    zha_gateway: Gateway,  # pylint: disable=redefined-outer-name
) -> Callable[[zigpy.device.Device], Awaitable[Device]]:
    """Return a newly joined ZHAWS device."""

    async def _zha_device(zigpy_dev: zigpy.device.Device) -> Device:
        zha_gateway.application_controller.devices[zigpy_dev.ieee] = zigpy_dev
        await zha_gateway.async_device_initialized(zigpy_dev)
        await zha_gateway.async_block_till_done()

        device = zha_gateway.get_device(zigpy_dev.ieee)
        assert device is not None
        return device

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
    zigpy_app_controller: ControllerApplication,  # pylint: disable=redefined-outer-name
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

            for cluster_id in ep.get(SIG_EP_INPUT, []):
                endpoint.add_input_cluster(cluster_id)

            for cluster_id in ep.get(SIG_EP_OUTPUT, []):
                endpoint.add_output_cluster(cluster_id)

        if quirk:
            device = quirk(zigpy_app_controller, device.ieee, device.nwk, device)
        else:
            device = get_device(device)

        async def mock_request(
            cluster: zigpy.types.ClusterId,
            sequence: zigpy.types.uint8_t,
            data: bytes,
            expect_reply: bool = True,
            command_id: GeneralCommand | zigpy.types.uint8_t = 0x00,
        ):
            # if isinstance(command_id, (int, GeneralCommand)):
            # Some commands can't handle default response, and will
            # fail with a non list element as first element.
            if command_id in (
                GeneralCommand.Read_Reporting_Configuration,
                GeneralCommand.Write_Attributes,
            ):
                return [[]]

            if command_id in GeneralCommand.__members__:
                return GENERAL_COMMANDS[GeneralCommand.Default_Response].schema(
                    command_id=command_id, status=Status.UNSUP_GENERAL_COMMAND
                )

            return [0]

        # add request mock after device creation since quirks may have added endpoints
        for epid, endpoint in device.endpoints.items():
            if epid:
                endpoint.request = AsyncMock(side_effect=mock_request)
            else:
                endpoint.request = AsyncMock(return_value=[0])

        if patch_cluster:
            for endpoint in (ep for epid, ep in device.endpoints.items() if epid):
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
