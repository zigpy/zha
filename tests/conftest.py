"""Test configuration for the ZHA component."""

from asyncio import AbstractEventLoop
from collections.abc import Callable
import itertools
import logging
import os
import tempfile
import time
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import aiohttp
import pytest
import zigpy
from zigpy.application import ControllerApplication
import zigpy.config
from zigpy.const import SIG_EP_INPUT, SIG_EP_OUTPUT, SIG_EP_PROFILE, SIG_EP_TYPE
import zigpy.device
import zigpy.group
import zigpy.profiles
import zigpy.types
import zigpy.zdo.types as zdo_t

from tests import common

FIXTURE_GRP_ID = 0x1001
FIXTURE_GRP_NAME = "fixture group"
_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def server_configuration() -> ServerConfiguration:
    """Server configuration fixture."""
    port = aiohttp.test_utils.unused_port()  # type: ignore
    with tempfile.TemporaryDirectory() as tempdir:
        # you can e.g. create a file here:
        config_path = os.path.join(tempdir, "configuration.json")
        server_config = ServerConfiguration.parse_obj(
            {
                "zigpy_configuration": {
                    "database_path": os.path.join(tempdir, "zigbee.db"),
                    "enable_quirks": True,
                },
                "radio_configuration": {
                    "type": "ezsp",
                    "path": "/dev/tty.SLAB_USBtoUART",
                    "baudrate": 115200,
                    "flow_control": "hardware",
                },
                "host": "localhost",
                "port": port,
                "network_auto_start": False,
            }
        )
        with open(config_path, "w") as tmpfile:
            tmpfile.write(server_config.json())
            return server_config


@pytest.fixture
def zigpy_app_controller() -> ControllerApplication:
    """Zigpy ApplicationController fixture."""
    app = MagicMock(spec_set=ControllerApplication)
    app.startup = AsyncMock()
    app.shutdown = AsyncMock()
    groups = zigpy.group.Groups(app)
    groups.add_group(FIXTURE_GRP_ID, FIXTURE_GRP_NAME, suppress_event=True)
    app.configure_mock(groups=groups)
    type(app).ieee = PropertyMock()
    app.ieee.return_value = zigpy.types.EUI64.convert("00:15:8d:00:02:32:4f:32")
    type(app).nwk = PropertyMock(return_value=zigpy.types.NWK(0x0000))
    type(app).devices = PropertyMock(return_value={})
    return app


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
async def connected_client_and_server(
    event_loop: AbstractEventLoop,
    server_configuration: ServerConfiguration,
    zigpy_app_controller: ControllerApplication,
) -> AsyncGenerator[tuple[Controller, Server], None]:
    """Return the connected client and server fixture."""

    application_controller_patch = patch(
        "bellows.zigbee.application.ControllerApplication.new",
        return_value=zigpy_app_controller,
    )

    with application_controller_patch:
        async with Server(configuration=server_configuration) as server:
            await server.controller.start_network()
            async with Controller(
                f"ws://localhost:{server_configuration.port}"
            ) as controller:
                await controller.clients.listen()
                yield controller, server


@pytest.fixture
def device_joined(
    connected_client_and_server: tuple[Controller, Server],
) -> Callable[[zigpy.device.Device], Device]:
    """Return a newly joined ZHAWS device."""

    async def _zha_device(zigpy_dev: zigpy.device.Device) -> Device:
        client, server = connected_client_and_server
        await server.controller.async_device_initialized(zigpy_dev)
        await server.block_till_done()
        return server.controller.get_device(zigpy_dev.ieee)

    return _zha_device


@pytest.fixture
def cluster_handler() -> Callable:
    """Clueter handler mock factory fixture."""

    def cluster_handler_factory(
        name: str, cluster_id: int, endpoint_id: int = 1
    ) -> MagicMock:
        ch = MagicMock()
        ch.name = name
        ch.generic_id = f"channel_0x{cluster_id:04x}"
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

        if patch_cluster:
            for endpoint in (ep for epid, ep in device.endpoints.items() if epid):
                endpoint.request = AsyncMock(return_value=[0])
                for cluster in itertools.chain(
                    endpoint.in_clusters.values(), endpoint.out_clusters.values()
                ):
                    common.patch_cluster(cluster)

        return device

    return _mock_dev
