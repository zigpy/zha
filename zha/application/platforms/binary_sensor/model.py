"""Models for the binary sensor platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo, BooleanState


class BinarySensorEntityInfo(BasePlatformEntityInfo):
    """Binary sensor model."""

    class_name: Literal[
        "Accelerometer",
        "Occupancy",
        "Opening",
        "BinaryInput",
        "Motion",
        "IASZone",
        "FrostLock",
        "BinarySensor",
        "ReplaceFilter",
        "AqaraLinkageAlarmState",
        "HueOccupancy",
        "AqaraE1CurtainMotorOpenedByHandBinarySensor",
        "DanfossHeatRequired",
        "DanfossMountingModeActive",
        "DanfossPreheatStatus",
    ]
    attribute_name: str | None = None
    state: BooleanState
