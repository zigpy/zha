"""Support for Zigbee Home Automation devices."""

import asyncio
import contextlib
import copy
import logging
import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TYPE, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol
from zhaquirks import setup as setup_quirks
from zigpy.config import CONF_DATABASE, CONF_DEVICE, CONF_DEVICE_PATH
from zigpy.exceptions import NetworkSettingsInconsistent, TransientConnectionError

from . import repairs, websocket_api
from .core import ZHAGateway
from .core.const import (
    BAUD_RATES,
    CONF_BAUDRATE,
    CONF_CUSTOM_QUIRKS_PATH,
    CONF_DEVICE_CONFIG,
    CONF_ENABLE_QUIRKS,
    CONF_FLOW_CONTROL,
    CONF_RADIO_TYPE,
    CONF_USB_PATH,
    CONF_ZIGPY,
    DATA_ZHA,
    DOMAIN,
    PLATFORMS,
    SIGNAL_ADD_ENTITIES,
    RadioType,
)
from .core.device import get_device_automation_triggers
from .core.discovery import GROUP_PROBE
from .core.helpers import ZHAData, get_zha_data
from .radio_manager import ZhaRadioManager
from .repairs.network_settings_inconsistent import warn_on_inconsistent_network_settings
from .repairs.wrong_silabs_firmware import (
    AlreadyRunningEZSP,
    warn_on_wrong_silabs_firmware,
)

DEVICE_CONFIG_SCHEMA_ENTRY = vol.Schema({vol.Optional(CONF_TYPE): cv.string})
ZHA_CONFIG_SCHEMA = {
    vol.Optional(CONF_BAUDRATE): cv.positive_int,
    vol.Optional(CONF_DATABASE): cv.string,
    vol.Optional(CONF_DEVICE_CONFIG, default={}): vol.Schema(
        {cv.string: DEVICE_CONFIG_SCHEMA_ENTRY}
    ),
    vol.Optional(CONF_ENABLE_QUIRKS, default=True): cv.boolean,
    vol.Optional(CONF_ZIGPY): dict,
    vol.Optional(CONF_RADIO_TYPE): cv.enum(RadioType),
    vol.Optional(CONF_USB_PATH): cv.string,
    vol.Optional(CONF_CUSTOM_QUIRKS_PATH): cv.isdir,
}
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            vol.All(
                cv.deprecated(CONF_USB_PATH),
                cv.deprecated(CONF_BAUDRATE),
                cv.deprecated(CONF_RADIO_TYPE),
                ZHA_CONFIG_SCHEMA,
            ),
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

# Zigbee definitions
CENTICELSIUS = "C-100"

# Internal definitions
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up ZHA from config."""
    zha_data = ZHAData()
    zha_data.yaml_config = config.get(DOMAIN, {})
    hass.data[DATA_ZHA] = zha_data

    return True


def _clean_serial_port_path(path: str) -> str:
    """Clean the serial port path, applying corrections where necessary."""

    if path.startswith("socket://"):
        path = path.strip()

    # Removes extraneous brackets from IP addresses (they don't parse in CPython 3.11.4)
    if re.match(r"^socket://\[\d+\.\d+\.\d+\.\d+\]:\d+$", path):
        path = path.replace("[", "").replace("]", "")

    return path


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up ZHA.

    Will automatically load components to support devices found on the network.
    """

    # Remove brackets around IP addresses, this no longer works in CPython 3.11.4
    # This will be removed in 2023.11.0
    path = config_entry.data[CONF_DEVICE][CONF_DEVICE_PATH]
    cleaned_path = _clean_serial_port_path(path)
    data = copy.deepcopy(dict(config_entry.data))

    if path != cleaned_path:
        _LOGGER.debug("Cleaned serial port path %r -> %r", path, cleaned_path)
        data[CONF_DEVICE][CONF_DEVICE_PATH] = cleaned_path
        hass.config_entries.async_update_entry(config_entry, data=data)

    zha_data = get_zha_data(hass)

    if zha_data.yaml_config.get(CONF_ENABLE_QUIRKS, True):
        setup_quirks(
            custom_quirks_path=zha_data.yaml_config.get(CONF_CUSTOM_QUIRKS_PATH)
        )

    # Load and cache device trigger information early
    device_registry = dr.async_get(hass)
    radio_mgr = ZhaRadioManager.from_config_entry(hass, config_entry)

    async with radio_mgr.connect_zigpy_app() as app:
        for dev in app.devices.values():
            dev_entry = device_registry.async_get_device(
                identifiers={(DOMAIN, str(dev.ieee))},
                connections={(dr.CONNECTION_ZIGBEE, str(dev.ieee))},
            )

            if dev_entry is None:
                continue

            zha_data.device_trigger_cache[dev_entry.id] = (
                str(dev.ieee),
                get_device_automation_triggers(dev),
            )

    _LOGGER.debug("Trigger cache: %s", zha_data.device_trigger_cache)

    try:
        zha_gateway = await ZHAGateway.async_from_config(
            hass=hass,
            config=zha_data.yaml_config,
            config_entry=config_entry,
        )
    except NetworkSettingsInconsistent as exc:
        await warn_on_inconsistent_network_settings(
            hass,
            config_entry=config_entry,
            old_state=exc.old_state,
            new_state=exc.new_state,
        )
        raise ConfigEntryError(
            "Network settings do not match most recent backup"
        ) from exc
    except TransientConnectionError as exc:
        raise ConfigEntryNotReady from exc
    except Exception as exc:
        _LOGGER.debug("Failed to set up ZHA", exc_info=exc)
        device_path = config_entry.data[CONF_DEVICE][CONF_DEVICE_PATH]

        if (
            not device_path.startswith("socket://")
            and RadioType[config_entry.data[CONF_RADIO_TYPE]] == RadioType.ezsp
        ):
            try:
                # Ignore all exceptions during probing, they shouldn't halt setup
                if await warn_on_wrong_silabs_firmware(hass, device_path):
                    raise ConfigEntryError("Incorrect firmware installed") from exc
            except AlreadyRunningEZSP as ezsp_exc:
                raise ConfigEntryNotReady from ezsp_exc

        raise ConfigEntryNotReady from exc

    repairs.async_delete_blocking_issues(hass)

    manufacturer = zha_gateway.state.node_info.manufacturer
    model = zha_gateway.state.node_info.model

    if manufacturer is None and model is None:
        manufacturer = "Unknown"
        model = "Unknown"

    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_ZIGBEE, str(zha_gateway.state.node_info.ieee))},
        identifiers={(DOMAIN, str(zha_gateway.state.node_info.ieee))},
        name="Zigbee Coordinator",
        manufacturer=manufacturer,
        model=model,
        sw_version=zha_gateway.state.node_info.version,
    )

    websocket_api.async_load_api(hass)

    async def async_shutdown(_: Event) -> None:
        await zha_gateway.shutdown()

    config_entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_shutdown)
    )

    await zha_gateway.async_initialize_devices_and_entities()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    async_dispatcher_send(hass, SIGNAL_ADD_ENTITIES)
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload ZHA config entry."""
    zha_data = get_zha_data(hass)

    if zha_data.gateway is not None:
        await zha_data.gateway.shutdown()
        zha_data.gateway = None

    # clean up any remaining entity metadata
    # (entities that have been discovered but not yet added to HA)
    # suppress KeyError because we don't know what state we may
    # be in when we get here in failure cases
    with contextlib.suppress(KeyError):
        for platform in PLATFORMS:
            del zha_data.platforms[platform]

    GROUP_PROBE.cleanup()
    websocket_api.async_unload_api(hass)

    # our components don't have unload methods so no need to look at return values
    await asyncio.gather(
        *(
            hass.config_entries.async_forward_entry_unload(config_entry, platform)
            for platform in PLATFORMS
        )
    )

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:
        data = {
            CONF_RADIO_TYPE: config_entry.data[CONF_RADIO_TYPE],
            CONF_DEVICE: {CONF_DEVICE_PATH: config_entry.data[CONF_USB_PATH]},
        }

        baudrate = get_zha_data(hass).yaml_config.get(CONF_BAUDRATE)
        if data[CONF_RADIO_TYPE] != RadioType.deconz and baudrate in BAUD_RATES:
            data[CONF_DEVICE][CONF_BAUDRATE] = baudrate

        hass.config_entries.async_update_entry(config_entry, data=data, version=2)

    if config_entry.version == 2:
        data = {**config_entry.data}

        if data[CONF_RADIO_TYPE] == "ti_cc":
            data[CONF_RADIO_TYPE] = "znp"

        hass.config_entries.async_update_entry(config_entry, data=data, version=3)

    if config_entry.version == 3:
        data = {**config_entry.data}

        if not data[CONF_DEVICE].get(CONF_BAUDRATE):
            data[CONF_DEVICE][CONF_BAUDRATE] = {
                "deconz": 38400,
                "xbee": 57600,
                "ezsp": 57600,
                "znp": 115200,
                "zigate": 115200,
            }[data[CONF_RADIO_TYPE]]

        if not data[CONF_DEVICE].get(CONF_FLOW_CONTROL):
            data[CONF_DEVICE][CONF_FLOW_CONTROL] = None

        hass.config_entries.async_update_entry(config_entry, data=data, version=4)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
    return True


BLOCK_LOG_TIMEOUT: Final[int] = 60
_LOGGER = logging.getLogger(__name__)


class Server:
    """ZHAWSS server implementation."""

    def __init__(self, *, configuration: ServerConfiguration) -> None:
        """Initialize the server."""
        self._config = configuration
        self._ws_server: websockets.Serve | None = None
        self._controller: Controller = Controller(self)
        self._client_manager: ClientManager = ClientManager(self)
        self._stopped_event: asyncio.Event = asyncio.Event()
        self._tracked_tasks: list[asyncio.Task] = []
        self._tracked_completable_tasks: list[asyncio.Task] = []
        self.data: dict[Any, Any] = {}
        for platform in PLATFORMS:
            self.data.setdefault(platform, [])
        self._register_api_commands()
        discovery.PROBE.initialize(self)
        discovery.GROUP_PROBE.initialize(self)
        self._tracked_tasks.append(
            asyncio.create_task(
                self._cleanup_tracked_tasks(), name="server_cleanup_tracked_tasks"
            )
        )

    @property
    def is_serving(self) -> bool:
        """Return whether or not the websocket server is serving."""
        return self._ws_server is not None and self._ws_server.is_serving

    @property
    def controller(self) -> Controller:
        """Return the zigbee application controller."""
        return self._controller

    @property
    def client_manager(self) -> ClientManager:
        """Return the zigbee application controller."""
        return self._client_manager

    @property
    def config(self) -> ServerConfiguration:
        """Return the server configuration."""
        return self._config

    async def start_server(self) -> None:
        """Start the websocket server."""
        assert self._ws_server is None
        self._stopped_event.clear()
        self._ws_server = await websockets.serve(
            self.client_manager.add_client,
            self._config.host,
            self._config.port,
            logger=_LOGGER,
        )
        if self._config.network_auto_start:
            await self._controller.start_network()

    async def wait_closed(self) -> None:
        """Wait until the server is not running."""
        await self._stopped_event.wait()
        _LOGGER.info("Server stopped. Completing remaining tasks...")
        tasks = [t for t in self._tracked_tasks if not (t.done() or t.cancelled())]
        for task in tasks:
            _LOGGER.debug("Cancelling task: %s", task)
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

        tasks = [
            t
            for t in self._tracked_completable_tasks
            if not (t.done() or t.cancelled())
        ]
        for task in tasks:
            _LOGGER.debug("Cancelling task: %s", task)
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_server(self) -> None:
        """Stop the websocket server."""
        if self._ws_server is None:
            self._stopped_event.set()
            return

        assert self._ws_server is not None

        if self._controller.is_running:
            await self._controller.stop_network()

        self._ws_server.close()
        await self._ws_server.wait_closed()
        self._ws_server = None

        self._stopped_event.set()

    async def __aenter__(self) -> Server:
        """Enter the context manager."""
        await self.start_server()
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Exit the context manager."""
        await self.stop_server()
        await self.wait_closed()

    async def block_till_done(self) -> None:
        """Block until all pending work is done."""
        # To flush out any call_soon_threadsafe
        await asyncio.sleep(0.001)
        start_time: float | None = None

        while self._tracked_completable_tasks:
            pending = [
                task for task in self._tracked_completable_tasks if not task.done()
            ]
            self._tracked_completable_tasks.clear()
            if pending:
                await self._await_and_log_pending(pending)

                if start_time is None:
                    # Avoid calling monotonic() until we know
                    # we may need to start logging blocked tasks.
                    start_time = 0
                elif start_time == 0:
                    # If we have waited twice then we set the start
                    # time
                    start_time = monotonic()
                elif monotonic() - start_time > BLOCK_LOG_TIMEOUT:
                    # We have waited at least three loops and new tasks
                    # continue to block. At this point we start
                    # logging all waiting tasks.
                    for task in pending:
                        _LOGGER.debug("Waiting for task: %s", task)
            else:
                await asyncio.sleep(0.001)

    async def _await_and_log_pending(self, pending: Iterable[Awaitable[Any]]) -> None:
        """Await and log tasks that take a long time."""
        # pylint: disable=no-self-use
        wait_time = 0
        while pending:
            _, pending = await asyncio.wait(pending, timeout=BLOCK_LOG_TIMEOUT)
            if not pending:
                return
            wait_time += BLOCK_LOG_TIMEOUT
            for task in pending:
                _LOGGER.debug("Waited %s seconds for task: %s", wait_time, task)

    def track_task(self, task: asyncio.Task) -> None:
        """Create a tracked task."""
        self._tracked_completable_tasks.append(task)

    @periodic((10, 10))
    async def _cleanup_tracked_tasks(self) -> None:
        """Cleanup tracked tasks."""
        done_tasks: list[asyncio.Task] = [
            task for task in self._tracked_completable_tasks if task.done()
        ]
        for task in done_tasks:
            self._tracked_completable_tasks.remove(task)

    def _register_api_commands(self) -> None:
        """Load server API commands."""
        from zhaws.server.websocket.client import load_api as load_client_api

        register_api_command(self, stop_server)
        load_zigbee_controller_api(self)
        load_platform_entity_apis(self)
        load_client_api(self)


class StopServerCommand(WebSocketCommand):
    """Stop the server."""

    command: Literal[APICommands.STOP_SERVER] = APICommands.STOP_SERVER


@decorators.websocket_command(StopServerCommand)
@decorators.async_response
async def stop_server(
    server: Server, client: Client, command: WebSocketCommand
) -> None:
    """Stop the Zigbee network."""
    client.send_result_success(command)
    await server.stop_server()
