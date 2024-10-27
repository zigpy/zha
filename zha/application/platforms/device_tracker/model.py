"""Models for the device tracker platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo
from zha.model import BaseModel


class DeviceTrackerState(BaseModel):
    """Device tracker state model."""

    class_name: Literal["DeviceScannerEntity"] = "DeviceScannerEntity"
    connected: bool
    battery_level: float | None = None


class DeviceTrackerEntityInfo(BasePlatformEntityInfo):
    """Device tracker entity model."""

    class_name: Literal["DeviceScannerEntity"]
    state: DeviceTrackerState
