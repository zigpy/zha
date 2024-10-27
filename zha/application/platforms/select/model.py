"""Models for the select platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo, GenericState


class SelectEntityInfo(BasePlatformEntityInfo):
    """Select entity model."""

    class_name: Literal[
        "DefaultToneSelectEntity",
        "DefaultSirenLevelSelectEntity",
        "DefaultStrobeLevelSelectEntity",
        "DefaultStrobeSelectEntity",
        "StartupOnOffSelectEntity",
        "HueV1MotionSensitivity",
        "AqaraMonitoringMode",
        "AqaraApproachDistance",
        "AqaraMotionSensitivity",
        "AqaraMagnetAC01DetectionDistance",
        "HueV2MotionSensitivity",
        "ZCLEnumSelectEntity",
    ]
    enum: str
    options: list[str]
    state: GenericState


class EnumSelectInfo(BasePlatformEntityInfo):
    """Enum select entity info."""

    enum: str
    options: list[str]
