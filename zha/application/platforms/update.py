"""Representation of ZHA updates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag, StrEnum
import functools
import logging
from typing import TYPE_CHECKING, Any, Final, final

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
ATTR_PROGRESS: Final = "progress"
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
    _attr_in_progress: bool = False
    _attr_progress: int = 0
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
        )

    @property
    def state(self):
        """Get the state for the entity."""
        response = super().state
        response.update(self.state_attributes)
        return response

    @property
    def installed_version(self) -> str | None:
        """Version installed and in use."""
        return self._attr_installed_version

    @property
    def in_progress(self) -> bool | None:
        """Update installation progress.

        Needs UpdateEntityFeature.PROGRESS flag to be set for it to be used.

        Returns a boolean (True if in progress, False if not).
        """
        return self._attr_in_progress

    @property
    def progress(self) -> int | None:
        """Update installation progress.

        Needs UpdateEntityFeature.PROGRESS flag to be set for it to be used.

        Returns an integer indicating the progress from 0 to 100%.
        """
        return self._attr_progress

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

    @final
    @property
    def state_attributes(self) -> dict[str, Any] | None:
        """Return state attributes."""
        if (release_summary := self.release_summary) is not None:
            release_summary = release_summary[:255]

        return {
            ATTR_INSTALLED_VERSION: self.installed_version,
            ATTR_IN_PROGRESS: self.in_progress,
            ATTR_PROGRESS: self.progress,
            ATTR_LATEST_VERSION: self.latest_version,
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
        try:
            await self.async_install(version, backup)
        finally:
            # No matter what happens, we always stop progress in the end
            self._attr_in_progress = False
            self.maybe_emit_state_changed_event()

    def _get_cluster_version(self) -> str | None:
        """Synchronize current file version with the cluster."""

        if self._ota_cluster_handler.current_file_version is not None:
            return f"0x{self._ota_cluster_handler.current_file_version:08x}"

        return None

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,
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
        if not self._attr_in_progress:
            return

        self._attr_progress = int(progress)
        self.maybe_emit_state_changed_event()

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install an update."""
        assert self._latest_firmware is not None

        self._attr_in_progress = True
        self._attr_progress = 0
        self.maybe_emit_state_changed_event()

        try:
            result = await self.device.device.update_firmware(
                image=self._latest_firmware,
                progress_callback=self._update_progress,
            )
        except Exception as ex:
            self._attr_in_progress = False
            self.maybe_emit_state_changed_event()
            raise ZHAException(f"Update was not successful: {ex}") from ex

        # If we tried to install firmware that is no longer compatible with the device,
        # bail out
        if result == Status.NO_IMAGE_AVAILABLE:
            self._attr_in_progress = False
            self._attr_latest_version = self._attr_installed_version
            self.maybe_emit_state_changed_event()

        # If the update finished but was not successful, we should also throw an error
        if result != Status.SUCCESS:
            self._attr_in_progress = False
            self.maybe_emit_state_changed_event()
            raise ZHAException(f"Update was not successful: {result}")

        # Clear the state
        self._latest_firmware = None
        self._attr_in_progress = False
        self.maybe_emit_state_changed_event()

    async def on_remove(self) -> None:
        """Call when entity will be removed."""
        await super().on_remove()
        self._attr_in_progress = False
