"""Virtual gateway for Zigbee Home Automation."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import contextlib
from contextlib import suppress
from datetime import timedelta
import logging
import time
from types import TracebackType
from typing import Any, Final, Self, TypeVar, cast

from async_timeout import timeout
import websockets
from zhaquirks import setup as setup_quirks
from zigpy.application import ControllerApplication
from zigpy.config import (
    CONF_DEVICE,
    CONF_DEVICE_BAUDRATE,
    CONF_DEVICE_FLOW_CONTROL,
    CONF_DEVICE_PATH,
    CONF_NWK_VALIDATE_SETTINGS,
)
import zigpy.device
import zigpy.endpoint
import zigpy.group
from zigpy.quirks.v2 import UNBUILT_QUIRK_BUILDERS
from zigpy.state import State
from zigpy.types.named import EUI64
from zigpy.zdo import ZDO

from zha.application import discovery
from zha.application.const import (
    ATTR_DEVICE_TYPE,
    ATTR_ENDPOINTS,
    ATTR_MANUFACTURER,
    ATTR_MODEL,
    ATTR_NODE_DESCRIPTOR,
    ATTR_PROFILE_ID,
    CONF_USE_THREAD,
    UNKNOWN_MANUFACTURER,
    UNKNOWN_MODEL,
    ZHA_GW_MSG_CONNECTION_LOST,
    ZHA_GW_MSG_DEVICE_FULL_INIT,
    ZHA_GW_MSG_DEVICE_JOINED,
    ZHA_GW_MSG_DEVICE_LEFT,
    ZHA_GW_MSG_DEVICE_REMOVED,
    ZHA_GW_MSG_RAW_INIT,
    RadioType,
)
from zha.application.helpers import DeviceAvailabilityChecker, GlobalUpdater, ZHAData
from zha.application.model import (
    ConnectionLostEvent,
    DeviceFullyInitializedEvent,
    DeviceJoinedDeviceInfo,
    DeviceJoinedEvent,
    DeviceLeftEvent,
    DevicePairingStatus,
    DeviceRemovedEvent,
    ExtendedDeviceInfoWithPairingStatus,
    GroupAddedEvent,
    GroupMemberAddedEvent,
    GroupMemberRemovedEvent,
    GroupRemovedEvent,
    RawDeviceInitializedDeviceInfo,
    RawDeviceInitializedEvent,
)
from zha.application.platforms.model import EntityStateChangedEvent
from zha.async_ import (
    AsyncUtilMixin,
    create_eager_task,
    gather_with_limited_concurrency,
)
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
from zha.websocket.const import ControllerEvents
from zha.websocket.server.api.model import WebSocketCommand, WebSocketCommandResponse
from zha.websocket.server.api.platforms.api import load_platform_entity_apis
from zha.websocket.server.client import ClientManager, load_api as load_client_api
from zha.websocket.server.gateway_api import load_api as load_zigbee_controller_api
from zha.zigbee.device import BaseDevice, Device, WebSocketClientDevice
from zha.zigbee.endpoint import ATTR_IN_CLUSTERS, ATTR_OUT_CLUSTERS
from zha.zigbee.group import (
    BaseGroup,
    Group,
    GroupMemberReference,
    WebSocketClientGroup,
)
from zha.zigbee.model import DeviceStatus, ExtendedDeviceInfo, ZHAEvent

BLOCK_LOG_TIMEOUT: Final[int] = 60
_R = TypeVar("_R")
_LOGGER = logging.getLogger(__name__)


class BaseGateway(EventBase, ABC):
    """Base gateway class."""

    def __init__(self, config: ZHAData) -> None:
        """Initialize the gateway."""
        super().__init__()
        self.config: ZHAData = config
        self.config.gateway = self

    @abstractmethod
    async def _async_initialize(self) -> None:
        """Initialize controller and connect radio."""

    @abstractmethod
    def _find_coordinator_device(self) -> zigpy.device.Device:
        """Find the coordinator device."""

    @abstractmethod
    async def async_initialize_devices_and_entities(self) -> None:
        """Initialize devices and load entities."""

    @abstractmethod
    def get_or_create_device(
        self, zigpy_device: zigpy.device.Device | ExtendedDeviceInfo
    ) -> BaseDevice:
        """Get or create a ZHA device."""

    @abstractmethod
    async def async_create_zigpy_group(
        self,
        name: str,
        members: list[GroupMemberReference] | None,
        group_id: int | None = None,
    ) -> BaseGroup | None:
        """Create a new Zigpy Zigbee group."""

    @abstractmethod
    async def async_remove_device(self, ieee: EUI64) -> None:
        """Remove a device from ZHA."""

    @abstractmethod
    async def async_remove_zigpy_group(self, group_id: int) -> None:
        """Remove a Zigbee group from Zigpy."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Stop ZHA Controller Application."""


class Gateway(AsyncUtilMixin, BaseGateway):
    """Gateway that handles events that happen on the ZHA Zigbee network."""

    def __init__(self, config: ZHAData) -> None:
        """Initialize the gateway."""
        super().__init__(config)
        self._devices: dict[EUI64, Device] = {}
        self._groups: dict[int, Group] = {}
        self.coordinator_zha_device: Device = None  # type: ignore[assignment]
        self.application_controller: ControllerApplication = None
        self.shutting_down: bool = False
        self._reload_task: asyncio.Task | None = None
        self.global_updater: GlobalUpdater = GlobalUpdater(self)
        self._device_availability_checker: DeviceAvailabilityChecker = (
            DeviceAvailabilityChecker(self)
        )

    @property
    def devices(self) -> dict[EUI64, Device]:
        """Return devices."""
        return self._devices

    @property
    def groups(self) -> dict[int, Group]:
        """Return groups."""
        return self._groups

    @property
    def radio_type(self) -> RadioType:
        """Get the current radio type."""
        return RadioType[self.config.config.coordinator_configuration.radio_type]

    def get_application_controller_data(self) -> tuple[ControllerApplication, dict]:
        """Get an uninitialized instance of a zigpy `ControllerApplication`."""
        app_config = self.config.zigpy_config
        app_config[CONF_DEVICE] = {
            CONF_DEVICE_PATH: self.config.config.coordinator_configuration.path,
            CONF_DEVICE_BAUDRATE: self.config.config.coordinator_configuration.baudrate,
            CONF_DEVICE_FLOW_CONTROL: self.config.config.coordinator_configuration.flow_control,
        }

        if CONF_NWK_VALIDATE_SETTINGS not in app_config:
            app_config[CONF_NWK_VALIDATE_SETTINGS] = True

        # The bellows UART thread sometimes propagates a cancellation into the main Core
        # event loop, when a connection to a TCP coordinator fails in a specific way
        if (
            CONF_USE_THREAD not in app_config
            and self.radio_type is RadioType.ezsp
            and app_config[CONF_DEVICE][CONF_DEVICE_PATH].startswith("socket://")
        ):
            app_config[CONF_USE_THREAD] = False

        return self.radio_type.controller, app_config

    @classmethod
    async def async_from_config(cls, config: ZHAData) -> Self:
        """Create an instance of a gateway from config objects."""
        instance = cls(config)

        if config.config.quirks_configuration.enabled:
            for quirk in UNBUILT_QUIRK_BUILDERS:
                _LOGGER.warning(
                    "Found a v2 quirk that was not added to the registry: %s",
                    quirk,
                )
                quirk.add_to_registry()

            UNBUILT_QUIRK_BUILDERS.clear()

            await instance.async_add_executor_job(
                setup_quirks,
                instance.config.config.quirks_configuration.custom_quirks_path,
            )

        return instance

    async def _async_initialize(self) -> None:
        """Initialize controller and connect radio."""
        discovery.DEVICE_PROBE.initialize(self)
        discovery.ENDPOINT_PROBE.initialize(self)
        discovery.GROUP_PROBE.initialize(self)

        self.shutting_down = False

        app_controller_cls, app_config = self.get_application_controller_data()
        self.application_controller = await app_controller_cls.new(
            config=app_config,
            auto_form=False,
            start_radio=False,
        )

        await self.application_controller.startup(auto_form=True)

        self.coordinator_zha_device = self.get_or_create_device(
            self._find_coordinator_device()
        )

        self.load_devices()
        self.load_groups()

        self.application_controller.add_listener(self)
        self.application_controller.groups.add_listener(self)
        self.global_updater.start()
        self._device_availability_checker.start()

    async def async_initialize(self) -> None:
        """Initialize controller and connect radio."""
        try:
            await self._async_initialize()
        except Exception:
            await self.shutdown()
            raise

    def connection_lost(self, exc: Exception) -> None:
        """Handle connection lost event."""
        _LOGGER.debug("Connection to the radio was lost: %r", exc)
        self.emit(ZHA_GW_MSG_CONNECTION_LOST, ConnectionLostEvent(exception=exc))

    def _find_coordinator_device(self) -> zigpy.device.Device:
        zigpy_coordinator = self.application_controller.get_device(nwk=0x0000)

        if last_backup := self.application_controller.backups.most_recent_backup():
            with suppress(KeyError):
                zigpy_coordinator = self.application_controller.get_device(
                    ieee=last_backup.node_info.ieee
                )

        return zigpy_coordinator

    def load_devices(self) -> None:
        """Restore ZHA devices from zigpy application state."""

        assert self.application_controller
        for zigpy_device in self.application_controller.devices.values():
            zha_device = self.get_or_create_device(zigpy_device)
            delta_msg = "not known"
            if zha_device.last_seen is not None:
                delta = round(time.time() - zha_device.last_seen)
                delta_msg = f"{str(timedelta(seconds=delta))} ago"
            _LOGGER.debug(
                (
                    "[%s](%s) restored as '%s', last seen: %s,"
                    " consider_unavailable_time: %s seconds"
                ),
                zha_device.nwk,
                zha_device.name,
                "available" if zha_device.available else "unavailable",
                delta_msg,
                zha_device.consider_unavailable_time,
            )
        self.create_platform_entities()

    def load_groups(self) -> None:
        """Initialize ZHA groups."""

        for group_id, group in self.application_controller.groups.items():
            _LOGGER.info("Loading group with id: 0x%04x", group_id)
            zha_group = self.get_or_create_group(group)
            # we can do this here because the entities are in the
            # entity registry tied to the devices
            discovery.GROUP_PROBE.discover_group_entities(zha_group)

    def create_platform_entities(self) -> None:
        """Create platform entities."""

        for platform in discovery.PLATFORMS:
            for platform_entity_class, args, kw_args in self.config.platforms[platform]:
                try:
                    platform_entity = platform_entity_class.create_platform_entity(
                        *args, **kw_args
                    )
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception(
                        "Failed to create platform entity: %s [args=%s, kwargs=%s]",
                        platform_entity_class,
                        args,
                        kw_args,
                    )
                    continue
                if platform_entity:
                    _LOGGER.debug(
                        "Platform entity data: %s", platform_entity.info_object
                    )
            self.config.platforms[platform].clear()

    @property
    def radio_concurrency(self) -> int:
        """Maximum configured radio concurrency."""
        return self.application_controller._concurrent_requests_semaphore.max_value  # pylint: disable=protected-access

    async def async_fetch_updated_state_mains(self) -> None:
        """Fetch updated state for mains powered devices."""
        _LOGGER.debug("Fetching current state for mains powered devices")

        now = time.time()

        # Only delay startup to poll mains-powered devices that are online
        online_devices = [
            dev
            for dev in self.devices.values()
            if dev.is_mains_powered
            and dev.last_seen is not None
            and (now - dev.last_seen) < dev.consider_unavailable_time
        ]

        # Prioritize devices that have recently been contacted
        online_devices.sort(key=lambda dev: cast(float, dev.last_seen), reverse=True)

        # Make sure that we always leave slots for non-startup requests
        max_poll_concurrency = max(1, self.radio_concurrency - 4)

        await gather_with_limited_concurrency(
            max_poll_concurrency,
            *(dev.async_initialize(from_cache=False) for dev in online_devices),
        )

        _LOGGER.debug("completed fetching current state for mains powered devices")

    async def async_initialize_devices_and_entities(self) -> None:
        """Initialize devices and load entities."""

        _LOGGER.debug("Initializing all devices from Zigpy cache")
        await asyncio.gather(
            *(dev.async_initialize(from_cache=True) for dev in self.devices.values())
        )

        async def fetch_updated_state() -> None:
            """Fetch updated state for mains powered devices."""
            if self.config.config.device_options.enable_mains_startup_polling:
                await self.async_fetch_updated_state_mains()
            else:
                _LOGGER.debug("Polling of mains powered devices at startup is disabled")
            _LOGGER.debug("Allowing polled requests")
            self.config.allow_polling = True

        # background the fetching of state for mains powered devices
        self.async_create_background_task(
            fetch_updated_state(), "zha.gateway-fetch_updated_state"
        )

    def device_joined(self, device: zigpy.device.Device) -> None:
        """Handle device joined.

        At this point, no information about the device is known other than its
        address
        """

        self.emit(
            ZHA_GW_MSG_DEVICE_JOINED,
            DeviceJoinedEvent(
                device_info=DeviceJoinedDeviceInfo(
                    ieee=device.ieee,
                    nwk=device.nwk,
                    pairing_status=DevicePairingStatus.PAIRED,
                )
            ),
        )

    def raw_device_initialized(self, device: zigpy.device.Device) -> None:  # pylint: disable=unused-argument
        """Handle a device initialization without quirks loaded."""

        self.emit(
            ZHA_GW_MSG_RAW_INIT,
            RawDeviceInitializedEvent(
                device_info=RawDeviceInitializedDeviceInfo(
                    ieee=device.ieee,
                    nwk=device.nwk,
                    pairing_status=DevicePairingStatus.INTERVIEW_COMPLETE,
                    model=device.model if device.model else UNKNOWN_MODEL,
                    manufacturer=device.manufacturer
                    if device.manufacturer
                    else UNKNOWN_MANUFACTURER,
                    signature={
                        ATTR_NODE_DESCRIPTOR: device.node_desc.as_dict(),
                        ATTR_ENDPOINTS: {
                            ep_id: {
                                ATTR_PROFILE_ID: f"0x{endpoint.profile_id:04x}"
                                if endpoint.profile_id is not None
                                else "",
                                ATTR_DEVICE_TYPE: f"0x{endpoint.device_type:04x}"
                                if endpoint.device_type is not None
                                else "",
                                ATTR_IN_CLUSTERS: [
                                    f"0x{cluster_id:04x}"
                                    for cluster_id in sorted(endpoint.in_clusters)
                                ],
                                ATTR_OUT_CLUSTERS: [
                                    f"0x{cluster_id:04x}"
                                    for cluster_id in sorted(endpoint.out_clusters)
                                ],
                            }
                            for ep_id, endpoint in device.endpoints.items()
                            if not isinstance(endpoint, ZDO)
                        },
                        ATTR_MANUFACTURER: device.manufacturer
                        if device.manufacturer
                        else UNKNOWN_MANUFACTURER,
                        ATTR_MODEL: device.model if device.model else UNKNOWN_MODEL,
                    },
                )
            ),
        )

    def device_initialized(self, device: zigpy.device.Device) -> None:
        """Handle device joined and basic information discovered."""
        if device.ieee in self._device_init_tasks:
            _LOGGER.warning(
                "Cancelling previous initialization task for device %s",
                str(device.ieee),
            )
            self._device_init_tasks[device.ieee].cancel()
        self._device_init_tasks[device.ieee] = init_task = self.async_create_task(
            self.async_device_initialized(device),
            name=f"device_initialized_task_{str(device.ieee)}:0x{device.nwk:04x}",
            eager_start=True,
        )
        init_task.add_done_callback(lambda _: self._device_init_tasks.pop(device.ieee))

    def device_left(self, device: zigpy.device.Device) -> None:
        """Handle device leaving the network."""
        zha_device: Device = self._devices.get(device.ieee)
        if zha_device is not None:
            zha_device.on_network = False
        self.async_update_device(device, available=False)
        self.emit(
            ZHA_GW_MSG_DEVICE_LEFT, DeviceLeftEvent(ieee=device.ieee, nwk=device.nwk)
        )

    def group_member_removed(
        self, zigpy_group: zigpy.group.Group, endpoint: zigpy.endpoint.Endpoint
    ) -> None:
        """Handle zigpy group member removed event."""
        # need to handle endpoint correctly on groups
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.clear_caches()
        discovery.GROUP_PROBE.discover_group_entities(zha_group)
        zha_group.info("group_member_removed - endpoint: %s", endpoint)
        self._emit_group_gateway_message(zigpy_group, GroupMemberRemovedEvent)

    def group_member_added(
        self, zigpy_group: zigpy.group.Group, endpoint: zigpy.endpoint.Endpoint
    ) -> None:
        """Handle zigpy group member added event."""
        # need to handle endpoint correctly on groups
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.clear_caches()
        discovery.GROUP_PROBE.discover_group_entities(zha_group)
        zha_group.info("group_member_added - endpoint: %s", endpoint)
        self._emit_group_gateway_message(zigpy_group, GroupMemberAddedEvent)

    def group_added(self, zigpy_group: zigpy.group.Group) -> None:
        """Handle zigpy group added event."""
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.info("group_added")
        # need to dispatch for entity creation here
        self._emit_group_gateway_message(zigpy_group, GroupAddedEvent)

    def group_removed(self, zigpy_group: zigpy.group.Group) -> None:
        """Handle zigpy group removed event."""
        self._emit_group_gateway_message(zigpy_group, GroupRemovedEvent)
        zha_group = self._groups.pop(zigpy_group.group_id)
        zha_group.info("group_removed")

    def _emit_group_gateway_message(  # pylint: disable=unused-argument
        self,
        zigpy_group: zigpy.group.Group,
        gateway_message_type: GroupRemovedEvent
        | GroupAddedEvent
        | GroupMemberAddedEvent
        | GroupMemberRemovedEvent,
    ) -> None:
        """Send the gateway event for a zigpy group event."""
        zha_group = self._groups.get(zigpy_group.group_id)
        if zha_group is not None:
            response = gateway_message_type(
                group_info=zha_group.info_object,
            )
            self.emit(
                response.event,
                response,
            )

    def device_removed(self, device: zigpy.device.Device) -> None:
        """Handle device being removed from the network."""
        _LOGGER.info("Removing device %s - %s", device.ieee, f"0x{device.nwk:04x}")
        zha_device = self._devices.pop(device.ieee, None)
        if zha_device is not None:
            device_info = zha_device.extended_device_info
            self.track_task(
                create_eager_task(
                    zha_device.on_remove(), name="Gateway._async_remove_device"
                )
            )
            if device_info is not None:
                self.emit(
                    ZHA_GW_MSG_DEVICE_REMOVED,
                    DeviceRemovedEvent(device_info=device_info),
                )

    def get_device(self, ieee: EUI64) -> Device | None:
        """Return Device for given ieee."""
        return self._devices.get(ieee)

    def get_group(self, group_id_or_name: int | str) -> Group | None:
        """Return Group for given group id or group name."""
        if isinstance(group_id_or_name, str):
            for group in self.groups.values():
                if group.name == group_id_or_name:
                    return group
            return None
        return self.groups.get(group_id_or_name)

    @property
    def state(self) -> State:
        """Return the active coordinator's network state."""
        return self.application_controller.state

    def get_or_create_device(self, zigpy_device: zigpy.device.Device) -> Device:
        """Get or create a ZHA device."""
        if (zha_device := self._devices.get(zigpy_device.ieee)) is None:
            zha_device = Device.new(zigpy_device, self)
            self._devices[zigpy_device.ieee] = zha_device
        return zha_device

    def get_or_create_group(self, zigpy_group: zigpy.group.Group) -> Group:
        """Get or create a ZHA group."""
        zha_group = self._groups.get(zigpy_group.group_id)
        if zha_group is None:
            zha_group = Group(self, zigpy_group)
            self._groups[zigpy_group.group_id] = zha_group
        return zha_group

    def async_update_device(
        self,
        sender: zigpy.device.Device,
        available: bool = True,
    ) -> None:
        """Update device that has just become available."""
        if sender.ieee in self.devices:
            device = self.devices[sender.ieee]
            # avoid a race condition during new joins
            if device.status is DeviceStatus.INITIALIZED:
                device.update_available(available)

    async def async_device_initialized(self, device: zigpy.device.Device) -> None:
        """Handle device joined and basic information discovered (async)."""
        zha_device = self.get_or_create_device(device)
        _LOGGER.debug(
            "device - %s:%s entering async_device_initialized - is_new_join: %s",
            device.nwk,
            device.ieee,
            zha_device.status is not DeviceStatus.INITIALIZED,
        )

        if zha_device.status is DeviceStatus.INITIALIZED:
            # ZHA already has an initialized device so either the device was assigned a
            # new nwk or device was physically reset and added again without being removed
            _LOGGER.debug(
                "device - %s:%s has been reset and re-added or its nwk address changed",
                device.nwk,
                device.ieee,
            )
            await self._async_device_rejoined(zha_device)
        else:
            _LOGGER.debug(
                "device - %s:%s has joined the ZHA zigbee network",
                device.nwk,
                device.ieee,
            )
            await self._async_device_joined(zha_device)

        device_info = ExtendedDeviceInfoWithPairingStatus(
            pairing_status=DevicePairingStatus.INITIALIZED,
            **zha_device.extended_device_info.__dict__,
        )
        self.emit(
            ZHA_GW_MSG_DEVICE_FULL_INIT,
            DeviceFullyInitializedEvent(device_info=device_info),
        )

    async def _async_device_joined(self, zha_device: Device) -> None:
        zha_device.available = True
        zha_device.on_network = True
        await zha_device.async_configure()
        device_info = ExtendedDeviceInfoWithPairingStatus(
            pairing_status=DevicePairingStatus.CONFIGURED,
            **zha_device.extended_device_info.__dict__,
        )
        await zha_device.async_initialize(from_cache=False)
        self.create_platform_entities()
        self.emit(
            ZHA_GW_MSG_DEVICE_FULL_INIT,
            DeviceFullyInitializedEvent(device_info=device_info, new_join=True),
        )

    async def _async_device_rejoined(self, zha_device: Device) -> None:
        _LOGGER.debug(
            "skipping discovery for previously discovered device - %s:%s",
            zha_device.nwk,
            zha_device.ieee,
        )
        # we don't have to do this on a nwk swap
        # but we don't have a way to tell currently
        await zha_device.async_configure()
        device_info = ExtendedDeviceInfoWithPairingStatus(
            pairing_status=DevicePairingStatus.CONFIGURED,
            **zha_device.extended_device_info.__dict__,
        )
        self.emit(
            ZHA_GW_MSG_DEVICE_FULL_INIT,
            DeviceFullyInitializedEvent(device_info=device_info),
        )
        # force async_initialize() to fire so don't explicitly call it
        zha_device.available = False
        zha_device.on_network = True

    async def async_create_zigpy_group(
        self,
        name: str,
        members: list[GroupMemberReference] | None,
        group_id: int | None = None,
    ) -> Group | None:
        """Create a new Zigpy Zigbee group."""

        # we start with two to fill any gaps from a user removing existing groups

        if group_id is None:
            group_id = 2
            while group_id in self.groups:
                group_id += 1

        # guard against group already existing
        if self.get_group(name) is None:
            self.application_controller.groups.add_group(group_id, name)
            if members is not None:
                tasks = []
                for member in members:
                    _LOGGER.debug(
                        (
                            "Adding member with IEEE: %s and endpoint ID: %s to group:"
                            " %s:0x%04x"
                        ),
                        member.ieee,
                        member.endpoint_id,
                        name,
                        group_id,
                    )
                    tasks.append(
                        self.devices[member.ieee].async_add_endpoint_to_group(
                            member.endpoint_id, group_id
                        )
                    )
                await asyncio.gather(*tasks)
        return self.groups.get(group_id)

    async def async_remove_device(self, ieee: EUI64) -> None:
        """Remove a device from ZHA."""
        if not (device := self.devices.get(ieee)):
            _LOGGER.debug("Device: %s could not be found", ieee)
            return
        if device.is_active_coordinator:
            _LOGGER.info("Removing the active coordinator (%s) is not allowed", ieee)
            return
        for group_id, group in self.groups.items():
            for member_ieee_endpoint_id in list(group.zigpy_group.members.keys()):
                if member_ieee_endpoint_id[0] == ieee:
                    await device.async_remove_from_group(group_id)

        await self.application_controller.remove(ieee)

    async def async_remove_zigpy_group(self, group_id: int) -> None:
        """Remove a Zigbee group from Zigpy."""
        if not (group := self.groups.get(group_id)):
            _LOGGER.debug("Group: 0x%04x could not be found", group_id)
            return
        if group.members:
            tasks = []
            for member in group.members:
                tasks.append(member.async_remove_from_group())
            if tasks:
                await asyncio.gather(*tasks)
        self.application_controller.groups.pop(group_id)

    async def shutdown(self) -> None:
        """Stop ZHA Controller Application."""
        if self.shutting_down:
            _LOGGER.debug("Ignoring duplicate shutdown event")
            return

        self.shutting_down = True

        self.global_updater.stop()
        self._device_availability_checker.stop()

        for device in self._devices.values():
            await device.on_remove()

        for group in self._groups.values():
            await group.on_remove()

        _LOGGER.debug("Shutting down ZHA ControllerApplication")
        if self.application_controller is not None:
            await self.application_controller.shutdown()
            self.application_controller = None
            await asyncio.sleep(0.1)  # give bellows thread callback a chance to run

        await super().shutdown()

        self._devices.clear()
        self._groups.clear()

    def handle_message(  # pylint: disable=unused-argument
        self,
        sender: zigpy.device.Device,
        profile: int,
        cluster: int,
        src_ep: int,
        dst_ep: int,
        message: bytes,
    ) -> None:
        """Handle message from a device Event handler."""
        if sender.ieee in self.devices and not self.devices[sender.ieee].available:
            self.devices[sender.ieee].on_network = True
            self.async_update_device(sender, available=True)


class WebSocketServerGateway(Gateway):
    """ZHAWSS server implementation."""

    def __init__(self, config: ZHAData) -> None:
        """Initialize the websocket server gateway."""
        super().__init__(config)
        self._ws_server: websockets.WebSocketServer | None = None
        self._client_manager: ClientManager = ClientManager(self)
        self._stopped_event: asyncio.Event = asyncio.Event()
        self._tracked_ws_tasks: set[asyncio.Task] = set()
        self.data: dict[Any, Any] = {}
        for platform in discovery.PLATFORMS:
            self.data.setdefault(platform, [])
        self._register_api_commands()

    @property
    def is_serving(self) -> bool:
        """Return whether or not the websocket server is serving."""
        return self._ws_server is not None and self._ws_server.is_serving

    @property
    def client_manager(self) -> ClientManager:
        """Return the zigbee application controller."""
        return self._client_manager

    async def start_server(self) -> None:
        """Start the websocket server."""
        assert self._ws_server is None
        self._stopped_event.clear()
        self._ws_server = await websockets.serve(
            self.client_manager.add_client,
            self.config.ws_server_config.host,
            self.config.ws_server_config.port,
            logger=_LOGGER,
        )
        if self.config.ws_server_config.network_auto_start:
            await self.async_initialize()
            await self.async_initialize_devices_and_entities()

    async def async_initialize(self) -> None:
        """Initialize controller and connect radio."""
        await super().async_initialize()
        self.on_all_events(self.client_manager.broadcast)

    async def stop_server(self) -> None:
        """Stop the websocket server."""
        if self._ws_server is None:
            self._stopped_event.set()
            return

        assert self._ws_server is not None

        await self.shutdown()

        self._ws_server.close()
        await self._ws_server.wait_closed()
        self._ws_server = None

        self._stopped_event.set()

    async def wait_closed(self) -> None:
        """Wait until the server is not running."""
        await self._stopped_event.wait()
        _LOGGER.info("Server stopped. Completing remaining tasks...")
        tasks = [t for t in self._tracked_ws_tasks if not (t.done() or t.cancelled())]
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

    def track_ws_task(self, task: asyncio.Task) -> None:
        """Create a tracked ws task."""
        self._tracked_ws_tasks.add(task)
        task.add_done_callback(self._tracked_ws_tasks.remove)

    async def async_block_till_done(self, wait_background_tasks=False):
        """Block until all pending work is done."""
        # To flush out any call_soon_threadsafe
        await asyncio.sleep(0.001)
        start_time: float | None = None

        while self._tracked_ws_tasks:
            pending = [task for task in self._tracked_ws_tasks if not task.done()]
            self._tracked_ws_tasks.clear()
            if pending:
                await self._await_and_log_pending(pending)

                if start_time is None:
                    # Avoid calling monotonic() until we know
                    # we may need to start logging blocked tasks.
                    start_time = 0
                elif start_time == 0:
                    # If we have waited twice then we set the start
                    # time
                    start_time = time.monotonic()
                elif time.monotonic() - start_time > BLOCK_LOG_TIMEOUT:
                    # We have waited at least three loops and new tasks
                    # continue to block. At this point we start
                    # logging all waiting tasks.
                    for task in pending:
                        _LOGGER.debug("Waiting for task: %s", task)
            else:
                await asyncio.sleep(0.001)
        await super().async_block_till_done(wait_background_tasks=wait_background_tasks)

    async def __aenter__(self) -> WebSocketServerGateway:
        """Enter the context manager."""
        await self.start_server()
        return self

    async def __aexit__(
        self, exc_type: Exception, exc_value: str, traceback: TracebackType
    ) -> None:
        """Exit the context manager."""
        await self.stop_server()
        await self.wait_closed()

    def _register_api_commands(self) -> None:
        """Load server API commands."""

        load_zigbee_controller_api(self)
        load_platform_entity_apis(self)
        load_client_api(self)


CONNECT_TIMEOUT = 10


class WebSocketClientGateway(BaseGateway):
    """ZHA gateway implementation for a websocket client."""

    def __init__(self, config: ZHAData) -> None:
        """Initialize the websocket client gateway."""
        super().__init__(config)
        self._ws_server_url: str = (
            f"ws://{config.ws_client_config.host}:{config.ws_client_config.port}"
        )
        self._client: Client = Client(
            self._ws_server_url, config.ws_client_config.aiohttp_session
        )
        self._devices: dict[EUI64, WebSocketClientDevice] = {}
        self._groups: dict[int, WebSocketClientGroup] = {}
        self.coordinator_zha_device: WebSocketClientDevice = None  # type: ignore[assignment]
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
        self._client.on_all_events(self._handle_event_protocol)

    @property
    def client(self) -> Client:
        """Return the client."""
        return self._client

    @property
    def devices(self) -> dict[EUI64, WebSocketClientDevice]:
        """Return devices."""
        return self._devices

    @property
    def groups(self) -> dict[int, WebSocketClientGroup]:
        """Return groups."""
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

    async def __aenter__(self) -> WebSocketClientGateway:
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
        """Restore ZHA devices from zigpy application state."""
        response_devices = await self.devices_helper.get_devices()
        for ieee, device in response_devices.items():
            self._devices[ieee] = self.get_or_create_device(device)

    async def load_groups(self) -> None:
        """Initialize ZHA groups."""
        response_groups = await self.groups_helper.get_groups()
        for group_id, group in response_groups.items():
            self._groups[group_id] = WebSocketClientGroup(group, self)

    async def _async_initialize(self) -> None:
        """Initialize controller and connect radio."""

        await self.load_devices()

        self.coordinator_zha_device = self.get_or_create_device(
            self._find_coordinator_device()
        )

        await self.load_groups()

    def _find_coordinator_device(self) -> zigpy.device.Device:
        """Find the coordinator device."""
        for device in self._devices.values():
            if device.is_active_coordinator:
                return device

    async def async_initialize_devices_and_entities(self) -> None:
        """Initialize devices and load entities."""

    def get_or_create_device(
        self, zigpy_device: zigpy.device.Device | ExtendedDeviceInfo
    ) -> WebSocketClientDevice:
        """Get or create a ZHA device."""
        if (zha_device := self._devices.get(zigpy_device.ieee)) is None:
            zha_device = WebSocketClientDevice(zigpy_device, self)
            self._devices[zigpy_device.ieee] = zha_device
        else:
            self._devices[zigpy_device.ieee]._extended_device_info = zigpy_device
        return zha_device

    async def async_create_zigpy_group(
        self,
        name: str,
        members: list[GroupMemberReference] | None,
        group_id: int | None = None,
    ) -> WebSocketClientGroup | None:
        """Create a new Zigpy Zigbee group."""

    async def async_remove_device(self, ieee: EUI64) -> None:
        """Remove a device from ZHA."""

    async def async_remove_zigpy_group(self, group_id: int) -> None:
        """Remove a Zigbee group from Zigpy."""

    async def shutdown(self) -> None:
        """Stop ZHA Controller Application."""

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

        self.emit(ZHA_GW_MSG_DEVICE_JOINED, event)

    def handle_raw_device_initialized(self, event: RawDeviceInitializedEvent) -> None:
        """Handle a device initialization without quirks loaded."""

        self.emit(ZHA_GW_MSG_RAW_INIT, event)

    def handle_device_fully_initialized(
        self, event: DeviceFullyInitializedEvent
    ) -> None:
        """Handle device joined and basic information discovered."""
        device_model = event.device_info
        _LOGGER.info("Device %s - %s initialized", device_model.ieee, device_model.nwk)
        if device_model.ieee in self.devices:
            self.devices[device_model.ieee]._extended_device_info = device_model
        else:
            self._devices[device_model.ieee] = self.get_or_create_device(device_model)
        self.emit(ControllerEvents.DEVICE_FULLY_INITIALIZED, event)

    def handle_device_left(self, event: DeviceLeftEvent) -> None:
        """Handle device leaving the network."""
        _LOGGER.info("Device %s - %s left", event.ieee, event.nwk)
        self.emit(ZHA_GW_MSG_DEVICE_LEFT, event)

    def handle_device_removed(self, event: DeviceRemovedEvent) -> None:
        """Handle device being removed from the network."""
        device = event.device_info
        _LOGGER.info(
            "Device %s - %s has been removed from the network", device.ieee, device.nwk
        )
        self._devices.pop(device.ieee, None)
        self.emit(ZHA_GW_MSG_DEVICE_REMOVED, event)

    def handle_group_member_removed(self, event: GroupMemberRemovedEvent) -> None:
        """Handle group member removed event."""
        if event.group_info.group_id in self.groups:
            self.groups[event.group_info.group_id]._group_info = event.group_info
        self.emit(ControllerEvents.GROUP_MEMBER_REMOVED, event)

    def handle_group_member_added(self, event: GroupMemberAddedEvent) -> None:
        """Handle group member added event."""
        if event.group_info.group_id in self.groups:
            self.groups[event.group_info.group_id]._group_info = event.group_info
        self.emit(ControllerEvents.GROUP_MEMBER_ADDED, event)

    def handle_group_added(self, event: GroupAddedEvent) -> None:
        """Handle group added event."""
        if event.group_info.group_id in self.groups:
            self.groups[event.group_info.group_id]._group_info = event.group_info
        else:
            self.groups[event.group_info.group_id] = WebSocketClientGroup(
                event.group_info, self
            )
        self.emit(ControllerEvents.GROUP_ADDED, event)

    def handle_group_removed(self, event: GroupRemovedEvent) -> None:
        """Handle group removed event."""
        if event.group_info.group_id in self.groups:
            self.groups.pop(event.group_info.group_id)
        self.emit(ControllerEvents.GROUP_REMOVED, event)

    def connection_lost(self, exc: Exception) -> None:
        """Handle connection lost event."""
