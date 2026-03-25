"""Constants for the Number platform."""

from zigpy.quirks.v2.homeassistant.number import NumberDeviceClass, NumberMode

# Re-exported from zigpy for use throughout ZHA
__all__ = ["NumberDeviceClass", "NumberMode"]

ICONS = {
    0: "mdi:temperature-celsius",
    1: "mdi:water-percent",
    2: "mdi:gauge",
    3: "mdi:speedometer",
    4: "mdi:percent",
    5: "mdi:air-filter",
    6: "mdi:fan",
    7: "mdi:flash",
    8: "mdi:current-ac",
    9: "mdi:flash",
    10: "mdi:flash",
    11: "mdi:flash",
    12: "mdi:counter",
    13: "mdi:thermometer-lines",
    14: "mdi:timer",
    15: "mdi:palette",
    16: "mdi:brightness-percent",
}
