"""Climate on Zigbee Home Automation."""  # pylint: disable=too-many-lines

from __future__ import annotations

from asyncio import Task
from dataclasses import dataclass
import datetime as dt
import functools
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.hvac import FanMode, RunningState, SystemMode

from zha.application import Platform
from zha.application.platforms import BaseEntityInfo, PlatformEntity
from zha.application.platforms.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_OCCP_COOL_SETPT,
    ATTR_OCCP_HEAT_SETPT,
    ATTR_OCCUPANCY,
    ATTR_PI_COOLING_DEMAND,
    ATTR_PI_HEATING_DEMAND,
    ATTR_SYS_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ATTR_TEMPERATURE,
    ATTR_UNOCCP_COOL_SETPT,
    ATTR_UNOCCP_HEAT_SETPT,
    FAN_AUTO,
    FAN_ON,
    HVAC_MODE_2_SYSTEM,
    PRECISION_TENTHS,
    SEQ_OF_OPERATION,
    SYSTEM_MODE_2_HVAC,
    ZCL_TEMP,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    Preset,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.decorators import periodic
from zha.units import UnitOfTemperature
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_FAN,
    CLUSTER_HANDLER_THERMOSTAT,
)

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.CLIMATE)
MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.CLIMATE)


@dataclass(frozen=True, kw_only=True)
class ThermostatEntityInfo(BaseEntityInfo):
    """Thermostat entity info."""

    max_temp: float
    min_temp: float
    supported_features: ClimateEntityFeature
    fan_modes: list[str] | None
    preset_modes: list[str] | None
    hvac_modes: list[HVACMode]


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
    _attr_extra_state_attribute_names: set[str] = {
        ATTR_SYS_MODE,
        ATTR_OCCUPANCY,
        ATTR_OCCP_COOL_SETPT,
        ATTR_OCCP_HEAT_SETPT,
        ATTR_PI_HEATING_DEMAND,
        ATTR_PI_COOLING_DEMAND,
        ATTR_UNOCCP_COOL_SETPT,
        ATTR_UNOCCP_HEAT_SETPT,
    }
    _attr_primary_weight = 10

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._preset = Preset.NONE
        self._presets: list[Preset | str] = []

        self._thermostat_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_THERMOSTAT
        )
        self._fan_cluster_handler: ClusterHandler = self.cluster_handlers.get(
            CLUSTER_HANDLER_FAN
        )

        self._supported_features = ClimateEntityFeature(0)
        self.recompute_capabilities()

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags."""
        super().recompute_capabilities()
        self._supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )

        if HVACMode.HEAT_COOL in self.hvac_modes:
            self._supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

        if self._fan_cluster_handler is not None:
            self._supported_features |= ClimateEntityFeature.FAN_MODE

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._on_remove_callbacks.append(
            self._thermostat_cluster_handler.on_event(
                CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
                self.handle_cluster_handler_attribute_updated,
            )
        )

    @functools.cached_property
    def info_object(self) -> ThermostatEntityInfo:
        """Return a representation of the thermostat."""
        return ThermostatEntityInfo(
            **super().info_object.__dict__,
            max_temp=self.max_temp,
            min_temp=self.min_temp,
            supported_features=self.supported_features,
            fan_modes=self.fan_modes,
            preset_modes=self.preset_modes,
            hvac_modes=self.hvac_modes,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the thermostat."""
        thermostat = self._thermostat_cluster_handler
        system_mode = SYSTEM_MODE_2_HVAC.get(thermostat.system_mode, "unknown")

        response = super().state
        response["current_temperature"] = self.current_temperature
        response["outdoor_temperature"] = self.outdoor_temperature
        response["target_temperature"] = self.target_temperature
        response["target_temperature_high"] = self.target_temperature_high
        response["target_temperature_low"] = self.target_temperature_low
        response["hvac_action"] = self.hvac_action
        response["hvac_mode"] = self.hvac_mode
        response["preset_mode"] = self.preset_mode
        response["fan_mode"] = self.fan_mode

        response[ATTR_SYS_MODE] = (
            f"[{thermostat.system_mode}]/{system_mode}"
            if self.hvac_mode is not None
            else None
        )
        response[ATTR_OCCUPANCY] = thermostat.occupancy
        response[ATTR_OCCP_COOL_SETPT] = thermostat.occupied_cooling_setpoint
        response[ATTR_OCCP_HEAT_SETPT] = thermostat.occupied_heating_setpoint
        response[ATTR_PI_HEATING_DEMAND] = thermostat.pi_heating_demand
        response[ATTR_PI_COOLING_DEMAND] = thermostat.pi_cooling_demand
        response[ATTR_UNOCCP_COOL_SETPT] = thermostat.unoccupied_cooling_setpoint
        response[ATTR_UNOCCP_HEAT_SETPT] = thermostat.unoccupied_heating_setpoint
        return response

    @property
    def current_temperature(self):
        """Return the current temperature."""
        if self._thermostat_cluster_handler.local_temperature is None:
            return None
        return self._thermostat_cluster_handler.local_temperature / ZCL_TEMP

    @property
    def outdoor_temperature(self):
        """Return the outdoor temperature."""
        if self._thermostat_cluster_handler.outdoor_temperature is None:
            return None
        return self._thermostat_cluster_handler.outdoor_temperature / ZCL_TEMP

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

    @functools.cached_property
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
        return self._supported_features

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

    def handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute update from device."""
        self.device.gateway.async_create_task(
            self._handle_cluster_handler_attribute_updated(event)
        )

    async def _handle_cluster_handler_attribute_updated(
        self, event: ClusterAttributeUpdatedEvent
    ) -> None:
        """Handle attribute update from device."""
        if (
            event.attribute_name in (ATTR_OCCP_COOL_SETPT, ATTR_OCCP_HEAT_SETPT)
            and self.preset_mode == Preset.AWAY
            and await self._thermostat_cluster_handler.get_occupancy() is True
        ):
            # occupancy attribute is an unreportable attribute, but if we get
            # an attribute update for an "occupied" setpoint, there's a chance
            # occupancy has changed
            self._preset = Preset.NONE

        self.debug(
            "Attribute '%s' = %s update", event.attribute_name, event.attribute_value
        )
        self.maybe_emit_state_changed_event()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode."""
        if not self.fan_modes or fan_mode not in self.fan_modes:
            self.warning("Unsupported '%s' fan mode", fan_mode)
            return

        mode = FanMode.On if fan_mode == FAN_ON else FanMode.Auto

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
            self.maybe_emit_state_changed_event()

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
        self.maybe_emit_state_changed_event()

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

        self.maybe_emit_state_changed_event()

    async def async_preset_handler(self, preset: str, enable: bool = False) -> None:
        """Set the preset mode via handler."""

        handler = getattr(self, f"async_preset_handler_{preset}")
        await handler(enable)


@MULTI_MATCH(
    cluster_handler_names={CLUSTER_HANDLER_THERMOSTAT, "sinope_manufacturer_specific"},
    manufacturers="Sinope Technologies",
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class SinopeTechnologiesThermostat(Thermostat):
    """Sinope Technologies Thermostat."""

    manufacturer = 0x119C
    __polling_interval: int

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs,
    ):
        """Initialize ZHA Thermostat instance."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._presets = [Preset.AWAY, Preset.NONE]
        self._manufacturer_ch = self.cluster_handlers["sinope_manufacturer_specific"]
        self._time_update_task: Task | None = None

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags."""
        super().recompute_capabilities()
        self._supported_features |= ClimateEntityFeature.PRESET_MODE

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self.start_polling()

    def start_polling(self) -> None:
        """Start polling."""
        self._time_update_task = self.device.gateway.async_create_background_task(
            self._update_time(),
            name=f"sinope_time_updater_{self.unique_id}",
            eager_start=True,
            untracked=True,
        )
        self._tracked_tasks.append(self._time_update_task)
        self.debug(
            "started time updating interval of %s",
            getattr(self, "__polling_interval"),
        )

    def enable(self) -> None:
        """Enable the entity."""
        super().enable()
        self.start_polling()

    def disable(self) -> None:
        """Disable the entity."""
        super().disable()
        if self._time_update_task:
            self._tracked_tasks.remove(self._time_update_task)
            self._time_update_task.cancel()
            self._time_update_task = None

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

        now = dt.datetime.now(self._device.gateway.config.local_timezone)
        secs_2k = (
            now.replace(tzinfo=None) - dt.datetime(2000, 1, 1, 0, 0, 0, 0)
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
    manufacturers={"ZEHNDER GROUP VAUX ANDIGNY      ", "ZEHNDER GROUP VAUX ANDIGNY"},
    stop_on_match_group=CLUSTER_HANDLER_THERMOSTAT,
)
class ZehnderThermostat(Thermostat):
    """Zehnder thermostat to adapt AUTO mode behavior."""

    ZEHNDER_HVAC_MODE_2_SYSTEM = {
        HVACMode.OFF: SystemMode.Off,
        HVACMode.HEAT: SystemMode.Auto,
    }

    ZEHNDER_SYSTEM_MODE_2_HVAC = {
        SystemMode.Off: HVACMode.OFF,
        SystemMode.Auto: HVACMode.HEAT,
    }

    hvac_modes = [HVACMode.OFF, HVACMode.HEAT]

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
            ZehnderThermostat.ZEHNDER_HVAC_MODE_2_SYSTEM[hvac_mode]
        ):
            self.maybe_emit_state_changed_event()

    @property
    def current_temperature(self):
        """Force no current temperature."""
        return None

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the lock."""
        thermostat = self._thermostat_cluster_handler
        system_mode = ZehnderThermostat.ZEHNDER_SYSTEM_MODE_2_HVAC.get(
            thermostat.system_mode, "unknown"
        )

        response = super().state

        response[ATTR_SYS_MODE] = (
            f"[{thermostat.system_mode}]/{system_mode}"
            if self.hvac_mode is not None
            else None
        )

        return response

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return HVAC operation mode."""
        return ZehnderThermostat.ZEHNDER_SYSTEM_MODE_2_HVAC.get(
            self._thermostat_cluster_handler.system_mode
        )


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

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags."""
        super().recompute_capabilities()
        self._presets = [
            Preset.NONE,
            Preset.AWAY,
            Preset.SCHEDULE,
            Preset.COMFORT,
            Preset.ECO,
            Preset.BOOST,
            Preset.COMPLEX,
        ]
        self._supported_features |= ClimateEntityFeature.PRESET_MODE

    @functools.cached_property
    def hvac_modes(self) -> list[HVACMode]:
        """Return only the heat mode, because the device can't be turned off."""
        return [HVACMode.HEAT]

    def handle_cluster_handler_attribute_updated(
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
        super().handle_cluster_handler_attribute_updated(event)

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

    def recompute_capabilities(self) -> None:
        """Recompute capabilities and feature flags."""
        super().recompute_capabilities()
        self._presets = [
            Preset.NONE,
            Preset.AWAY,
            Preset.SCHEDULE,
            Preset.ECO,
            Preset.BOOST,
            Preset.TEMP_MANUAL,
        ]
        self._supported_features |= ClimateEntityFeature.PRESET_MODE

    @functools.cached_property
    def hvac_modes(self) -> list[HVACMode]:
        """Return only the heat mode, because the device can't be turned off."""
        return [HVACMode.HEAT]

    def handle_cluster_handler_attribute_updated(
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
        super().handle_cluster_handler_attribute_updated(event)

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

    @functools.cached_property
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

    def recompute_capabilities(self) -> None:
        """Recompute capabilities."""
        super().recompute_capabilities()
        self._presets = [
            Preset.NONE,
            self.PRESET_HOLIDAY,
            Preset.SCHEDULE,
            self.PRESET_FROST,
        ]
        self._supported_features |= ClimateEntityFeature.PRESET_MODE

    def handle_cluster_handler_attribute_updated(
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
        super().handle_cluster_handler_attribute_updated(event)

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
