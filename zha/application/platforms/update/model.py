"""Models for the update platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo
from zha.application.platforms.update.const import UpdateEntityFeature
from zha.model import BaseModel


class FirmwareUpdateState(BaseModel):
    """Firmware update state model."""

    class_name: Literal["FirmwareUpdateEntity"]
    available: bool
    installed_version: str | None = None
    in_progress: bool | None = None
    progress: int | None = None
    latest_version: str | None = None
    release_summary: str | None = None
    release_notes: str | None = None
    release_url: str | None = None


class FirmwareUpdateEntityInfo(BasePlatformEntityInfo):
    """Firmware update entity model."""

    class_name: Literal["FirmwareUpdateEntity"]
    state: FirmwareUpdateState
    supported_features: UpdateEntityFeature
