"""Constants for the binary_sensor platform."""

from zigpy.quirks.v2.homeassistant.binary_sensor import BinarySensorDeviceClass
from zigpy.zcl.clusters.security import IasZone

# Re-exported from zigpy for use throughout ZHA
__all__ = ["BinarySensorDeviceClass"]


# Zigbee Cluster Library Zone Type to Home Assistant device class
IAS_ZONE_CLASS_MAPPING = {
    IasZone.ZoneType.Motion_Sensor: BinarySensorDeviceClass.MOTION,
    IasZone.ZoneType.Contact_Switch: BinarySensorDeviceClass.OPENING,
    IasZone.ZoneType.Fire_Sensor: BinarySensorDeviceClass.SMOKE,
    IasZone.ZoneType.Water_Sensor: BinarySensorDeviceClass.MOISTURE,
    IasZone.ZoneType.Carbon_Monoxide_Sensor: BinarySensorDeviceClass.CO,
    IasZone.ZoneType.Vibration_Movement_Sensor: BinarySensorDeviceClass.VIBRATION,
}
