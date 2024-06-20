"""Virtual gateway for Zigbee Home Automation."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from functools import cached_property
import logging
import time
from typing import Any, Final, Self, TypeVar, cast

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
from zigpy.state import State
from zigpy.types.named import EUI64

from zha.application import discovery
from zha.application.const import (
    CONF_USE_THREAD,
    UNKNOWN_MANUFACTURER,
    UNKNOWN_MODEL,
    ZHA_GW_MSG,
    ZHA_GW_MSG_CONNECTION_LOST,
    ZHA_GW_MSG_DEVICE_FULL_INIT,
    ZHA_GW_MSG_DEVICE_JOINED,
    ZHA_GW_MSG_DEVICE_LEFT,
    ZHA_GW_MSG_DEVICE_REMOVED,
    ZHA_GW_MSG_GROUP_ADDED,
    ZHA_GW_MSG_GROUP_MEMBER_ADDED,
    ZHA_GW_MSG_GROUP_MEMBER_REMOVED,
    ZHA_GW_MSG_GROUP_REMOVED,
    ZHA_GW_MSG_RAW_INIT,
    RadioType,
)
from zha.application.helpers import DeviceAvailabilityChecker, GlobalUpdater, ZHAData
from zha.async_ import (
    AsyncUtilMixin,
    create_eager_task,
    gather_with_limited_concurrency,
)
from zha.event import EventBase
from zha.zigbee.device import Device, DeviceInfo, DeviceStatus, ExtendedDeviceInfo
from zha.zigbee.group import Group, GroupInfo, GroupMemberReference

BLOCK_LOG_TIMEOUT: Final[int] = 60
_R = TypeVar("_R")
_LOGGER = logging.getLogger(__name__)


class DevicePairingStatus(Enum):
    """Status of a device."""

    PAIRED = 1
    INTERVIEW_COMPLETE = 2
    CONFIGURED = 3
    INITIALIZED = 4


@dataclass(kw_only=True, frozen=True)
class DeviceInfoWithPairingStatus(DeviceInfo):
    """Information about a device with pairing status."""

    pairing_status: DevicePairingStatus


@dataclass(kw_only=True, frozen=True)
class ExtendedDeviceInfoWithPairingStatus(ExtendedDeviceInfo):
    """Information about a device with pairing status."""

    pairing_status: DevicePairingStatus


@dataclass(kw_only=True, frozen=True)
class DeviceJoinedDeviceInfo:
    """Information about a device."""

    ieee: str
    nwk: int
    pairing_status: DevicePairingStatus


@dataclass(kw_only=True, frozen=True)
class ConnectionLostEvent:
    """Event to signal that the connection to the radio has been lost."""

    event_type: Final[str] = ZHA_GW_MSG
    event: Final[str] = ZHA_GW_MSG_CONNECTION_LOST
    exception: Exception | None = None


@dataclass(kw_only=True, frozen=True)
class DeviceJoinedEvent:
    """Event to signal that a device has joined the network."""

    device_info: DeviceJoinedDeviceInfo
    event_type: Final[str] = ZHA_GW_MSG
    event: Final[str] = ZHA_GW_MSG_DEVICE_JOINED


@dataclass(kw_only=True, frozen=True)
class DeviceLeftEvent:
    """Event to signal that a device has left the network."""

    ieee: EUI64
    nwk: int
    event_type: Final[str] = ZHA_GW_MSG
    event: Final[str] = ZHA_GW_MSG_DEVICE_LEFT


@dataclass(kw_only=True, frozen=True)
class RawDeviceInitializedDeviceInfo(DeviceJoinedDeviceInfo):
    """Information about a device that has been initialized without quirks loaded."""

    model: str
    manufacturer: str
    signature: dict[str, Any]


@dataclass(kw_only=True, frozen=True)
class RawDeviceInitializedEvent:
    """Event to signal that a device has been initialized without quirks loaded."""

    device_info: RawDeviceInitializedDeviceInfo
    event_type: Final[str] = ZHA_GW_MSG
    event: Final[str] = ZHA_GW_MSG_RAW_INIT


@dataclass(kw_only=True, frozen=True)
class DeviceFullInitEvent:
    """Event to signal that a device has been fully initialized."""

    device_info: ExtendedDeviceInfoWithPairingStatus
    new_join: bool = False
    event_type: Final[str] = ZHA_GW_MSG
    event: Final[str] = ZHA_GW_MSG_DEVICE_FULL_INIT


@dataclass(kw_only=True, frozen=True)
class GroupEvent:
    """Event to signal a group event."""

    event: str
    group_info: GroupInfo
    event_type: Final[str] = ZHA_GW_MSG


@dataclass(kw_only=True, frozen=True)
class DeviceRemovedEvent:
    """Event to signal that a device has been removed."""

    device_info: ExtendedDeviceInfo
    event_type: Final[str] = ZHA_GW_MSG
    event: Final[str] = ZHA_GW_MSG_DEVICE_REMOVED


class Gateway(AsyncUtilMixin, EventBase):
    """Gateway that handles events that happen on the ZHA Zigbee network."""

    def __init__(self, config: ZHAData) -> None:
        """Initialize the gateway."""
        super().__init__()
        self.config: ZHAData = config
        self._devices: dict[EUI64, Device] = {}
        self._groups: dict[int, Group] = {}
        self.application_controller: ControllerApplication = None
        self.coordinator_zha_device: Device = None  # type: ignore[assignment]

        self.shutting_down: bool = False
        self._reload_task: asyncio.Task | None = None

        self.global_updater: GlobalUpdater = GlobalUpdater(self)
        self._device_availability_checker: DeviceAvailabilityChecker = (
            DeviceAvailabilityChecker(self)
        )
        self.config.gateway = self

    def get_application_controller_data(self) -> tuple[ControllerApplication, dict]:
        """Get an uninitialized instance of a zigpy `ControllerApplication`."""
        radio_type = RadioType[self.config.config.coordinator_configuration.radio_type]
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
            and radio_type is RadioType.ezsp
            and app_config[CONF_DEVICE][CONF_DEVICE_PATH].startswith("socket://")
        ):
            app_config[CONF_USE_THREAD] = False

        return radio_type.controller, radio_type.controller.SCHEMA(app_config)

    @classmethod
    async def async_from_config(cls, config: ZHAData) -> Self:
        """Create an instance of a gateway from config objects."""
        instance = cls(config)
        await instance.async_initialize()
        return instance

    async def async_initialize(self) -> None:
        """Initialize controller and connect radio."""
        discovery.DEVICE_PROBE.initialize(self)
        discovery.ENDPOINT_PROBE.initialize(self)
        discovery.GROUP_PROBE.initialize(self)

        if self.config.config.quirks_configuration.enabled:
            await self.async_add_executor_job(
                setup_quirks, self.config.config.quirks_configuration.custom_quirks_path
            )

        self.shutting_down = False

        app_controller_cls, app_config = self.get_application_controller_data()
        app = await app_controller_cls.new(
            config=app_config,
            auto_form=False,
            start_radio=False,
        )

        try:
            await app.startup(auto_form=True)
        except Exception:
            # Explicitly shut down the controller application on failure
            await app.shutdown()
            raise

        self.application_controller = app

        self.coordinator_zha_device = self.get_or_create_device(
            self._find_coordinator_device()
        )

        self.load_devices()
        self.load_groups()

        self.application_controller.add_listener(self)
        self.application_controller.groups.add_listener(self)
        self.global_updater.start()
        self._device_availability_checker.start()

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
                platform_entity = platform_entity_class.create_platform_entity(
                    *args, **kw_args
                )
                if platform_entity:
                    _LOGGER.debug(
                        "Platform entity data: %s", platform_entity.info_object
                    )
            self.config.platforms[platform].clear()

    @cached_property
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
            await self.async_fetch_updated_state_mains()
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
                    signature=device.get_signature(),
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
        self._emit_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_MEMBER_REMOVED)

    def group_member_added(
        self, zigpy_group: zigpy.group.Group, endpoint: zigpy.endpoint.Endpoint
    ) -> None:
        """Handle zigpy group member added event."""
        # need to handle endpoint correctly on groups
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.clear_caches()
        discovery.GROUP_PROBE.discover_group_entities(zha_group)
        zha_group.info("group_member_added - endpoint: %s", endpoint)
        self._emit_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_MEMBER_ADDED)

    def group_added(self, zigpy_group: zigpy.group.Group) -> None:
        """Handle zigpy group added event."""
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.info("group_added")
        # need to dispatch for entity creation here
        self._emit_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_ADDED)

    def group_removed(self, zigpy_group: zigpy.group.Group) -> None:
        """Handle zigpy group removed event."""
        self._emit_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_REMOVED)
        zha_group = self._groups.pop(zigpy_group.group_id)
        zha_group.info("group_removed")

    def _emit_group_gateway_message(  # pylint: disable=unused-argument
        self,
        zigpy_group: zigpy.group.Group,
        gateway_message_type: str,
    ) -> None:
        """Send the gateway event for a zigpy group event."""
        zha_group = self._groups.get(zigpy_group.group_id)
        if zha_group is not None:
            self.emit(
                gateway_message_type,
                GroupEvent(
                    event=gateway_message_type,
                    group_info=zha_group.info_object,
                ),
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

    @property
    def devices(self) -> dict[EUI64, Device]:
        """Return devices."""
        return self._devices

    @property
    def groups(self) -> dict[int, Group]:
        """Return groups."""
        return self._groups

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
            DeviceFullInitEvent(device_info=device_info),
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
            DeviceFullInitEvent(device_info=device_info, new_join=True),
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
            DeviceFullInitEvent(device_info=device_info),
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
