"""Models for the climate platform."""

from __future__ import annotations

from typing import Literal

from zha.application.platforms.climate.const import ClimateEntityFeature, HVACMode
from zha.application.platforms.model import BasePlatformEntityInfo
from zha.model import BaseModel


class ThermostatState(BaseModel):
    """Thermostat state model."""

    class_name: Literal[
        "Thermostat",
        "SinopeTechnologiesThermostat",
        "ZenWithinThermostat",
        "MoesThermostat",
        "BecaThermostat",
        "ZONNSMARTThermostat",
    ]
    current_temperature: float | None = None
    target_temperature: float | None = None
    target_temperature_low: float | None = None
    target_temperature_high: float | None = None
    hvac_action: str | None = None
    hvac_mode: str | None = None
    preset_mode: str | None = None
    fan_mode: str | None = None


class ThermostatEntityInfo(BasePlatformEntityInfo):
    """Thermostat entity model."""

    class_name: Literal[
        "Thermostat",
        "SinopeTechnologiesThermostat",
        "ZenWithinThermostat",
        "MoesThermostat",
        "BecaThermostat",
        "ZONNSMARTThermostat",
    ]
    state: ThermostatState
    supported_features: ClimateEntityFeature
    hvac_modes: list[HVACMode]
    fan_modes: list[str] | None = None
    preset_modes: list[str] | None = None
    max_temp: float
    min_temp: float
