"""Models for the switch platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.model import BasePlatformEntityInfo
from zha.model import BaseModel


class SwitchState(BaseModel):
    """Switch state model."""

    class_name: Literal[
        "Switch",
        "SwitchGroup",
        "WindowCoveringInversionSwitch",
        "ChildLock",
        "DisableLed",
        "AqaraHeartbeatIndicator",
        "AqaraLinkageAlarm",
        "AqaraBuzzerManualMute",
        "AqaraBuzzerManualAlarm",
        "HueMotionTriggerIndicatorSwitch",
        "AqaraE1CurtainMotorHooksLockedSwitch",
        "P1MotionTriggerIndicatorSwitch",
        "ConfigurableAttributeSwitch",
        "OnOffWindowDetectionFunctionConfigurationEntity",
    ]
    state: bool


class SwitchEntityInfo(BasePlatformEntityInfo):
    """Switch entity model."""

    class_name: Literal[
        "Switch",
        "WindowCoveringInversionSwitch",
        "ChildLock",
        "DisableLed",
        "AqaraHeartbeatIndicator",
        "AqaraLinkageAlarm",
        "AqaraBuzzerManualMute",
        "AqaraBuzzerManualAlarm",
        "HueMotionTriggerIndicatorSwitch",
        "AqaraE1CurtainMotorHooksLockedSwitch",
        "P1MotionTriggerIndicatorSwitch",
        "ConfigurableAttributeSwitch",
        "OnOffWindowDetectionFunctionConfigurationEntity",
        "SwitchGroup",
    ]
    state: SwitchState


class ConfigurableAttributeSwitchInfo(BasePlatformEntityInfo):
    """Switch configuration entity info."""

    attribute_name: str
    invert_attribute_name: str | None = None
    force_inverted: bool
    off_value: int
    on_value: int
