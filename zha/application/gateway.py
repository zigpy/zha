"""Virtual gateway for Zigbee Home Automation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Coroutine
from contextlib import suppress
from datetime import timedelta
from enum import Enum
import logging
import time
from typing import Any, Final, Self, TypeVar, cast

from zigpy.application import ControllerApplication
from zigpy.config import (
    CONF_DATABASE,
    CONF_DEVICE,
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
    CONF_RADIO_TYPE,
    CONF_USE_THREAD,
    CONF_ZIGPY,
    DATA_ZHA,
    DEFAULT_DATABASE_NAME,
    DEVICE_PAIRING_STATUS,
    ZHA_GW_MSG_GROUP_ADDED,
    ZHA_GW_MSG_GROUP_MEMBER_ADDED,
    ZHA_GW_MSG_GROUP_MEMBER_REMOVED,
    ZHA_GW_MSG_GROUP_REMOVED,
    RadioType,
)
from zha.async_ import cancelling, create_eager_task, gather_with_limited_concurrency
from zha.zigbee.device import DeviceStatus, ZHADevice
from zha.zigbee.group import Group, GroupMember

BLOCK_LOG_TIMEOUT: Final[int] = 60
_R = TypeVar("_R")
_LOGGER = logging.getLogger(__name__)


class DevicePairingStatus(Enum):
    """Status of a device."""

    PAIRED = 1
    INTERVIEW_COMPLETE = 2
    CONFIGURED = 3
    INITIALIZED = 4


class ZHAGateway:
    """Gateway that handles events that happen on the ZHA Zigbee network."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the gateway."""
        self._config: dict[str, Any] = config
        self._devices: dict[EUI64, ZHADevice] = {}
        self._groups: dict[int, Group] = {}
        self.application_controller: ControllerApplication = None
        self.coordinator_zha_device: ZHADevice = None  # type: ignore[assignment]
        self._unsubs: list[Callable[[], None]] = []

        self.shutting_down: bool = False
        self._reload_task: asyncio.Task | None = None
        self.data: dict[str, Any] = {}
        self._tracked_completable_tasks: list[asyncio.Task] = []
        self._device_init_tasks: dict[EUI64, asyncio.Task] = {}
        self._background_tasks: set[asyncio.Future[Any]] = set()

    def get_application_controller_data(self) -> tuple[ControllerApplication, dict]:
        """Get an uninitialized instance of a zigpy `ControllerApplication`."""
        radio_type = RadioType[self.config_entry.data[CONF_RADIO_TYPE]]

        app_config = self._config.get(CONF_ZIGPY, {})
        database = self._config.get(
            CONF_DATABASE,
            self.hass.config.path(DEFAULT_DATABASE_NAME),
        )
        app_config[CONF_DATABASE] = database
        app_config[CONF_DEVICE] = self.config_entry.data[CONF_DEVICE]

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

        # pylint: disable=pointless-string-statement
        """TODO
        # Local import to avoid circular dependencies
        # pylint: disable-next=import-outside-toplevel
        from homeassistant.components.homeassistant_hardware.silabs_multiprotocol_addon import (
            is_multiprotocol_url,
        )

        # Until we have a way to coordinate channels with the Thread half of multi-PAN,
        # stick to the old zigpy default of channel 15 instead of dynamically scanning
        if (
            is_multiprotocol_url(app_config[CONF_DEVICE][CONF_DEVICE_PATH])
            and app_config.get(CONF_NWK, {}).get(CONF_NWK_CHANNEL) is None
        ):
            app_config.setdefault(CONF_NWK, {})[CONF_NWK_CHANNEL] = 15
        """

        return radio_type.controller, radio_type.controller.SCHEMA(app_config)

    @classmethod
    async def async_from_config(cls, config: dict[str, Any]) -> Self:
        """Create an instance of a gateway from config objects."""
        instance = cls(config)
        await instance.async_initialize()
        return instance

    async def async_initialize(self) -> None:
        """Initialize controller and connect radio."""
        discovery.PROBE.initialize(self)
        discovery.GROUP_PROBE.initialize(self)

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

    def connection_lost(self, exc: Exception) -> None:
        """Handle connection lost event."""
        _LOGGER.debug("Connection to the radio was lost: %r", exc)

        if self.shutting_down:
            return

        # Ensure we do not queue up multiple resets
        if self._reload_task is not None:
            _LOGGER.debug("Ignoring reset, one is already running")
            return

        # pylint: disable=pointless-string-statement
        """TODO
        self._reload_task = asyncio.create_task(
            self.hass.config_entries.async_reload(self.config_entry.entry_id)
        )
        """

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
        self._devices = {
            zigpy_device.ieee: ZHADevice.new(zigpy_device, self)
            for zigpy_device in self.application_controller.devices.values()
        }
        self.create_platform_entities()
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
            for platform_entity_class, args in self.data[platform]:
                platform_entity = platform_entity_class.create_platform_entity(*args)
                if platform_entity:
                    _LOGGER.debug("Platform entity data: %s", platform_entity.to_json())
            self.data[platform].clear()

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
            await self.async_fetch_updated_state_mains()
            _LOGGER.debug("Allowing polled requests")
            self.data[DATA_ZHA].allow_polling = True

        # background the fetching of state for mains powered devices
        self.async_create_background_task(
            fetch_updated_state(), "zha.gateway-fetch_updated_state"
        )

    async def stop_network(self) -> None:
        """Stop the Zigbee network."""
        if self.application_controller is None:
            return
        tasks = [
            t
            for t in self._device_init_tasks.values()
            if not (t.done() or t.cancelled())
        ]
        for task in tasks:
            _LOGGER.debug("Cancelling task: %s", task)
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

        for device in self._devices.values():
            await device.on_remove()

        await self.application_controller.pre_shutdown()
        self.application_controller = None
        await asyncio.sleep(0.1)  # give bellows thread callback a chance to run
        self._devices.clear()
        self._groups.clear()

    def device_joined(self, device: zigpy.device.Device) -> None:
        """Handle device joined.

        At this point, no information about the device is known other than its
        address
        """
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(
            self.hass,
            ZHA_GW_MSG,
            {
                ATTR_TYPE: ZHA_GW_MSG_DEVICE_JOINED,
                ZHA_GW_MSG_DEVICE_INFO: {
                    ATTR_NWK: device.nwk,
                    ATTR_IEEE: str(device.ieee),
                    DEVICE_PAIRING_STATUS: DevicePairingStatus.PAIRED.name,
                },
            },
        )
        """

    def raw_device_initialized(self, device: zigpy.device.Device) -> None:  # pylint: disable=unused-argument
        """Handle a device initialization without quirks loaded."""
        # pylint: disable=pointless-string-statement
        """TODO
        manuf = device.manufacturer
        async_dispatcher_send(
            self.hass,
            ZHA_GW_MSG,
            {
                ATTR_TYPE: ZHA_GW_MSG_RAW_INIT,
                ZHA_GW_MSG_DEVICE_INFO: {
                    ATTR_NWK: device.nwk,
                    ATTR_IEEE: str(device.ieee),
                    DEVICE_PAIRING_STATUS: DevicePairingStatus.INTERVIEW_COMPLETE.name,
                    ATTR_MODEL: device.model if device.model else UNKNOWN_MODEL,
                    ATTR_MANUFACTURER: manuf if manuf else UNKNOWN_MANUFACTURER,
                    ATTR_SIGNATURE: device.get_signature(),
                },
            },
        )
        """

    def device_initialized(self, device: zigpy.device.Device) -> None:
        """Handle device joined and basic information discovered."""
        if device.ieee in self._device_init_tasks:
            _LOGGER.warning(
                "Cancelling previous initialization task for device %s",
                str(device.ieee),
            )
            self._device_init_tasks[device.ieee].cancel()
        self._device_init_tasks[device.ieee] = asyncio.create_task(
            self.async_device_initialized(device),
            name=f"device_initialized_task_{str(device.ieee)}:0x{device.nwk:04x}",
        )

    def device_left(self, device: zigpy.device.Device) -> None:
        """Handle device leaving the network."""
        self.async_update_device(device, False)

    def group_member_removed(
        self, zigpy_group: zigpy.group.Group, endpoint: zigpy.endpoint.Endpoint
    ) -> None:
        """Handle zigpy group member removed event."""
        # need to handle endpoint correctly on groups
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.info("group_member_removed - endpoint: %s", endpoint)
        self._send_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_MEMBER_REMOVED)
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(
            self.hass, f"{SIGNAL_GROUP_MEMBERSHIP_CHANGE}_0x{zigpy_group.group_id:04x}"
        )
        """

    def group_member_added(
        self, zigpy_group: zigpy.group.Group, endpoint: zigpy.endpoint.Endpoint
    ) -> None:
        """Handle zigpy group member added event."""
        # need to handle endpoint correctly on groups
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.info("group_member_added - endpoint: %s", endpoint)
        self._send_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_MEMBER_ADDED)
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(
            self.hass, f"{SIGNAL_GROUP_MEMBERSHIP_CHANGE}_0x{zigpy_group.group_id:04x}"
        )
        """
        if len(zha_group.members) == 2:
            # we need to do this because there wasn't already
            # a group entity to remove and re-add
            discovery.GROUP_PROBE.discover_group_entities(zha_group)

    def group_added(self, zigpy_group: zigpy.group.Group) -> None:
        """Handle zigpy group added event."""
        zha_group = self.get_or_create_group(zigpy_group)
        zha_group.info("group_added")
        # need to dispatch for entity creation here
        self._send_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_ADDED)

    def group_removed(self, zigpy_group: zigpy.group.Group) -> None:
        """Handle zigpy group removed event."""
        self._send_group_gateway_message(zigpy_group, ZHA_GW_MSG_GROUP_REMOVED)
        zha_group = self._groups.pop(zigpy_group.group_id)
        zha_group.info("group_removed")

    def _send_group_gateway_message(  # pylint: disable=unused-argument
        self,
        zigpy_group: zigpy.group.Group,
        gateway_message_type: str,
    ) -> None:
        """Send the gateway event for a zigpy group event."""
        zha_group = self._groups.get(zigpy_group.group_id)
        if zha_group is not None:
            # pylint: disable=pointless-string-statement
            """TODO
            async_dispatcher_send(
                self.hass,
                ZHA_GW_MSG,
                {
                    ATTR_TYPE: gateway_message_type,
                    ZHA_GW_MSG_GROUP_INFO: zha_group.group_info,
                },
            )
            """

    def device_removed(self, device: zigpy.device.Device) -> None:
        """Handle device being removed from the network."""
        _LOGGER.info("Removing device %s - %s", device.ieee, f"0x{device.nwk:04x}")
        zha_device = self._devices.pop(device.ieee, None)
        if zha_device is not None:
            self.track_task(
                create_eager_task(
                    zha_device.on_remove(), name="ZHAGateway._async_remove_device"
                )
            )
            # pylint: disable=pointless-string-statement
            """TODO
            ### zhawss
            self.server.client_manager.broadcast(
                {
                    DEVICE: device.zha_device_info,
                    MESSAGE_TYPE: MessageTypes.EVENT,
                    EVENT_TYPE: EventTypes.CONTROLLER_EVENT,
                    EVENT: ControllerEvents.DEVICE_REMOVED,
                }
            )
            ### HA
            device_info = zha_device.zha_device_info
            zha_device.async_cleanup_handles()
            async_dispatcher_send(self.hass, f"{SIGNAL_REMOVE}_{str(zha_device.ieee)}")
            self.hass.async_create_task(
                self._async_remove_device(zha_device, entity_refs),
                "ZHAGateway._async_remove_device",
            )
            if device_info is not None:
                async_dispatcher_send(
                    self.hass,
                    ZHA_GW_MSG,
                    {
                        ATTR_TYPE: ZHA_GW_MSG_DEVICE_REMOVED,
                        ZHA_GW_MSG_DEVICE_INFO: device_info,
                    },
                )
            """

    def get_device(self, ieee: EUI64) -> ZHADevice | None:
        """Return ZHADevice for given ieee."""
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
    def devices(self) -> dict[EUI64, ZHADevice]:
        """Return devices."""
        return self._devices

    @property
    def groups(self) -> dict[int, Group]:
        """Return groups."""
        return self._groups

    def block_till_done(self) -> None:
        """Block until all pending work is done."""
        asyncio.run_coroutine_threadsafe(
            self.async_block_till_done(), asyncio.get_running_loop()
        ).result()

    async def async_block_till_done(self, wait_background_tasks: bool = False) -> None:
        """Block until all pending work is done."""
        # To flush out any call_soon_threadsafe
        await asyncio.sleep(0)
        start_time: float | None = None
        current_task = asyncio.current_task()
        while tasks := [
            task
            for task in (
                self._tracked_completable_tasks
                | self._background_tasks
                | self._device_init_tasks
                if wait_background_tasks
                else self._tracked_completable_tasks | self._device_init_tasks
            )
            if task is not current_task and not cancelling(task)
        ]:
            await self._await_and_log_pending(tasks)

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
                for task in tasks:
                    _LOGGER.debug("Waiting for task: %s", task)

    async def _await_and_log_pending(
        self, pending: Collection[asyncio.Future[Any]]
    ) -> None:
        """Await and log tasks that take a long time."""
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
        task.add_done_callback(self._tracked_completable_tasks.remove)

    def get_or_create_device(self, zigpy_device: zigpy.device.Device) -> ZHADevice:
        """Get or create a ZHA device."""
        if (zha_device := self._devices.get(zigpy_device.ieee)) is None:
            zha_device = ZHADevice.new(zigpy_device, self)
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
        self, sender: zigpy.device.Device, available: bool = True
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

        device_info = zha_device.zha_device_info
        device_info[DEVICE_PAIRING_STATUS] = DevicePairingStatus.INITIALIZED.name
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(
            self.hass,
            ZHA_GW_MSG,
            {
                ATTR_TYPE: ZHA_GW_MSG_DEVICE_FULL_INIT,
                ZHA_GW_MSG_DEVICE_INFO: device_info,
            },
        )
        """

    async def _async_device_joined(self, zha_device: ZHADevice) -> None:
        zha_device.available = True
        device_info = zha_device.device_info
        await zha_device.async_configure()
        device_info[DEVICE_PAIRING_STATUS] = DevicePairingStatus.CONFIGURED.name
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(
            self.hass,
            ZHA_GW_MSG,
            {
                ATTR_TYPE: ZHA_GW_MSG_DEVICE_FULL_INIT,
                ZHA_GW_MSG_DEVICE_INFO: device_info,
            },
        )
        """
        await zha_device.async_initialize(from_cache=False)
        self.create_platform_entities()
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(self.hass, SIGNAL_ADD_ENTITIES)
        """

    async def _async_device_rejoined(self, zha_device: ZHADevice) -> None:
        _LOGGER.debug(
            "skipping discovery for previously discovered device - %s:%s",
            zha_device.nwk,
            zha_device.ieee,
        )
        # we don't have to do this on a nwk swap
        # but we don't have a way to tell currently
        await zha_device.async_configure()
        device_info = zha_device.device_info
        device_info[DEVICE_PAIRING_STATUS] = DevicePairingStatus.CONFIGURED.name
        # pylint: disable=pointless-string-statement
        """TODO
        async_dispatcher_send(
            self.hass,
            ZHA_GW_MSG,
            {
                ATTR_TYPE: ZHA_GW_MSG_DEVICE_FULL_INIT,
                ZHA_GW_MSG_DEVICE_INFO: device_info,
            },
        )
        """
        # force async_initialize() to fire so don't explicitly call it
        zha_device.available = False
        zha_device.update_available(True)

    async def async_create_zigpy_group(
        self,
        name: str,
        members: list[GroupMember] | None,
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

        _LOGGER.debug("Shutting down ZHA ControllerApplication")
        self.shutting_down = True

        for unsubscribe in self._unsubs:
            unsubscribe()
        for device in self.devices.values():
            device.async_cleanup_handles()
        await self.application_controller.shutdown()

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
            self.async_update_device(sender, available=True)

    def async_create_background_task(
        self, target: Coroutine[Any, Any, _R], name: str, eager_start: bool = False
    ) -> asyncio.Task[_R]:
        """Create a task from within the event loop.

        This type of task is for background tasks that usually run for
        the lifetime of Home Assistant or an integration's setup.

        A background task is different from a normal task:

          - Will not block startup
          - Will be automatically cancelled on shutdown
          - Calls to async_block_till_done will not wait for completion

        If you are using this in your integration, use the create task
        methods on the config entry instead.

        This method must be run in the event loop.
        """
        if eager_start:
            task = create_eager_task(target, name=name, loop=asyncio.get_running_loop())
            if task.done():
                return task
        else:
            # Use loop.create_task
            # to avoid the extra function call in asyncio.create_task.
            task = asyncio.get_running_loop().create_task(target, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.remove)
        return task
