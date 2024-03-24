"""Representation of ZHA updates."""

from __future__ import annotations

from enum import IntFlag, StrEnum
import functools
import logging
import math
from typing import TYPE_CHECKING, Any, Final

from zigpy.ota import OtaImageWithMetadata
from zigpy.zcl.clusters.general import Ota
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import EntityCategory, PlatformEntity
from zha.application.registries import PLATFORM_ENTITIES
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers.const import CLUSTER_HANDLER_OTA

if TYPE_CHECKING:
    # from zigpy.application import ControllerApplication

    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice

_LOGGER = logging.getLogger(__name__)

CONFIG_DIAGNOSTIC_MATCH = functools.partial(
    PLATFORM_ENTITIES.config_diagnostic_match, Platform.UPDATE
)

# pylint: disable=unused-argument
# pylint: disable=pointless-string-statement
"""TODO do this in discovery?
zha_data = get_zha_data(hass)
entities_to_create = zha_data.platforms[Platform.UPDATE]

coordinator = ZHAFirmwareUpdateCoordinator(
    hass, get_zha_gateway(hass).application_controller
)
"""

# pylint: disable=pointless-string-statement
"""TODO find a solution for this
class ZHAFirmwareUpdateCoordinator(DataUpdateCoordinator[None]):  # pylint: disable=hass-enforce-coordinator-module
    #Firmware update coordinator that broadcasts updates network-wide.

    def __init__(
        self, hass: HomeAssistant, controller_application: ControllerApplication
    ) -> None:
        #Initialize the coordinator.
        super().__init__(
            hass,
            _LOGGER,
            name="ZHA firmware update coordinator",
            update_method=self.async_update_data,
        )
        self.controller_application = controller_application

    async def async_update_data(self) -> None:
        #Fetch the latest firmware update data.
        # Broadcast to all devices
        await self.controller_application.ota.broadcast_notify(jitter=100)
"""


class UpdateDeviceClass(StrEnum):
    """Device class for update."""

    FIRMWARE = "firmware"


class UpdateEntityFeature(IntFlag):
    """Supported features of the update entity."""

    INSTALL = 1
    SPECIFIC_VERSION = 2
    PROGRESS = 4
    BACKUP = 8
    RELEASE_NOTES = 16


SERVICE_INSTALL: Final = "install"
SERVICE_SKIP: Final = "skip"

ATTR_AUTO_UPDATE: Final = "auto_update"
ATTR_BACKUP: Final = "backup"
ATTR_INSTALLED_VERSION: Final = "installed_version"
ATTR_IN_PROGRESS: Final = "in_progress"
ATTR_LATEST_VERSION: Final = "latest_version"
ATTR_RELEASE_SUMMARY: Final = "release_summary"
ATTR_RELEASE_URL: Final = "release_url"
ATTR_SKIPPED_VERSION: Final = "skipped_version"
ATTR_TITLE: Final = "title"
ATTR_VERSION: Final = "version"


# old base classes: CoordinatorEntity[ZHAFirmwareUpdateCoordinator], UpdateEntity
@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_OTA)
class ZHAFirmwareUpdateEntity(PlatformEntity):
    """Representation of a ZHA firmware update entity."""

    _unique_id_suffix = "firmware_update"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.SPECIFIC_VERSION
    )
    _attr_auto_update: bool = False
    _attr_installed_version: str | None = None
    _attr_in_progress: bool | int = False
    _attr_latest_version: str | None = None
    _attr_release_summary: str | None = None
    _attr_release_url: str | None = None
    _attr_state: None = None
    _attr_title: str | None = None

    def __init__(
        self,
        unique_id: str,
        zha_device: ZHADevice,
        channels: list[ClusterHandler],
        coordinator,
        **kwargs: Any,
    ) -> None:
        """Initialize the ZHA update entity."""
        super().__init__(unique_id, zha_device, channels, **kwargs)
        # CoordinatorEntity.__init__(self, coordinator)

        self._ota_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_OTA
        ]
        self._attr_installed_version: str | None = self._get_cluster_version()
        self._attr_latest_version = self._attr_installed_version
        self._latest_firmware: OtaImageWithMetadata | None = None

    def _get_cluster_version(self) -> str | None:
        """Synchronize current file version with the cluster."""

        device = self._ota_cluster_handler._endpoint.device  # pylint: disable=protected-access

        if self._ota_cluster_handler.current_file_version is not None:
            return f"0x{self._ota_cluster_handler.current_file_version:08x}"

        if device.sw_version is not None:
            return device.sw_version

        return None

    def attribute_updated(self, attrid: int, name: str, value: Any) -> None:
        """Handle attribute updates on the OTA cluster."""
        if attrid == Ota.AttributeDefs.current_file_version.id:
            self._attr_installed_version = f"0x{value:08x}"
            self.maybe_emit_state_changed_event()

    def device_ota_update_available(
        self, image: OtaImageWithMetadata, current_file_version: int
    ) -> None:
        """Handle ota update available signal from Zigpy."""
        self._latest_firmware = image
        self._attr_latest_version = f"0x{image.version:08x}"
        self._attr_installed_version = f"0x{current_file_version:08x}"

        if image.metadata.changelog:
            self._attr_release_summary = image.metadata.changelog

        self.maybe_emit_state_changed_event()

    def _update_progress(self, current: int, total: int, progress: float) -> None:
        """Update install progress on event."""
        # If we are not supposed to be updating, do nothing
        if self._attr_in_progress is False:
            return

        # Remap progress to 2-100 to avoid 0 and 1
        self._attr_in_progress = int(math.ceil(2 + 98 * progress / 100))
        self.maybe_emit_state_changed_event()

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        assert self._latest_firmware is not None

        # Set the progress to an indeterminate state
        self._attr_in_progress = True
        self.maybe_emit_state_changed_event()

        try:
            result = await self.device.device.update_firmware(
                image=self._latest_firmware,
                progress_callback=self._update_progress,
            )
        except Exception as ex:
            raise ZHAException(f"Update was not successful: {ex}") from ex

        # If we tried to install firmware that is no longer compatible with the device,
        # bail out
        if result == Status.NO_IMAGE_AVAILABLE:
            self._attr_latest_version = self._attr_installed_version
            self.maybe_emit_state_changed_event()

        # If the update finished but was not successful, we should also throw an error
        if result != Status.SUCCESS:
            raise ZHAException(f"Update was not successful: {result}")

        # Clear the state
        self._latest_firmware = None
        self._attr_in_progress = False
        self.maybe_emit_state_changed_event()

    # pylint: disable=pointless-string-statement
    """TODO
    async def async_added_to_hass(self) -> None:
        #Call when entity is added.
        await super().async_added_to_hass()

        # OTA events are sent by the device
        self.zha_device.device.add_listener(self)
        self.async_accept_signal(
            self._ota_cluster_handler, SIGNAL_ATTR_UPDATED, self.attribute_updated
        )
    """

    async def on_remove(self) -> None:
        """Call when entity will be removed."""
        await super().on_remove()
        self._attr_in_progress = False

    async def async_update(self) -> None:
        """Update the entity."""
        # await CoordinatorEntity.async_update(self)
        await super().async_update()
