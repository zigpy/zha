"""Constants copied from legacy zha-quirks device handlers. This will be removed."""

from __future__ import annotations

from typing import Final

from zigpy import types as t

AQARA_OPPLE_CLUSTER: Final[int] = 0xFCC0


class MagnetAC01OppleCluster:
    """Mirrors `zhaquirks.xiaomi.aqara.magnet_ac01.OppleCluster`."""

    cluster_id = AQARA_OPPLE_CLUSTER

    class DetectionDistance(t.enum8):
        """Detection distance."""

        TenMillimeters = 0x01
        TwentyMillimeters = 0x02
        ThirtyMillimeters = 0x03


class T2RelayOppleCluster:
    """Mirrors `zhaquirks.xiaomi.aqara.switch_acn047.OppleCluster`."""

    cluster_id = AQARA_OPPLE_CLUSTER

    class SwitchType(t.enum8):
        """Switch type."""

        Toggle = 0x01
        Momentary = 0x02
        NoSwitch = 0x03

    class StartupOnOff(t.enum8):
        """Startup mode."""

        On = 0x00
        Previous = 0x01
        Off = 0x02
        Toggle = 0x03

    class DecoupledMode(t.enum8):
        """Decoupled mode."""

        Decoupled = 0x00
        ControlRelay = 0x01

    class SwitchMode(t.enum8):
        """Switch Mode."""

        Power = 0x00
        Pulse = 0x01
        Dry = 0x03


class DanfossViewingDirectionEnum(t.enum8):
    """Default or Inverted screen orientation."""

    Default = 0x00
    Inverted = 0x01


class DanfossAdaptationRunControlEnum(t.enum8):
    """Initiate or Cancel adaptation run."""

    Nothing = 0x00
    Initiate = 0x01
    Cancel = 0x02


class DanfossExerciseDayOfTheWeekEnum(t.enum8):
    """Day of the week."""

    Sunday = 0
    Monday = 1
    Tuesday = 2
    Wednesday = 3
    Thursday = 4
    Friday = 5
    Saturday = 6
    Undefined = 7


class DanfossOpenWindowDetectionEnum(t.enum8):
    """Danfoss open window detection judgments."""

    Quarantine = 0x00
    Closed = 0x01
    Maybe = 0x02
    Open = 0x03
    External = 0x04


class DanfossSoftwareErrorCodeBitmap(t.bitmap16):
    """Danfoss software error code bitmap."""

    Top_pcb_sensor_error = 0x0001
    Side_pcb_sensor_error = 0x0002
    Non_volatile_memory_error = 0x0004
    Unknown_hw_error = 0x0008
    Motor_error = 0x0020
    Invalid_internal_communication = 0x0080
    Invalid_clock_information = 0x0200
    Radio_communication_error = 0x0800
    Encoder_jammed = 0x1000
    Low_battery = 0x2000
    Critical_low_battery = 0x4000


class DanfossAdaptationRunStatusBitmap(t.bitmap8):
    """Danfoss Adaptation run status bitmap."""

    In_progress = 0x0001
    Valve_characteristic_found = 0x0002
    Valve_characteristic_lost = 0x0004
