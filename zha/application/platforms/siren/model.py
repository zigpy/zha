"""Models for the siren platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo, BooleanState
from zha.application.platforms.siren.const import SirenEntityFeature


class SirenEntityInfo(BasePlatformEntityInfo):
    """Siren entity model."""

    class_name: Literal["Siren"]
    available_tones: dict[int, str]
    supported_features: SirenEntityFeature
    state: BooleanState
