"""Constants for the alarm control panel platform."""

from enum import IntFlag, StrEnum

from zigpy.zcl.clusters.security import IasAce


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


class CodeFormat(StrEnum):
    """Code formats for the Alarm Control Panel."""

    TEXT = "text"
    NUMBER = "number"


class AlarmControlPanelEntityFeature(IntFlag):
    """Supported features of the alarm control panel entity."""

    ARM_HOME = 1
    ARM_AWAY = 2
    ARM_NIGHT = 4
    TRIGGER = 8
    ARM_CUSTOM_BYPASS = 16
    ARM_VACATION = 32
