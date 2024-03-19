"""Constants for the alarm control panel platform."""

from enum import StrEnum
from typing import Final

from zigpy.zcl.clusters.security import IasAce

SUPPORT_ALARM_ARM_HOME: Final[int] = 1
SUPPORT_ALARM_ARM_AWAY: Final[int] = 2
SUPPORT_ALARM_ARM_NIGHT: Final[int] = 4
SUPPORT_ALARM_TRIGGER: Final[int] = 8
SUPPORT_ALARM_ARM_CUSTOM_BYPASS: Final[int] = 16
SUPPORT_ALARM_ARM_VACATION: Final[int] = 32


class AlarmState(StrEnum):
    """Alarm state."""

    DISARMED = "disarmed"
    ARMED_HOME = "armed_home"
    ARMED_AWAY = "armed_away"
    ARMED_NIGHT = "armed_night"
    ARMED_VACATION = "armed_vacation"
    ARMED_CUSTOM_BYPASS = "armed_custom_bypass"
    PENDING = "pending"
    ARMING = "arming"
    DISARMING = "disarming"
    TRIGGERED = "triggered"
    UNKNOWN = "unknown"


IAS_ACE_STATE_MAP = {
    IasAce.PanelStatus.Panel_Disarmed: AlarmState.DISARMED,
    IasAce.PanelStatus.Armed_Stay: AlarmState.ARMED_HOME,
    IasAce.PanelStatus.Armed_Night: AlarmState.ARMED_NIGHT,
    IasAce.PanelStatus.Armed_Away: AlarmState.ARMED_AWAY,
    IasAce.PanelStatus.In_Alarm: AlarmState.TRIGGERED,
}
