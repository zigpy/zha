"""Constants for the binary_sensor platform."""

from zigpy.zcl.clusters.security import IasZone

from zha.application.platforms.binary_sensor.device_class import BinarySensorDeviceClass

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
