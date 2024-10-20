"""Controller implementation for the zhaws.client."""

from __future__ import annotations

import logging
from types import TracebackType

from aiohttp import ClientSession
from async_timeout import timeout
from zigpy.types.named import EUI64

from zha.application.gateway import RawDeviceInitializedEvent
from zha.application.model import (
    DeviceFullyInitializedEvent,
    DeviceJoinedEvent,
    DeviceLeftEvent,
    DeviceRemovedEvent,
    GroupAddedEvent,
    GroupMemberAddedEvent,
    GroupMemberRemovedEvent,
    GroupRemovedEvent,
)
from zha.application.platforms.model import EntityStateChangedEvent
from zha.event import EventBase
from zha.websocket.client.client import Client
from zha.websocket.client.helpers import (
    AlarmControlPanelHelper,
    ButtonHelper,
    ClientHelper,
    ClimateHelper,
    CoverHelper,
    DeviceHelper,
    FanHelper,
    GroupHelper,
    LightHelper,
    LockHelper,
    NetworkHelper,
    NumberHelper,
    PlatformEntityHelper,
    SelectHelper,
    ServerHelper,
    SirenHelper,
    SwitchHelper,
)
from zha.websocket.client.proxy import DeviceProxy, GroupProxy
from zha.websocket.const import ControllerEvents
from zha.websocket.server.api.model import WebSocketCommand, WebSocketCommandResponse
from zha.zigbee.model import ZHAEvent

CONNECT_TIMEOUT = 10

_LOGGER = logging.getLogger(__name__)


class Controller(EventBase):
    """Controller implementation."""

    def __init__(
        self, ws_server_url: str, aiohttp_session: ClientSession | None = None
    ):
        """Initialize the controller."""
        super().__init__()
        self._ws_server_url: str = ws_server_url
        self._client: Client = Client(ws_server_url, aiohttp_session)
        self._devices: dict[EUI64, DeviceProxy] = {}
        self._groups: dict[int, GroupProxy] = {}

        # set up all of the helper objects
        self.lights: LightHelper = LightHelper(self._client)
        self.switches: SwitchHelper = SwitchHelper(self._client)
        self.sirens: SirenHelper = SirenHelper(self._client)
        self.buttons: ButtonHelper = ButtonHelper(self._client)
        self.covers: CoverHelper = CoverHelper(self._client)
        self.fans: FanHelper = FanHelper(self._client)
        self.locks: LockHelper = LockHelper(self._client)
        self.numbers: NumberHelper = NumberHelper(self._client)
        self.selects: SelectHelper = SelectHelper(self._client)
        self.thermostats: ClimateHelper = ClimateHelper(self._client)
        self.alarm_control_panels: AlarmControlPanelHelper = AlarmControlPanelHelper(
            self._client
        )
        self.entities: PlatformEntityHelper = PlatformEntityHelper(self._client)
        self.clients: ClientHelper = ClientHelper(self._client)
        self.groups_helper: GroupHelper = GroupHelper(self._client)
        self.devices_helper: DeviceHelper = DeviceHelper(self._client)
        self.network: NetworkHelper = NetworkHelper(self._client)
        self.server_helper: ServerHelper = ServerHelper(self._client)

        # subscribe to event types we care about
        self._client.on_all_events(self._handle_event_protocol)

    @property
    def client(self) -> Client:
        """Return the client."""
        return self._client

    @property
    def devices(self) -> dict[EUI64, DeviceProxy]:
        """Return the devices."""
        return self._devices

    @property
    def groups(self) -> dict[int, GroupProxy]:
        """Return the groups."""
        return self._groups

    async def connect(self) -> None:
        """Connect to the websocket server."""
        _LOGGER.debug("Connecting to websocket server at: %s", self._ws_server_url)
        try:
            async with timeout(CONNECT_TIMEOUT):
                await self._client.connect()
        except Exception as err:
            _LOGGER.exception("Unable to connect to the ZHA wss", exc_info=err)
            raise err

        await self._client.listen()

    async def disconnect(self) -> None:
        """Disconnect from the websocket server."""
        await self._client.disconnect()

    async def __aenter__(self) -> Controller:
        """Connect to the websocket server."""
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Disconnect from the websocket server."""
        await self.disconnect()

    async def send_command(self, command: WebSocketCommand) -> WebSocketCommandResponse:
        """Send a command and get a response."""
        return await self._client.async_send_command(command)

    async def load_devices(self) -> None:
        """Load devices from the websocket server."""
        response_devices = await self.devices_helper.get_devices()
        for ieee, device in response_devices.items():
            self._devices[ieee] = DeviceProxy(device, self, self._client)

    async def load_groups(self) -> None:
        """Load groups from the websocket server."""
        response_groups = await self.groups_helper.get_groups()
        for group_id, group in response_groups.items():
            self._groups[group_id] = GroupProxy(group, self, self._client)

    def handle_state_changed(self, event: EntityStateChangedEvent) -> None:
        """Handle a platform_entity_event from the websocket server."""
        _LOGGER.debug("platform_entity_event: %s", event)
        if event.device_ieee:
            device = self.devices.get(event.device_ieee)
            if device is None:
                _LOGGER.warning("Received event from unknown device: %s", event)
                return
            device.emit_platform_entity_event(event)
        elif event.group_id:
            group = self.groups.get(event.group_id)
            if not group:
                _LOGGER.warning("Received event from unknown group: %s", event)
                return
            group.emit_platform_entity_event(event)

    def handle_zha_event(self, event: ZHAEvent) -> None:
        """Handle a zha_event from the websocket server."""
        _LOGGER.debug("zha_event: %s", event)
        device = self.devices.get(event.device.ieee)
        if device is None:
            _LOGGER.warning("Received zha_event from unknown device: %s", event)
            return
        device.emit("zha_event", event)

    def handle_device_joined(self, event: DeviceJoinedEvent) -> None:
        """Handle device joined.

        At this point, no information about the device is known other than its
        address
        """
        _LOGGER.info(
            "Device %s - %s joined", event.device_info.ieee, event.device_info.nwk
        )
        self.emit(ControllerEvents.DEVICE_JOINED, event)

    def handle_raw_device_initialized(self, event: RawDeviceInitializedEvent) -> None:
        """Handle a device initialization without quirks loaded."""
        _LOGGER.info(
            "Device %s - %s raw device initialized",
            event.device_info.ieee,
            event.device_info.nwk,
        )
        self.emit(ControllerEvents.RAW_DEVICE_INITIALIZED, event)

    def handle_device_fully_initialized(
        self, event: DeviceFullyInitializedEvent
    ) -> None:
        """Handle device joined and basic information discovered."""
        device_model = event.device_info
        _LOGGER.info("Device %s - %s initialized", device_model.ieee, device_model.nwk)
        if device_model.ieee in self.devices:
            self.devices[device_model.ieee].device_model = device_model
        else:
            self._devices[device_model.ieee] = DeviceProxy(
                device_model, self, self._client
            )
        self.emit(ControllerEvents.DEVICE_FULLY_INITIALIZED, event)

    def handle_device_left(self, event: DeviceLeftEvent) -> None:
        """Handle device leaving the network."""
        _LOGGER.info("Device %s - %s left", event.ieee, event.nwk)
        self.emit(ControllerEvents.DEVICE_LEFT, event)

    def handle_device_removed(self, event: DeviceRemovedEvent) -> None:
        """Handle device being removed from the network."""
        device = event.device_info
        _LOGGER.info(
            "Device %s - %s has been removed from the network", device.ieee, device.nwk
        )
        self._devices.pop(device.ieee, None)
        self.emit(ControllerEvents.DEVICE_REMOVED, event)

    def handle_group_member_removed(self, event: GroupMemberRemovedEvent) -> None:
        """Handle group member removed event."""
        if event.group_info.group_id in self.groups:
            self.groups[event.group_info.group_id].group_model = event.group_info
        self.emit(ControllerEvents.GROUP_MEMBER_REMOVED, event)

    def handle_group_member_added(self, event: GroupMemberAddedEvent) -> None:
        """Handle group member added event."""
        if event.group_info.group_id in self.groups:
            self.groups[event.group_info.group_id].group_model = event.group_info
        self.emit(ControllerEvents.GROUP_MEMBER_ADDED, event)

    def handle_group_added(self, event: GroupAddedEvent) -> None:
        """Handle group added event."""
        if event.group_info.group_id in self.groups:
            self.groups[event.group_info.group_id].group_model = event.group_info
        else:
            self.groups[event.group_info.group_id] = GroupProxy(
                event.group_info, self, self._client
            )
        self.emit(ControllerEvents.GROUP_ADDED, event)

    def handle_group_removed(self, event: GroupRemovedEvent) -> None:
        """Handle group removed event."""
        if event.group_info.group_id in self.groups:
            self.groups.pop(event.group_info.group_id)
        self.emit(ControllerEvents.GROUP_REMOVED, event)
