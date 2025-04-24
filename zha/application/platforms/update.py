"""Representation of ZHA updates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntFlag, StrEnum
import functools
import itertools
import logging
from typing import TYPE_CHECKING, Any, Final, final

from zigpy.ota import OtaImagesResult, OtaImageWithMetadata
from zigpy.zcl.clusters.general import Ota, QueryNextImageCommand
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import BaseEntityInfo, EntityCategory, PlatformEntity
from zha.application.registries import PLATFORM_ENTITIES
from zha.exceptions import ZHAException
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_OTA,
    CLUSTER_HANDLER_OTA_SERVER,
)
from zha.zigbee.endpoint import Endpoint

if TYPE_CHECKING:
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


ATTR_BACKUP: Final = "backup"
ATTR_INSTALLED_VERSION: Final = "installed_version"
ATTR_IN_PROGRESS: Final = "in_progress"
ATTR_UPDATE_PERCENTAGE: Final = "update_percentage"
ATTR_LATEST_VERSION: Final = "latest_version"
ATTR_RELEASE_SUMMARY: Final = "release_summary"
ATTR_RELEASE_NOTES: Final = "release_notes"
ATTR_RELEASE_URL: Final = "release_url"
ATTR_VERSION: Final = "version"


@dataclass(frozen=True, kw_only=True)
class UpdateEntityInfo(BaseEntityInfo):
    """Update entity info."""

    supported_features: UpdateEntityFeature
    device_class: UpdateDeviceClass
    entity_category: EntityCategory


class BaseFirmwareUpdateEntity(PlatformEntity):
    """Base representation of a ZHA firmware update entity."""

    PLATFORM = Platform.UPDATE

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
    _attr_update_percentage: float | None = None
    _attr_latest_version: str | None = None
    _attr_release_summary: str | None = None
    _attr_release_notes: str | None = None
    _attr_release_url: str | None = None

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
    def update_percentage(self) -> float | None:
        """Update installation progress.

        Returns a number indicating the progress from 0 to 100%. If an update's progress
        is indeterminate, this will return None.
        """
        return self._attr_update_percentage

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
    def release_notes(self) -> str | None:
        """Full release notes of the latest version available."""
        return self._attr_release_notes

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
            ATTR_UPDATE_PERCENTAGE: self.update_percentage,
            ATTR_LATEST_VERSION: self.latest_version,
            ATTR_RELEASE_SUMMARY: release_summary,
            ATTR_RELEASE_NOTES: self.release_notes,
            ATTR_RELEASE_URL: self.release_url,
        }

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

    def device_ota_image_query_result(
        self,
        images_result: OtaImagesResult,
        query_next_img_command: QueryNextImageCommand,
    ) -> None:
        """Handle ota update available signal from Zigpy."""

        current_version = query_next_img_command.current_file_version
        self._attr_installed_version = f"0x{current_version:08x}"

        self._compatible_images = images_result
        self._attr_latest_version = None
        self._attr_release_summary = None
        self._attr_release_notes = None

        latest_firmware: OtaImageWithMetadata | None = None

        if images_result.upgrades:
            # If there are upgrades, cache the image and indicate that we should upgrade
            latest_firmware = images_result.upgrades[0]
            self._attr_latest_version = f"0x{latest_firmware.version:08x}"
            self._attr_release_summary = latest_firmware.metadata.changelog or None
            self._attr_release_notes = latest_firmware.metadata.release_notes or None
        elif images_result.downgrades:
            # If not, note the version of the most recent firmware
            latest_firmware = None
            self._attr_latest_version = f"0x{images_result.downgrades[0].version:08x}"

        self.maybe_emit_state_changed_event()

    def _update_progress(self, current: int, total: int, progress: float) -> None:
        """Update install progress on event."""
        # If we are not supposed to be updating, do nothing
        if not self._attr_in_progress:
            return

        self._attr_update_percentage = progress
        self.maybe_emit_state_changed_event()

    async def async_install(self, version: str | None) -> None:
        """Install an update."""

        if version is None:
            if not self._compatible_images.upgrades:
                raise ZHAException("No firmware updates are available")

            firmware = self._compatible_images.upgrades[0]
        else:
            version = int(version, 16)

            for firmware in itertools.chain(
                self._compatible_images.upgrades,
                self._compatible_images.downgrades,
            ):
                if firmware.version == version:
                    break
            else:
                raise ZHAException(f"Version {version!r} is not available")

        self._attr_in_progress = True
        self._attr_update_percentage = None
        self.maybe_emit_state_changed_event()

        try:
            result = await self.device.device.update_firmware(
                image=firmware,
                progress_callback=self._update_progress,
            )
        except Exception as ex:
            self._attr_in_progress = False
            self.maybe_emit_state_changed_event()
            raise ZHAException(f"Update was not successful: {ex}") from ex

        # If the update finished but was not successful, we should also throw an error
        if result != Status.SUCCESS:
            self._attr_in_progress = False
            self.maybe_emit_state_changed_event()
            raise ZHAException(f"Update was not successful: {result}")

        # Clear the state
        self._attr_in_progress = False
        self.maybe_emit_state_changed_event()

    def on_add(self) -> None:
        """Call when entity is added."""
        super().on_add()

        self.device.device.add_listener(self)
        self._on_remove_callbacks.append(
            self._ota_cluster_handler.on_event(
                CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
                self.handle_cluster_handler_attribute_updated,
            )
        )
        self._on_remove_callbacks.append(
            lambda: self.device.device.remove_listener(self)
        )

    async def on_remove(self) -> None:
        """Call when entity will be removed."""
        self._attr_in_progress = False
        await super().on_remove()


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_OTA)
class FirmwareUpdateEntity(BaseFirmwareUpdateEntity):
    """Representation of a ZHA firmware update entity."""

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the ZHA update entity."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)

        self._ota_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_OTA
        ]
        self._attr_installed_version: str | None = self._get_cluster_version()
        self._attr_latest_version = self._attr_installed_version
        self._compatible_images: OtaImagesResult = OtaImagesResult(
            upgrades=(), downgrades=()
        )


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_OTA_SERVER)
class FirmwareUpdateServerEntity(BaseFirmwareUpdateEntity):
    """Representation of a ZHA firmware update entity."""

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the ZHA update entity."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)

        # Some devices make it a server cluster, not a client cluster...
        self._ota_cluster_handler: ClusterHandler = self.cluster_handlers[
            CLUSTER_HANDLER_OTA_SERVER
        ]
        self._attr_installed_version: str | None = self._get_cluster_version()
        self._attr_latest_version = self._attr_installed_version
        self._compatible_images: OtaImagesResult = OtaImagesResult(
            upgrades=(), downgrades=()
        )
