"""Models for the lock platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo
from zha.model import BaseModel


class LockState(BaseModel):
    """Lock state model."""

    class_name: Literal["Lock", "DoorLock"] = "Lock"
    is_locked: bool


class LockEntityInfo(BasePlatformEntityInfo):
    """Lock entity model."""

    class_name: Literal["Lock", "DoorLock"]
    state: LockState
