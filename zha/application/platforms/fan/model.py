"""Models for the fan platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.fan.const import FanEntityFeature
from zha.application.platforms.model import BasePlatformEntityInfo
from zha.model import BaseModel


class FanState(BaseModel):
    """Fan state model."""

    class_name: Literal["Fan", "FanGroup", "IkeaFan", "KofFan"]
    preset_mode: str | None = (
        None  # TODO: how should we represent these when they are None?
    )
    percentage: int | None = (
        None  # TODO: how should we represent these when they are None?
    )
    is_on: bool
    speed: str | None = None


class FanEntityInfo(BasePlatformEntityInfo):
    """Fan model."""

    class_name: Literal["Fan", "IkeaFan", "KofFan", "FanGroup"]
    preset_modes: list[str]
    supported_features: FanEntityFeature
    speed_count: int
    speed_list: list[str]
    percentage_step: float | None = None
    state: FanState
