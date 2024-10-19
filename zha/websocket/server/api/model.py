"""Models for the websocket API."""

from typing import Literal

from zha.model import BaseModel
from zha.websocket.const import APICommands


class WebSocketCommand(BaseModel):
    """Command for the websocket API."""

    message_id: int = 1
    command: Literal[
        APICommands.STOP_SERVER,
        APICommands.CLIENT_LISTEN_RAW_ZCL,
        APICommands.CLIENT_DISCONNECT,
        APICommands.CLIENT_LISTEN,
        APICommands.BUTTON_PRESS,
        APICommands.PLATFORM_ENTITY_REFRESH_STATE,
        APICommands.ALARM_CONTROL_PANEL_DISARM,
        APICommands.ALARM_CONTROL_PANEL_ARM_HOME,
        APICommands.ALARM_CONTROL_PANEL_ARM_AWAY,
        APICommands.ALARM_CONTROL_PANEL_ARM_NIGHT,
        APICommands.ALARM_CONTROL_PANEL_TRIGGER,
        APICommands.START_NETWORK,
        APICommands.STOP_NETWORK,
        APICommands.UPDATE_NETWORK_TOPOLOGY,
        APICommands.RECONFIGURE_DEVICE,
        APICommands.GET_DEVICES,
        APICommands.GET_GROUPS,
        APICommands.PERMIT_JOINING,
        APICommands.ADD_GROUP_MEMBERS,
        APICommands.REMOVE_GROUP_MEMBERS,
        APICommands.CREATE_GROUP,
        APICommands.REMOVE_GROUPS,
        APICommands.REMOVE_DEVICE,
        APICommands.READ_CLUSTER_ATTRIBUTES,
        APICommands.WRITE_CLUSTER_ATTRIBUTE,
        APICommands.SIREN_TURN_ON,
        APICommands.SIREN_TURN_OFF,
        APICommands.SELECT_SELECT_OPTION,
        APICommands.NUMBER_SET_VALUE,
        APICommands.LOCK_CLEAR_USER_CODE,
        APICommands.LOCK_SET_USER_CODE,
        APICommands.LOCK_ENAABLE_USER_CODE,
        APICommands.LOCK_DISABLE_USER_CODE,
        APICommands.LOCK_LOCK,
        APICommands.LOCK_UNLOCK,
        APICommands.LIGHT_TURN_OFF,
        APICommands.LIGHT_TURN_ON,
        APICommands.FAN_SET_PERCENTAGE,
        APICommands.FAN_SET_PRESET_MODE,
        APICommands.FAN_TURN_ON,
        APICommands.FAN_TURN_OFF,
        APICommands.COVER_STOP,
        APICommands.COVER_SET_POSITION,
        APICommands.COVER_OPEN,
        APICommands.COVER_CLOSE,
        APICommands.CLIMATE_SET_TEMPERATURE,
        APICommands.CLIMATE_SET_HVAC_MODE,
        APICommands.CLIMATE_SET_FAN_MODE,
        APICommands.CLIMATE_SET_PRESET_MODE,
        APICommands.SWITCH_TURN_ON,
        APICommands.SWITCH_TURN_OFF,
    ]
