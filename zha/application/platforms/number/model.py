"""Models for the number platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo, GenericState


class NumberEntityInfo(BasePlatformEntityInfo):
    """Number entity model."""

    class_name: Literal[
        "Number",
        "MaxHeatSetpointLimit",
        "MinHeatSetpointLimit",
        "StartUpCurrentLevelConfigurationEntity",
        "StartUpColorTemperatureConfigurationEntity",
        "OnOffTransitionTimeConfigurationEntity",
        "OnLevelConfigurationEntity",
        "NumberConfigurationEntity",
        "OnTransitionTimeConfigurationEntity",
        "OffTransitionTimeConfigurationEntity",
        "DefaultMoveRateConfigurationEntity",
        "FilterLifeTime",
        "AqaraMotionDetectionInterval",
        "TiRouterTransmitPower",
    ]
    engineering_units: int | None = (
        None  # TODO: how should we represent this when it is None?
    )
    application_type: int | None = (
        None  # TODO: how should we represent this when it is None?
    )
    step: float | None = None  # TODO: how should we represent this when it is None?
    min_value: float
    max_value: float
    state: GenericState


class NumberConfigurationEntityInfo(BasePlatformEntityInfo):
    """Number configuration entity info."""

    min_value: float | None
    max_value: float | None
    step: float | None
    multiplier: float | None
    device_class: str | None
