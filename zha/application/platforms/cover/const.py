"""Constants for the cover platform."""

from enum import IntFlag, StrEnum
from typing import Final

from zigpy.zcl.clusters.closures import WindowCovering as WindowCoveringCluster

ATTR_CURRENT_POSITION: Final[str] = "current_position"
ATTR_CURRENT_TILT_POSITION: Final[str] = "current_tilt_position"
ATTR_POSITION: Final[str] = "position"
ATTR_TILT_POSITION: Final[str] = "tilt_position"

POSITION_CLOSED: Final[int] = 0
POSITION_OPEN: Final[int] = 100


class CoverState(StrEnum):
    """State of Cover entities."""

    CLOSED = "closed"
    CLOSING = "closing"
    OPEN = "open"
    OPENING = "opening"


class CoverDeviceClass(StrEnum):
    """Device class for cover."""

    # Refer to the cover dev docs for device class descriptions
    AWNING = "awning"
    BLIND = "blind"
    CURTAIN = "curtain"
    DAMPER = "damper"
    DOOR = "door"
    GARAGE = "garage"
    GATE = "gate"
    SHADE = "shade"
    SHUTTER = "shutter"
    WINDOW = "window"


class CoverEntityFeature(IntFlag):
    """Supported features of the cover entity."""

    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8
    OPEN_TILT = 16
    CLOSE_TILT = 32
    STOP_TILT = 64
    SET_TILT_POSITION = 128


WCAttrs = WindowCoveringCluster.AttributeDefs
WCT = WindowCoveringCluster.WindowCoveringType
WCCS = WindowCoveringCluster.ConfigStatus

ZCL_TO_COVER_DEVICE_CLASS = {
    WCT.Awning: CoverDeviceClass.AWNING,
    WCT.Drapery: CoverDeviceClass.CURTAIN,
    WCT.Projector_screen: CoverDeviceClass.SHADE,
    WCT.Rollershade: CoverDeviceClass.SHADE,
    WCT.Rollershade_two_motors: CoverDeviceClass.SHADE,
    WCT.Rollershade_exterior: CoverDeviceClass.SHADE,
    WCT.Rollershade_exterior_two_motors: CoverDeviceClass.SHADE,
    WCT.Shutter: CoverDeviceClass.SHUTTER,
    WCT.Tilt_blind_tilt_only: CoverDeviceClass.BLIND,
    WCT.Tilt_blind_tilt_and_lift: CoverDeviceClass.BLIND,
}
