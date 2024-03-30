"""Representation of ZHA updates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag, StrEnum
import functools
import logging
import math
from typing import TYPE_CHECKING, Any, Final, final

from awesomeversion import AwesomeVersion, AwesomeVersionCompareException
from zigpy.ota import OtaImageWithMetadata
from zigpy.zcl.clusters.general import Ota
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import EntityCategory, PlatformEntity, PlatformEntityInfo
from zha.application.registries import PLATFORM_ENTITIES
from zha.decorators import callback
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_OTA,
)
from zha.zigbee.endpoint import Endpoint

if TYPE_CHECKING:
    # from zigpy.application import ControllerApplication

    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device

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

ATTR_BACKUP: Final = "backup"
ATTR_INSTALLED_VERSION: Final = "installed_version"
ATTR_IN_PROGRESS: Final = "in_progress"
ATTR_LATEST_VERSION: Final = "latest_version"
ATTR_RELEASE_SUMMARY: Final = "release_summary"
ATTR_RELEASE_URL: Final = "release_url"
ATTR_VERSION: Final = "version"


@dataclass(frozen=True, kw_only=True)
class UpdateEntityInfo(PlatformEntityInfo):
    """Update entity info."""

    supported_features: UpdateEntityFeature
    device_class: UpdateDeviceClass
    entity_category: EntityCategory


# old base classes: CoordinatorEntity[ZHAFirmwareUpdateCoordinator], UpdateEntity
@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_OTA)
class FirmwareUpdateEntity(PlatformEntity):
    """Representation of a ZHA firmware update entity."""

    PLATFORM: Final = Platform.UPDATE

    _unique_id_suffix = "firmware_update"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.SPECIFIC_VERSION
    )
    _attr_installed_version: str | None = None
    _attr_in_progress: bool | int = False
    _attr_latest_version: str | None = None
    _attr_release_summary: str | None = None
    _attr_release_url: str | None = None

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the ZHA update entity."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        # CoordinatorEntity.__init__(self, coordinator)

        self._ota_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_OTA
        ]
        self._attr_installed_version: str | None = self._get_cluster_version()
        self._attr_latest_version = self._attr_installed_version
        self._latest_firmware: OtaImageWithMetadata | None = None

        self.device.device.add_listener(self)
        self._ota_cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

    @functools.cached_property
    def info_object(self) -> UpdateEntityInfo:
        """Return a representation of the entity."""
        return UpdateEntityInfo(
            **super().info_object.__dict__,
            supported_features=self.supported_features,
            device_class=self._attr_device_class,
            entity_category=self._attr_entity_category,
        )

    @property
    def state(self):
        """Get the state for the entity."""
        response = super().state
        response["state"] = self._state
        response.update(self.state_attributes)
        return response

    @property
    def installed_version(self) -> str | None:
        """Version installed and in use."""
        return self._attr_installed_version

    @property
    def in_progress(self) -> bool | int | None:
        """Update installation progress.

        Needs UpdateEntityFeature.PROGRESS flag to be set for it to be used.

        Can either return a boolean (True if in progress, False if not)
        or an integer to indicate the progress in from 0 to 100%.
        """
        return self._attr_in_progress

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        return self._attr_latest_version

    @property
    def release_summary(self) -> str | None:
        """Summary of the release notes or changelog.

        This is not suitable for long changelogs, but merely suitable
        for a short excerpt update description of max 255 characters.
        """
        return self._attr_release_summary

    @property
    def release_url(self) -> str | None:
        """URL to the full release notes of the latest version available."""
        return self._attr_release_url

    @property
    def supported_features(self) -> UpdateEntityFeature:
        """Flag supported features."""
        return self._attr_supported_features

    @property
    @final
    def _state(self) -> bool | None:
        """Return the entity state."""
        if (installed_version := self.installed_version) is None or (
            latest_version := self.latest_version
        ) is None:
            return None

        if latest_version == installed_version:
            return False

        try:
            return _version_is_newer(latest_version, installed_version)
        except AwesomeVersionCompareException:
            # Can't compare versions, already tried exact match
            return True

    @final
    @property
    def state_attributes(self) -> dict[str, Any] | None:
        """Return state attributes."""
        if (release_summary := self.release_summary) is not None:
            release_summary = release_summary[:255]

        # If entity supports progress, return the in_progress value.
        # Otherwise, we use the internal progress value.
        if UpdateEntityFeature.PROGRESS in self.supported_features:
            in_progress = self.in_progress
        else:
            in_progress = self._attr_in_progress

        installed_version = self.installed_version
        latest_version = self.latest_version

        return {
            ATTR_INSTALLED_VERSION: installed_version,
            ATTR_IN_PROGRESS: in_progress,
            ATTR_LATEST_VERSION: latest_version,
            ATTR_RELEASE_SUMMARY: release_summary,
            ATTR_RELEASE_URL: self.release_url,
        }

    @final
    async def async_install_with_progress(
        self, version: str | None, backup: bool
    ) -> None:
        """Install update and handle progress if needed.

        Handles setting the in_progress state in case the entity doesn't
        support it natively.
        """
        if UpdateEntityFeature.PROGRESS not in self.supported_features:
            self._attr_in_progress = True
            self.maybe_emit_state_changed_event()

        try:
            await self.async_install(version, backup)
        finally:
            # No matter what happens, we always stop progress in the end
            self._attr_in_progress = False
            self.maybe_emit_state_changed_event()

    def _get_cluster_version(self) -> str | None:
        """Synchronize current file version with the cluster."""

        device = self._ota_cluster_handler._endpoint.device  # pylint: disable=protected-access

        if self._ota_cluster_handler.current_file_version is not None:
            return f"0x{self._ota_cluster_handler.current_file_version:08x}"

        if device.sw_version is not None:
            return device.sw_version

        return None

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle attribute updates on the OTA cluster."""
        if event.attribute_id == Ota.AttributeDefs.current_file_version.id:
            self._attr_installed_version = f"0x{event.attribute_value:08x}"
            self.maybe_emit_state_changed_event()

    @callback
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
            self._attr_in_progress = False
            self._attr_latest_version = self._attr_installed_version
            self.maybe_emit_state_changed_event()

        # If the update finished but was not successful, we should also throw an error
        if result != Status.SUCCESS:
            raise ZHAException(f"Update was not successful: {result}")

        # Clear the state
        self._latest_firmware = None
        self._attr_in_progress = False
        self.maybe_emit_state_changed_event()

    async def on_remove(self) -> None:
        """Call when entity will be removed."""
        await super().on_remove()
        self._attr_in_progress = False

    async def async_update(self) -> None:
        """Update the entity."""
        # await CoordinatorEntity.async_update(self)
        await super().async_update()


@functools.lru_cache(maxsize=256)
def _version_is_newer(latest_version: str, installed_version: str) -> bool:
    """Return True if version is newer."""
    return AwesomeVersion(latest_version) > installed_version
