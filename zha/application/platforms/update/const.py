"""Constants for the ZHA update platform."""

from __future__ import annotations

from enum import IntFlag, StrEnum
from typing import Final

SERVICE_INSTALL: Final = "install"

ATTR_BACKUP: Final = "backup"
ATTR_INSTALLED_VERSION: Final = "installed_version"
ATTR_IN_PROGRESS: Final = "in_progress"
ATTR_PROGRESS: Final = "progress"
ATTR_LATEST_VERSION: Final = "latest_version"
ATTR_RELEASE_SUMMARY: Final = "release_summary"
ATTR_RELEASE_NOTES: Final = "release_notes"
ATTR_RELEASE_URL: Final = "release_url"
ATTR_VERSION: Final = "version"


class UpdateEntityFeature(IntFlag):
    """Supported features of the update entity."""

    INSTALL = 1
    SPECIFIC_VERSION = 2
    PROGRESS = 4
    BACKUP = 8
    RELEASE_NOTES = 16


class UpdateDeviceClass(StrEnum):
    """Device class for update."""

    FIRMWARE = "firmware"
