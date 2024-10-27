"""Models for the light platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.light.const import ColorMode, LightEntityFeature
from zha.application.platforms.model import BasePlatformEntityInfo
from zha.model import BaseModel


class LightState(BaseModel):
    """Light state model."""

    class_name: Literal[
        "Light",
        "HueLight",
        "ForceOnLight",
        "LightGroup",
        "MinTransitionLight",
    ]
    on: bool
    brightness: int | None = None
    xy_color: tuple[float, float] | None = None
    color_temp: int | None = None
    effect: str
    off_brightness: int | None = None
    color_mode: ColorMode | None = None
    off_with_transition: bool = False


class LightEntityInfo(BasePlatformEntityInfo):
    """Light model."""

    class_name: Literal[
        "Light", "HueLight", "ForceOnLight", "MinTransitionLight", "LightGroup"
    ]
    supported_features: LightEntityFeature
    min_mireds: int
    max_mireds: int
    effect_list: list[str] | None = None
    supported_color_modes: set[ColorMode]
    state: LightState
