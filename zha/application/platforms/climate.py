"""Climate on Zigbee Home Automation."""  # pylint: disable=too-many-lines

from __future__ import annotations

import datetime as dt
from enum import IntFlag, StrEnum
import functools
from typing import TYPE_CHECKING, Any, Final

from zigpy.zcl.clusters.hvac import FanMode, RunningState, SystemMode

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.registries import PLATFORM_ENTITIES
from zha.decorators import periodic
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_EVENT,
    CLUSTER_HANDLER_FAN,
    CLUSTER_HANDLER_THERMOSTAT,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import ZHADevice
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.CLIMATE)
MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.CLIMATE)


ATTR_SYS_MODE: Final[str] = "system_mode"
ATTR_FAN_MODE: Final[str] = "fan_mode"
ATTR_RUNNING_MODE: Final[str] = "running_mode"
ATTR_SETPT_CHANGE_SRC: Final[str] = "setpoint_change_source"
ATTR_SETPT_CHANGE_AMT: Final[str] = "setpoint_change_amount"
ATTR_OCCUPANCY: Final[str] = "occupancy"
ATTR_PI_COOLING_DEMAND: Final[str] = "pi_cooling_demand"
ATTR_PI_HEATING_DEMAND: Final[str] = "pi_heating_demand"
ATTR_OCCP_COOL_SETPT: Final[str] = "occupied_cooling_setpoint"
ATTR_OCCP_HEAT_SETPT: Final[str] = "occupied_heating_setpoint"
ATTR_UNOCCP_HEAT_SETPT: Final[str] = "unoccupied_heating_setpoint"
ATTR_UNOCCP_COOL_SETPT: Final[str] = "unoccupied_cooling_setpoint"
ATTR_HVAC_MODE: Final[str] = "hvac_mode"
ATTR_TARGET_TEMP_HIGH: Final[str] = "target_temp_high"
ATTR_TARGET_TEMP_LOW: Final[str] = "target_temp_low"

SUPPORT_TARGET_TEMPERATURE: Final[int] = 1
SUPPORT_TARGET_TEMPERATURE_RANGE: Final[int] = 2
SUPPORT_TARGET_HUMIDITY: Final[int] = 4
SUPPORT_FAN_MODE: Final[int] = 8
SUPPORT_PRESET_MODE: Final[int] = 16
SUPPORT_SWING_MODE: Final[int] = 32
SUPPORT_AUX_HEAT: Final[int] = 64

PRECISION_TENTHS: Final[float] = 0.1
# Temperature attribute
ATTR_TEMPERATURE: Final[str] = "temperature"
TEMP_CELSIUS: Final[str] = "°C"

# Possible fan state
FAN_ON = "on"
FAN_OFF = "off"
FAN_AUTO = "auto"
FAN_LOW = "low"
FAN_MEDIUM = "medium"
FAN_HIGH = "high"
FAN_TOP = "top"
FAN_MIDDLE = "middle"
FAN_FOCUS = "focus"
FAN_DIFFUSE = "diffuse"

# Possible swing state
SWING_ON = "on"
SWING_OFF = "off"
SWING_BOTH = "both"
SWING_VERTICAL = "vertical"
SWING_HORIZONTAL = "horizontal"


class ClimateEntityFeature(IntFlag):
    """Supported features of the climate entity."""

    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2
    TARGET_HUMIDITY = 4
    FAN_MODE = 8
    PRESET_MODE = 16
    SWING_MODE = 32
    AUX_HEAT = 64
    TURN_OFF = 128
    TURN_ON = 256


class UnitOfTemperature(StrEnum):
    """Temperature units."""

    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class HVACMode(StrEnum):
    """HVAC mode."""

    OFF = "off"
    # Heating
    HEAT = "heat"
    # Cooling
    COOL = "cool"
    # The device supports heating/cooling to a range
    HEAT_COOL = "heat_cool"
    # The temperature is set based on a schedule, learned behavior, AI or some
    # other related mechanism. User is not able to adjust the temperature
    AUTO = "auto"
    # Device is in Dry/Humidity mode
    DRY = "dry"
    # Only the fan is on, not fan and another mode like cool
    FAN_ONLY = "fan_only"


class Preset(StrEnum):
    """Preset mode."""

    # No preset is active
    NONE = "none"
    # Device is running an energy-saving mode
    ECO = "eco"
    # Device is in away mode
    AWAY = "away"
    # Device turn all valve full up
    BOOST = "boost"
    # Device is in comfort mode
    COMFORT = "comfort"
    # Device is in home mode
    HOME = "home"
    # Device is prepared for sleep
    SLEEP = "sleep"
    # Device is reacting to activity (e.g. movement sensors)
    ACTIVITY = "activity"
    SCHEDULE = "Schedule"
    COMPLEX = "Complex"
    TEMP_MANUAL = "Temporary manual"


class FanState(StrEnum):
    """Fan state."""

    # Possible fan state
    ON = "on"
    OFF = "off"
    AUTO = "auto"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TOP = "top"
    MIDDLE = "middle"
    FOCUS = "focus"
    DIFFUSE = "diffuse"


class CurrentHVAC(StrEnum):
    """Current HVAC state."""

    OFF = "off"
    HEAT = "heating"
    COOL = "cooling"
    DRY = "drying"
    IDLE = "idle"
    FAN = "fan"


class HVACAction(StrEnum):
    """HVAC action for climate devices."""

    COOLING = "cooling"
    DRYING = "drying"
    FAN = "fan"
    HEATING = "heating"
    IDLE = "idle"
    OFF = "off"
    PREHEATING = "preheating"


RUNNING_MODE = {0x00: HVACMode.OFF, 0x03: HVACMode.COOL, 0x04: HVACMode.HEAT}

SEQ_OF_OPERATION = {
    0x00: [HVACMode.OFF, HVACMode.COOL],  # cooling only
    0x01: [HVACMode.OFF, HVACMode.COOL],  # cooling with reheat
    0x02: [HVACMode.OFF, HVACMode.HEAT],  # heating only
    0x03: [HVACMode.OFF, HVACMode.HEAT],  # heating with reheat
    # cooling and heating 4-pipes
    0x04: [HVACMode.OFF, HVACMode.HEAT_COOL, HVACMode.COOL, HVACMode.HEAT],
    # cooling and heating 4-pipes
    0x05: [HVACMode.OFF, HVACMode.HEAT_COOL, HVACMode.COOL, HVACMode.HEAT],
    0x06: [HVACMode.COOL, HVACMode.HEAT, HVACMode.OFF],  # centralite specific
    0x07: [HVACMode.HEAT_COOL, HVACMode.OFF],  # centralite specific
}

HVAC_MODE_2_SYSTEM = {
    HVACMode.OFF: SystemMode.Off,
    HVACMode.HEAT_COOL: SystemMode.Auto,
    HVACMode.COOL: SystemMode.Cool,
    HVACMode.HEAT: SystemMode.Heat,
    HVACMode.FAN_ONLY: SystemMode.Fan_only,
    HVACMode.DRY: SystemMode.Dry,
}

SYSTEM_MODE_2_HVAC = {
    SystemMode.Off: HVACMode.OFF,
    SystemMode.Auto: HVACMode.HEAT_COOL,
    SystemMode.Cool: HVACMode.COOL,
    SystemMode.Heat: HVACMode.HEAT,
    SystemMode.Emergency_Heating: HVACMode.HEAT,
    SystemMode.Pre_cooling: HVACMode.COOL,  # this is 'precooling'. is it the same?
    SystemMode.Fan_only: HVACMode.FAN_ONLY,
    SystemMode.Dry: HVACMode.DRY,
    SystemMode.Sleep: HVACMode.OFF,
}

ZCL_TEMP = 100


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    aux_cluster_handlers=CLUSTER_HANDLER_FAN,
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class Thermostat(PlatformEntity):
    """Representation of a ZHA Thermostat device."""

    PLATFORM = Platform.CLIMATE
    DEFAULT_MAX_TEMP = 35
    DEFAULT_MIN_TEMP = 7

    _attr_precision = PRECISION_TENTHS
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_translation_key: str = "thermostat"
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._preset = Preset.NONE
        self._presets = []
        self._supported_flags = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        self._thermostat_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_THERMOSTAT
        )
        self._fan_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_FAN
        )
        self._thermostat_cluster_handler.on_event(
            CLUSTER_HANDLER_EVENT, self._handle_event_protocol
        )

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if self._thermostat_cluster_handler.local_temperature is None:
            return None
        return self._thermostat_cluster_handler.local_temperature / ZCL_TEMP

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        data = {}
        if self.hvac_mode:
            mode = SYSTEM_MODE_2_HVAC.get(
                self._thermostat_cluster_handler.system_mode, "unknown"
            )
            data[ATTR_SYS_MODE] = (
                f"[{self._thermostat_cluster_handler.system_mode}]/{mode}"
            )
        if self._thermostat_cluster_handler.occupancy is not None:
            data[ATTR_OCCUPANCY] = self._thermostat_cluster_handler.occupancy
        if self._thermostat_cluster_handler.occupied_cooling_setpoint is not None:
            data[ATTR_OCCP_COOL_SETPT] = (
                self._thermostat_cluster_handler.occupied_cooling_setpoint
            )
        if self._thermostat_cluster_handler.occupied_heating_setpoint is not None:
            data[ATTR_OCCP_HEAT_SETPT] = (
                self._thermostat_cluster_handler.occupied_heating_setpoint
            )
        if self._thermostat_cluster_handler.pi_heating_demand is not None:
            data[ATTR_PI_HEATING_DEMAND] = (
                self._thermostat_cluster_handler.pi_heating_demand
            )
        if self._thermostat_cluster_handler.pi_cooling_demand is not None:
            data[ATTR_PI_COOLING_DEMAND] = (
                self._thermostat_cluster_handler.pi_cooling_demand
            )

        unoccupied_cooling_setpoint = (
            self._thermostat_cluster_handler.unoccupied_cooling_setpoint
        )
        if unoccupied_cooling_setpoint is not None:
            data[ATTR_UNOCCP_COOL_SETPT] = unoccupied_cooling_setpoint

        unoccupied_heating_setpoint = (
            self._thermostat_cluster_handler.unoccupied_heating_setpoint
        )
        if unoccupied_heating_setpoint is not None:
            data[ATTR_UNOCCP_HEAT_SETPT] = unoccupied_heating_setpoint
        return data

    @property
    def fan_mode(self) -> str | None:
        """Return current FAN mode."""
        if self._thermostat_cluster_handler.running_state is None:
            return FAN_AUTO

        if self._thermostat_cluster_handler.running_state & (
            RunningState.Fan_State_On
            | RunningState.Fan_2nd_Stage_On
            | RunningState.Fan_3rd_Stage_On
        ):
            return FAN_ON
        return FAN_AUTO

    @property
    def fan_modes(self) -> list[str] | None:
        """Return supported FAN modes."""
        if not self._fan_cluster_handler:
            return None
        return [FAN_AUTO, FAN_ON]

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action."""
        if (
            self._thermostat_cluster_handler.pi_heating_demand is None
            and self._thermostat_cluster_handler.pi_cooling_demand is None
        ):
            return self._rm_rs_action
        return self._pi_demand_action

    @property
    def _rm_rs_action(self) -> HVACAction | None:
        """Return the current HVAC action based on running mode and running state."""

        if (running_state := self._thermostat_cluster_handler.running_state) is None:
            return None
        if running_state & (
            RunningState.Heat_State_On | RunningState.Heat_2nd_Stage_On
        ):
            return HVACAction.HEATING
        if running_state & (
            RunningState.Cool_State_On | RunningState.Cool_2nd_Stage_On
        ):
            return HVACAction.COOLING
        if running_state & (
            RunningState.Fan_State_On
            | RunningState.Fan_2nd_Stage_On
            | RunningState.Fan_3rd_Stage_On
        ):
            return HVACAction.FAN
        if running_state & RunningState.Idle:
            return HVACAction.IDLE
        if self.hvac_mode != HVACMode.OFF:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def _pi_demand_action(self) -> HVACAction | None:
        """Return the current HVAC action based on pi_demands."""

        heating_demand = self._thermostat_cluster_handler.pi_heating_demand
        if heating_demand is not None and heating_demand > 0:
            return HVACAction.HEATING
        cooling_demand = self._thermostat_cluster_handler.pi_cooling_demand
        if cooling_demand is not None and cooling_demand > 0:
            return HVACAction.COOLING

        if self.hvac_mode != HVACMode.OFF:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return HVAC operation mode."""
        return SYSTEM_MODE_2_HVAC.get(self._thermostat_cluster_handler.system_mode)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC operation modes."""
        return SEQ_OF_OPERATION.get(
            self._thermostat_cluster_handler.ctrl_sequence_of_oper, [HVACMode.OFF]
        )

    @property
    def preset_mode(self) -> str:
        """Return current preset mode."""
        return self._preset

    @property
    def preset_modes(self) -> list[str] | None:
        """Return supported preset modes."""
        return self._presets

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        features = self._supported_flags
        if HVACMode.HEAT_COOL in self.hvac_modes:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        if self._fan_cluster_handler is not None:
            self._supported_flags |= ClimateEntityFeature.FAN_MODE
        return features

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        temp = None
        if self.hvac_mode == HVACMode.COOL:
            if self.preset_mode == Preset.AWAY:
                temp = self._thermostat_cluster_handler.unoccupied_cooling_setpoint
            else:
                temp = self._thermostat_cluster_handler.occupied_cooling_setpoint
        elif self.hvac_mode == HVACMode.HEAT:
            if self.preset_mode == Preset.AWAY:
                temp = self._thermostat_cluster_handler.unoccupied_heating_setpoint
            else:
                temp = self._thermostat_cluster_handler.occupied_heating_setpoint
        if temp is None:
            return temp
        return round(temp / ZCL_TEMP, 1)

    @property
    def target_temperature_high(self):
        """Return the upper bound temperature we try to reach."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        if self.preset_mode == Preset.AWAY:
            temp = self._thermostat_cluster_handler.unoccupied_cooling_setpoint
        else:
            temp = self._thermostat_cluster_handler.occupied_cooling_setpoint

        if temp is None:
            return temp

        return round(temp / ZCL_TEMP, 1)

    @property
    def target_temperature_low(self):
        """Return the lower bound temperature we try to reach."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        if self.preset_mode == Preset.AWAY:
            temp = self._thermostat_cluster_handler.unoccupied_heating_setpoint
        else:
            temp = self._thermostat_cluster_handler.occupied_heating_setpoint

        if temp is None:
            return temp
        return round(temp / ZCL_TEMP, 1)

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        temps = []
        if HVACMode.HEAT in self.hvac_modes:
            temps.append(self._thermostat_cluster_handler.max_heat_setpoint_limit)
        if HVACMode.COOL in self.hvac_modes:
            temps.append(self._thermostat_cluster_handler.max_cool_setpoint_limit)

        if not temps:
            return self.DEFAULT_MAX_TEMP
        return round(max(temps) / ZCL_TEMP, 1)

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        temps = []
        if HVACMode.HEAT in self.hvac_modes:
            temps.append(self._thermostat_cluster_handler.min_heat_setpoint_limit)
        if HVACMode.COOL in self.hvac_modes:
            temps.append(self._thermostat_cluster_handler.min_cool_setpoint_limit)

        if not temps:
            return self.DEFAULT_MIN_TEMP
        return round(min(temps) / ZCL_TEMP, 1)

    async def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute update from device."""
        if (
            event.attribute_name in (ATTR_OCCP_COOL_SETPT, ATTR_OCCP_HEAT_SETPT)
            and self.preset_mode == Preset.AWAY
        ):
            # occupancy attribute is an unreportable attribute, but if we get
            # an attribute update for an "occupied" setpoint, there's a chance
            # occupancy has changed
            if await self._thermostat_cluster_handler.get_occupancy() is True:
                self._preset = Preset.NONE

        self.debug(
            "Attribute '%s' = %s update", event.attribute_name, event.attribute_value
        )
        self.maybe_send_state_changed_event()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        if not self.fan_modes or fan_mode not in self.fan_modes:
            self.warning("Unsupported '%s' fan mode", fan_mode)
            return

        if fan_mode == FAN_ON:
            mode = FanMode.On
        else:
            mode = FanMode.Auto

        await self._fan_cluster_handler.async_set_speed(mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target operation mode."""
        if hvac_mode not in self.hvac_modes:
            self.warning(
                "can't set '%s' mode. Supported modes are: %s",
                hvac_mode,
                self.hvac_modes,
            )
            return

        if await self._thermostat_cluster_handler.async_set_operation_mode(
            HVAC_MODE_2_SYSTEM[hvac_mode]
        ):
            self.maybe_send_state_changed_event()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        if not self.preset_modes or preset_mode not in self.preset_modes:
            self.debug("Preset mode '%s' is not supported", preset_mode)
            return

        if self.preset_mode not in (
            preset_mode,
            Preset.NONE,
        ):
            await self.async_preset_handler(self.preset_mode, enable=False)

        if preset_mode != Preset.NONE:
            await self.async_preset_handler(preset_mode, enable=True)

        self._preset = preset_mode
        self.maybe_send_state_changed_event()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        low_temp = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high_temp = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp = kwargs.get(ATTR_TEMPERATURE)
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)

        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)

        is_away = self.preset_mode == Preset.AWAY

        if self.hvac_mode == HVACMode.HEAT_COOL:
            if low_temp is not None:
                await self._thermostat_cluster_handler.async_set_heating_setpoint(
                    temperature=int(low_temp * ZCL_TEMP),
                    is_away=is_away,
                )
            if high_temp is not None:
                await self._thermostat_cluster_handler.async_set_cooling_setpoint(
                    temperature=int(high_temp * ZCL_TEMP),
                    is_away=is_away,
                )
        elif temp is not None:
            if self.hvac_mode == HVACMode.COOL:
                await self._thermostat_cluster_handler.async_set_cooling_setpoint(
                    temperature=int(temp * ZCL_TEMP),
                    is_away=is_away,
                )
            elif self.hvac_mode == HVACMode.HEAT:
                await self._thermostat_cluster_handler.async_set_heating_setpoint(
                    temperature=int(temp * ZCL_TEMP),
                    is_away=is_away,
                )
            else:
                self.debug("Not setting temperature for '%s' mode", self.hvac_mode)
                return
        else:
            self.debug("incorrect %s setting for '%s' mode", kwargs, self.hvac_mode)
            return

        self.maybe_send_state_changed_event()

    async def async_preset_handler(self, preset: str, enable: bool = False) -> None:
        """Set the preset mode via handler."""

        handler = getattr(self, f"async_preset_handler_{preset}")
        await handler(enable)

    def to_json(self) -> dict:
        """Return a JSON representation of the thermostat."""
        json = super().to_json()
        json["hvac_modes"] = self.hvac_modes
        json["fan_modes"] = self.fan_modes
        json["preset_modes"] = self.preset_modes
        return json

    def get_state(self) -> dict:
        """Get the state of the lock."""
        response = super().get_state()
        response["current_temperature"] = self.current_temperature
        response["target_temperature"] = self.target_temperature
        response["target_temperature_high"] = self.target_temperature_high
        response["target_temperature_low"] = self.target_temperature_low
        response["hvac_action"] = self.hvac_action
        response["hvac_mode"] = self.hvac_mode
        response["preset_mode"] = self.preset_mode
        response["fan_mode"] = self.fan_mode
        return response


@MULTI_MATCH(
    cluster_handler_names={CLUSTER_HANDLER_THERMOSTAT, "sinope_manufacturer_specific"},
    manufacturers="Sinope Technologies",
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class SinopeTechnologiesThermostat(Thermostat):
    """Sinope Technologies Thermostat."""

    manufacturer = 0x119C

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._presets = [Preset.AWAY, Preset.NONE]
        self._supported_flags |= ClimateEntityFeature.PRESET_MODE
        self._manufacturer_ch = self.cluster_handlers["sinope_manufacturer_specific"]

        self._tracked_tasks.append(
            device.gateway.async_create_background_task(
                self._update_time(),
                name=f"sinope_time_updater_{self.unique_id}",
                eager_start=True,
            )
        )

    @periodic((2700, 4500))
    async def _update_time(self) -> None:
        await self._async_update_time()

    @property
    def _rm_rs_action(self) -> HVACAction:
        """Return the current HVAC action based on running mode and running state."""

        running_mode = self._thermostat_cluster_handler.running_mode
        if running_mode == SystemMode.Heat:
            return HVACAction.HEATING
        if running_mode == SystemMode.Cool:
            return HVACAction.COOLING

        running_state = self._thermostat_cluster_handler.running_state
        if running_state and running_state & (
            RunningState.Fan_State_On
            | RunningState.Fan_2nd_Stage_On
            | RunningState.Fan_3rd_Stage_On
        ):
            return HVACAction.FAN
        if self.hvac_mode != HVACMode.OFF and running_mode == SystemMode.Off:
            return HVACAction.IDLE
        return HVACAction.OFF

    async def _async_update_time(self) -> None:
        """Update thermostat's time display."""

        secs_2k = (
            dt.datetime.now(dt.UTC).replace(tzinfo=None)
            - dt.datetime(2000, 1, 1, 0, 0, 0, 0)
        ).total_seconds()

        self.debug("Updating time: %s", secs_2k)
        await self._manufacturer_ch.write_attributes_safe(
            {"secs_since_2k": secs_2k}, manufacturer=self.manufacturer
        )

    async def async_preset_handler_away(self, is_away: bool = False) -> None:
        """Set occupancy."""
        mfg_code = self._device.manufacturer_code
        await self._thermostat_cluster_handler.write_attributes_safe(
            {"set_occupancy": 0 if is_away else 1}, manufacturer=mfg_code
        )


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    aux_cluster_handlers=CLUSTER_HANDLER_FAN,
    manufacturers={"Zen Within", "LUX"},
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class ZenWithinThermostat(Thermostat):
    """Zen Within Thermostat implementation."""


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    aux_cluster_handlers=CLUSTER_HANDLER_FAN,
    manufacturers="Centralite",
    models={"3157100", "3157100-E"},
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class CentralitePearl(ZenWithinThermostat):
    """Centralite Pearl Thermostat implementation."""


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    manufacturers={
        "_TZE200_ckud7u2l",
        "_TZE200_ywdxldoj",
        "_TZE200_cwnjrr72",
        "_TZE200_2atgpdho",
        "_TZE200_pvvbommb",
        "_TZE200_4eeyebrt",
        "_TZE200_cpmgn2cf",
        "_TZE200_9sfg7gm0",
        "_TZE200_8whxpsiw",
        "_TYST11_ckud7u2l",
        "_TYST11_ywdxldoj",
        "_TYST11_cwnjrr72",
        "_TYST11_2atgpdho",
    },
)
class MoesThermostat(Thermostat):
    """Moes Thermostat implementation."""

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._presets = [
            Preset.NONE,
            Preset.AWAY,
            Preset.SCHEDULE,
            Preset.COMFORT,
            Preset.ECO,
            Preset.BOOST,
            Preset.COMPLEX,
        ]
        self._supported_flags |= ClimateEntityFeature.PRESET_MODE

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return only the heat mode, because the device can't be turned off."""
        return [HVACMode.HEAT]

    async def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute update from device."""
        if event.attribute_name == "operation_preset":
            if event.attribute_value == 0:
                self._preset = Preset.AWAY
            if event.attribute_value == 1:
                self._preset = Preset.SCHEDULE
            if event.attribute_value == 2:
                self._preset = Preset.NONE
            if event.attribute_value == 3:
                self._preset = Preset.COMFORT
            if event.attribute_value == 4:
                self._preset = Preset.ECO
            if event.attribute_value == 5:
                self._preset = Preset.BOOST
            if event.attribute_value == 6:
                self._preset = Preset.COMPLEX
        await super().handle_cluster_handler_attribute_updated(event)

    async def async_preset_handler(self, preset: str, enable: bool = False) -> None:
        """Set the preset mode."""
        mfg_code = self._device.manufacturer_code
        if not enable:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 2}, manufacturer=mfg_code
            )
        if preset == Preset.AWAY:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 0}, manufacturer=mfg_code
            )
        if preset == Preset.SCHEDULE:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 1}, manufacturer=mfg_code
            )
        if preset == Preset.COMFORT:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 3}, manufacturer=mfg_code
            )
        if preset == Preset.ECO:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 4}, manufacturer=mfg_code
            )
        if preset == Preset.BOOST:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 5}, manufacturer=mfg_code
            )
        if preset == Preset.COMPLEX:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 6}, manufacturer=mfg_code
            )


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    manufacturers={
        "_TZE200_b6wax7g0",
    },
)
class BecaThermostat(Thermostat):
    """Beca Thermostat implementation."""

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._presets = [
            Preset.NONE,
            Preset.AWAY,
            Preset.SCHEDULE,
            Preset.ECO,
            Preset.BOOST,
            Preset.TEMP_MANUAL,
        ]
        self._supported_flags |= ClimateEntityFeature.PRESET_MODE

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return only the heat mode, because the device can't be turned off."""
        return [HVACMode.HEAT]

    async def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute update from device."""
        if event.attribute_name == "operation_preset":
            if event.attribute_value == 0:
                self._preset = Preset.AWAY
            if event.attribute_value == 1:
                self._preset = Preset.SCHEDULE
            if event.attribute_value == 2:
                self._preset = Preset.NONE
            if event.attribute_value == 4:
                self._preset = Preset.ECO
            if event.attribute_value == 5:
                self._preset = Preset.BOOST
            if event.attribute_value == 7:
                self._preset = Preset.TEMP_MANUAL
        await super().handle_cluster_handler_attribute_updated(event)

    async def async_preset_handler(self, preset: str, enable: bool = False) -> None:
        """Set the preset mode."""
        mfg_code = self._device.manufacturer_code
        if not enable:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 2}, manufacturer=mfg_code
            )
        if preset == Preset.AWAY:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 0}, manufacturer=mfg_code
            )
        if preset == Preset.SCHEDULE:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 1}, manufacturer=mfg_code
            )
        if preset == Preset.ECO:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 4}, manufacturer=mfg_code
            )
        if preset == Preset.BOOST:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 5}, manufacturer=mfg_code
            )
        if preset == Preset.TEMP_MANUAL:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 7}, manufacturer=mfg_code
            )


@MULTI_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    manufacturers="Stelpro",
    models={"SORB"},
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class StelproFanHeater(Thermostat):
    """Stelpro Fan Heater implementation."""

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return only the heat mode, because the device can't be turned off."""
        return [HVACMode.HEAT]


@STRICT_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    manufacturers={
        "_TZE200_7yoranx2",
        "_TZE200_e9ba97vf",  # TV01-ZG
        "_TZE200_hue3yfsn",  # TV02-ZG
        "_TZE200_husqqvux",  # TSL-TRV-TV01ZG
        "_TZE200_kds0pmmv",  # MOES TRV TV02
        "_TZE200_kly8gjlz",  # TV05-ZG
        "_TZE200_lnbfnyxd",
        "_TZE200_mudxchsu",
    },
)
class ZONNSMARTThermostat(Thermostat):
    """ZONNSMART Thermostat implementation.

    Notice that this device uses two holiday presets (2: HolidayMode,
    3: HolidayModeTemp), but only one of them can be set.
    """

    PRESET_HOLIDAY = "holiday"
    PRESET_FROST = "frost protect"

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: ZHADevice,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(unique_id, cluster_handlers, endpoint, device, **kwargs)
        self._presets = [
            Preset.NONE,
            self.PRESET_HOLIDAY,
            Preset.SCHEDULE,
            self.PRESET_FROST,
        ]
        self._supported_flags |= ClimateEntityFeature.PRESET_MODE

    async def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute update from device."""
        if event.attribute_name == "operation_preset":
            if event.attribute_value == 0:
                self._preset = Preset.SCHEDULE
            if event.attribute_value == 1:
                self._preset = Preset.NONE
            if event.attribute_value in (2, 3):
                self._preset = self.PRESET_HOLIDAY
            if event.attribute_value == 4:
                self._preset = self.PRESET_FROST
        await super().handle_cluster_handler_attribute_updated(event)

    async def async_preset_handler(self, preset: str, enable: bool = False) -> None:
        """Set the preset mode."""
        mfg_code = self._device.manufacturer_code
        if not enable:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 1}, manufacturer=mfg_code
            )
        if preset == Preset.SCHEDULE:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 0}, manufacturer=mfg_code
            )
        if preset == self.PRESET_HOLIDAY:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 3}, manufacturer=mfg_code
            )
        if preset == self.PRESET_FROST:
            return await self._thermostat_cluster_handler.write_attributes_safe(
                {"operation_preset": 4}, manufacturer=mfg_code
            )
