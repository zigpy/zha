"""Switches on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
import functools
import logging
from typing import TYPE_CHECKING, Any, cast

from zhaquirks.quirk_ids import DANFOSS_ALLY_THERMOSTAT, TUYA_PLUG_ONOFF
from zigpy.quirks.v2 import SwitchMetadata
from zigpy.zcl.clusters.closures import ConfigStatus, WindowCovering, WindowCoveringMode
from zigpy.zcl.clusters.general import OnOff
from zigpy.zcl.foundation import Status

from zha.application import Platform
from zha.application.platforms import (
    BaseEntity,
    BaseEntityInfo,
    EntityCategory,
    GroupEntity,
    PlatformEntity,
)
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_BASIC,
    CLUSTER_HANDLER_COVER,
    CLUSTER_HANDLER_INOVELLI,
    CLUSTER_HANDLER_ON_OFF,
    CLUSTER_HANDLER_THERMOSTAT,
)
from zha.zigbee.cluster_handlers.general import OnOffClusterHandler
from zha.zigbee.group import Group

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

STRICT_MATCH = functools.partial(PLATFORM_ENTITIES.strict_match, Platform.SWITCH)
GROUP_MATCH = functools.partial(PLATFORM_ENTITIES.group_match, Platform.SWITCH)
CONFIG_DIAGNOSTIC_MATCH = functools.partial(
    PLATFORM_ENTITIES.config_diagnostic_match, Platform.SWITCH
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class ConfigurableAttributeSwitchInfo(BaseEntityInfo):
    """Switch configuration entity info."""

    attribute_name: str
    invert_attribute_name: str | None
    force_inverted: bool
    off_value: int
    on_value: int


class BaseSwitch(BaseEntity, ABC):
    """Common base class for zhawss switches."""

    PLATFORM = Platform.SWITCH
    _attr_primary_weight = 10

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ):
        """Initialize the switch."""
        self._on_off_cluster_handler: OnOffClusterHandler
        super().__init__(*args, **kwargs)

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the switch."""
        response = super().state
        response["state"] = self.is_on
        return response

    @property
    def is_on(self) -> bool:
        """Return if the switch is on based on the statemachine."""
        if self._on_off_cluster_handler.on_off is None:
            return False
        return self._on_off_cluster_handler.on_off

    # TODO revert this once group entities use cluster handlers
    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity on."""
        await self._on_off_cluster_handler.turn_on()
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity off."""
        await self._on_off_cluster_handler.turn_off()
        self.maybe_emit_state_changed_event()


@STRICT_MATCH(cluster_handler_names=CLUSTER_HANDLER_ON_OFF)
class Switch(PlatformEntity, BaseSwitch):
    """ZHA switch."""

    _attr_translation_key = "switch"
    _attr_primary_weight = 10

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Initialize the ZHA switch."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._on_off_cluster_handler: OnOffClusterHandler = cast(
            OnOffClusterHandler, self.cluster_handlers[CLUSTER_HANDLER_ON_OFF]
        )

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        self._on_remove_callbacks.append(
            self._on_off_cluster_handler.on_event(
                CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
                self.handle_cluster_handler_attribute_updated,
            )
        )

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state update from cluster handler."""
        if event.attribute_name == OnOff.AttributeDefs.on_off.name:
            self.maybe_emit_state_changed_event()


@GROUP_MATCH()
class SwitchGroup(GroupEntity, BaseSwitch):
    """Representation of a switch group."""

    def __init__(self, group: Group):
        """Initialize a switch group."""
        super().__init__(group)
        self._state: bool
        self._on_off_cluster_handler = group.zigpy_group.endpoint[OnOff.cluster_id]
        if hasattr(self, "info_object"):
            delattr(self, "info_object")
        self.update()

    @property
    def is_on(self) -> bool:
        """Return if the switch is on based on the statemachine."""
        return bool(self._state)

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity on."""
        result = await self._on_off_cluster_handler.on()
        if isinstance(result, Exception) or result[1] is not Status.SUCCESS:
            return
        self._state = True
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity off."""
        result = await self._on_off_cluster_handler.off()
        if isinstance(result, Exception) or result[1] is not Status.SUCCESS:
            return
        self._state = False
        self.maybe_emit_state_changed_event()

    def update(self, _: Any | None = None) -> None:
        """Query all members and determine the light group state."""
        self.debug("Updating switch group entity state")
        platform_entities = self._group.get_platform_entities(self.PLATFORM)
        all_states = [entity.state for entity in platform_entities]
        self.debug(
            "All platform entity states for group entity members: %s", all_states
        )
        on_states = [state for state in all_states if state["state"]]

        self._state = len(on_states) > 0

        self.maybe_emit_state_changed_event()


class ConfigurableAttributeSwitch(PlatformEntity):
    """Representation of a ZHA switch configuration entity."""

    PLATFORM = Platform.SWITCH

    _attr_entity_category = EntityCategory.CONFIG
    _attribute_name: str
    _inverter_attribute_name: str | None = None
    _force_inverted: bool = False
    _off_value: int = 0
    _on_value: int = 1

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this number configuration entity."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

    def _init_from_quirks_metadata(self, entity_metadata: SwitchMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        self._attribute_name = entity_metadata.attribute_name
        if entity_metadata.invert_attribute_name:
            self._inverter_attribute_name = entity_metadata.invert_attribute_name
        if entity_metadata.force_inverted:
            self._force_inverted = entity_metadata.force_inverted
        self._off_value = entity_metadata.off_value
        self._on_value = entity_metadata.on_value

    def _is_supported(self) -> bool:
        if (
            self._attribute_name in self._cluster_handler.cluster.unsupported_attributes
            or self._attribute_name
            not in self._cluster_handler.cluster.attributes_by_name
            or self._cluster_handler.cluster.get(self._attribute_name) is None
        ):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                self._attribute_name,
                self.__class__.__name__,
            )
            return False

        return super()._is_supported()

    @functools.cached_property
    def info_object(self) -> ConfigurableAttributeSwitchInfo:
        """Return representation of the switch configuration entity."""
        return ConfigurableAttributeSwitchInfo(
            **super().info_object.__dict__,
            attribute_name=self._attribute_name,
            invert_attribute_name=self._inverter_attribute_name,
            force_inverted=self._force_inverted,
            off_value=self._off_value,
            on_value=self._on_value,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the switch."""
        response = super().state
        response["state"] = self.is_on
        response["inverted"] = self.inverted
        return response

    @property
    def inverted(self) -> bool:
        """Return True if the switch is inverted."""
        if self._inverter_attribute_name:
            return bool(
                self._cluster_handler.cluster.get(self._inverter_attribute_name)
            )
        return self._force_inverted

    @property
    def is_on(self) -> bool:
        """Return if the switch is on based on the statemachine."""
        if self._on_value != 1:
            val = self._cluster_handler.cluster.get(self._attribute_name)
            val = val == self._on_value
        else:
            val = bool(self._cluster_handler.cluster.get(self._attribute_name))
        return (not val) if self.inverted else val

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,  # pylint: disable=unused-argument
    ) -> None:
        """Handle state update from cluster handler."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    async def async_turn_on_off(self, state: bool) -> None:
        """Turn the entity on or off."""
        if self.inverted:
            state = not state
        if state:
            await self._cluster_handler.write_attributes_safe(
                {self._attribute_name: self._on_value}
            )
        else:
            await self._cluster_handler.write_attributes_safe(
                {self._attribute_name: self._off_value}
            )
        self.maybe_emit_state_changed_event()

    async def async_turn_on(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity on."""
        await self.async_turn_on_off(True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn the entity off."""
        await self.async_turn_on_off(False)

    async def async_update(self) -> None:
        """Attempt to retrieve the state of the entity."""
        self.debug("Polling current state")

        polling_attrs = [self._attribute_name]
        if self._inverter_attribute_name:
            polling_attrs.append(self._inverter_attribute_name)

        results = await self._cluster_handler.get_attributes(
            polling_attrs, from_cache=False, only_cache=False
        )

        self.debug("read values=%s", results)
        self.maybe_emit_state_changed_event()


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="tuya_manufacturer",
    manufacturers={
        "_TZE200_b6wax7g0",
    },
)
class OnOffWindowDetectionFunctionConfigurationEntity(ConfigurableAttributeSwitch):
    """Representation of a ZHA window detection configuration entity."""

    _unique_id_suffix = "on_off_window_opened_detection"
    _attribute_name = "window_detection_function"
    _inverter_attribute_name = "window_detection_function_inverter"
    _attr_translation_key = "window_detection_function"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.motion.ac02"}
)
class P1MotionTriggerIndicatorSwitch(ConfigurableAttributeSwitch):
    """Representation of a ZHA motion triggering configuration entity."""

    _unique_id_suffix = "trigger_indicator"
    _attribute_name = "trigger_indicator"
    _attr_translation_key = "trigger_indicator"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster",
    models={"lumi.plug.mmeu01", "lumi.plug.maeu01"},
)
class XiaomiPlugPowerOutageMemorySwitch(ConfigurableAttributeSwitch):
    """Representation of a ZHA power outage memory configuration entity."""

    _unique_id_suffix = "power_outage_memory"
    _attribute_name = "power_outage_memory"
    _attr_translation_key = "power_outage_memory"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_BASIC,
    manufacturers={"Philips", "Signify Netherlands B.V."},
    models={"SML001", "SML002", "SML003", "SML004"},
)
class HueMotionTriggerIndicatorSwitch(ConfigurableAttributeSwitch):
    """Representation of a ZHA motion triggering configuration entity."""

    _unique_id_suffix = "trigger_indicator"
    _attribute_name = "trigger_indicator"
    _attr_translation_key = "trigger_indicator"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="ikea_airpurifier",
    models={"STARKVIND Air purifier", "STARKVIND Air purifier table"},
)
class ChildLock(ConfigurableAttributeSwitch):
    """ZHA BinarySensor."""

    _unique_id_suffix = "child_lock"
    _attribute_name = "child_lock"
    _attr_translation_key = "child_lock"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="ikea_airpurifier",
    models={"STARKVIND Air purifier", "STARKVIND Air purifier table"},
)
class DisableLed(ConfigurableAttributeSwitch):
    """ZHA BinarySensor."""

    _unique_id_suffix = "disable_led"
    _attribute_name = "disable_led"
    _attr_translation_key = "disable_led"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliInvertSwitch(ConfigurableAttributeSwitch):
    """Inovelli invert switch control."""

    _unique_id_suffix = "invert_switch"
    _attribute_name = "invert_switch"
    _attr_translation_key = "invert_switch"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliSmartBulbMode(ConfigurableAttributeSwitch):
    """Inovelli smart bulb mode control."""

    _unique_id_suffix = "smart_bulb_mode"
    _attribute_name = "smart_bulb_mode"
    _attr_translation_key = "smart_bulb_mode"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI, models={"VZM35-SN"}
)
class InovelliSmartFanMode(ConfigurableAttributeSwitch):
    """Inovelli smart fan mode control."""

    _unique_id_suffix = "smart_fan_mode"
    _attribute_name = "smart_fan_mode"
    _attr_translation_key = "smart_fan_mode"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliDoubleTapUpEnabled(ConfigurableAttributeSwitch):
    """Inovelli double tap up enabled."""

    _unique_id_suffix = "double_tap_up_enabled"
    _attribute_name = "double_tap_up_enabled"
    _attr_translation_key = "double_tap_up_enabled"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliDoubleTapDownEnabled(ConfigurableAttributeSwitch):
    """Inovelli double tap down enabled."""

    _unique_id_suffix = "double_tap_down_enabled"
    _attribute_name = "double_tap_down_enabled"
    _attr_translation_key = "double_tap_down_enabled"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliAuxSwitchScenes(ConfigurableAttributeSwitch):
    """Inovelli unique aux switch scenes."""

    _unique_id_suffix = "aux_switch_scenes"
    _attribute_name = "aux_switch_scenes"
    _attr_translation_key = "aux_switch_scenes"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliBindingOffToOnSyncLevel(ConfigurableAttributeSwitch):
    """Inovelli send move to level with on/off to bound devices."""

    _unique_id_suffix = "binding_off_to_on_sync_level"
    _attribute_name = "binding_off_to_on_sync_level"
    _attr_translation_key = "binding_off_to_on_sync_level"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliLocalProtection(ConfigurableAttributeSwitch):
    """Inovelli local protection control."""

    _unique_id_suffix = "local_protection"
    _attribute_name = "local_protection"
    _attr_translation_key = "local_protection"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliOnOffLEDMode(ConfigurableAttributeSwitch):
    """Inovelli only 1 LED mode control."""

    _unique_id_suffix = "on_off_led_mode"
    _attribute_name = "on_off_led_mode"
    _attr_translation_key = "one_led_mode"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliFirmwareProgressLED(ConfigurableAttributeSwitch):
    """Inovelli firmware progress LED control."""

    _unique_id_suffix = "firmware_progress_led"
    _attribute_name = "firmware_progress_led"
    _attr_translation_key = "firmware_progress_led"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliRelayClickInOnOffMode(ConfigurableAttributeSwitch):
    """Inovelli relay click in on off mode control."""

    _unique_id_suffix = "relay_click_in_on_off_mode"
    _attribute_name = "relay_click_in_on_off_mode"
    _attr_translation_key = "relay_click_in_on_off_mode"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_INOVELLI,
)
class InovelliDisableDoubleTapClearNotificationsMode(ConfigurableAttributeSwitch):
    """Inovelli disable clear notifications double tap control."""

    _unique_id_suffix = "disable_clear_notifications_double_tap"
    _attribute_name = "disable_clear_notifications_double_tap"
    _attr_translation_key = "disable_clear_notifications_double_tap"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"}
)
class AqaraPetFeederLEDIndicator(ConfigurableAttributeSwitch):
    """Representation of a LED indicator configuration entity."""

    _unique_id_suffix = "disable_led_indicator"
    _attribute_name = "disable_led_indicator"
    _attr_translation_key = "led_indicator"
    _force_inverted = True


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"}
)
class AqaraPetFeederChildLock(ConfigurableAttributeSwitch):
    """Representation of a child lock configuration entity."""

    _unique_id_suffix = "child_lock"
    _attribute_name = "child_lock"
    _attr_translation_key = "child_lock"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_ON_OFF, quirk_ids=TUYA_PLUG_ONOFF
)
class TuyaChildLockSwitch(ConfigurableAttributeSwitch):
    """Representation of a child lock configuration entity."""

    _unique_id_suffix = "child_lock"
    _attribute_name = "child_lock"
    _attr_translation_key = "child_lock"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"}
)
class AqaraThermostatWindowDetection(ConfigurableAttributeSwitch):
    """Representation of an Aqara thermostat window detection configuration entity."""

    _unique_id_suffix = "window_detection"
    _attribute_name = "window_detection"
    _attr_translation_key = "window_detection"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"}
)
class AqaraThermostatValveDetection(ConfigurableAttributeSwitch):
    """Representation of an Aqara thermostat valve detection configuration entity."""

    _unique_id_suffix = "valve_detection"
    _attribute_name = "valve_detection"
    _attr_translation_key = "valve_detection"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.airrtc.agl001"}
)
class AqaraThermostatChildLock(ConfigurableAttributeSwitch):
    """Representation of an Aqara thermostat child lock configuration entity."""

    _unique_id_suffix = "child_lock"
    _attribute_name = "child_lock"
    _attr_translation_key = "child_lock"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"}
)
class AqaraHeartbeatIndicator(ConfigurableAttributeSwitch):
    """Representation of a heartbeat indicator configuration entity for Aqara smoke sensors."""

    _unique_id_suffix = "heartbeat_indicator"
    _attribute_name = "heartbeat_indicator"
    _attr_translation_key = "heartbeat_indicator"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"}
)
class AqaraLinkageAlarm(ConfigurableAttributeSwitch):
    """Representation of a linkage alarm configuration entity for Aqara smoke sensors."""

    _unique_id_suffix = "linkage_alarm"
    _attribute_name = "linkage_alarm"
    _attr_translation_key = "linkage_alarm"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"}
)
class AqaraBuzzerManualMute(ConfigurableAttributeSwitch):
    """Representation of a buzzer manual mute configuration entity for Aqara smoke sensors."""

    _unique_id_suffix = "buzzer_manual_mute"
    _attribute_name = "buzzer_manual_mute"
    _attr_translation_key = "buzzer_manual_mute"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"}
)
class AqaraBuzzerManualAlarm(ConfigurableAttributeSwitch):
    """Representation of a buzzer manual mute configuration entity for Aqara smoke sensors."""

    _unique_id_suffix = "buzzer_manual_alarm"
    _attribute_name = "buzzer_manual_alarm"
    _attr_translation_key = "buzzer_manual_alarm"


@CONFIG_DIAGNOSTIC_MATCH(cluster_handler_names=CLUSTER_HANDLER_COVER)
class WindowCoveringInversionSwitch(ConfigurableAttributeSwitch):
    """Representation of a switch that controls inversion for window covering devices.

    This is necessary because this cluster uses 2 attributes to control inversion.
    """

    _unique_id_suffix = "inverted"
    _attribute_name = WindowCovering.AttributeDefs.config_status.name
    _attr_translation_key = "inverted"

    def _is_supported(self) -> bool:
        window_covering_mode_attr = (
            WindowCovering.AttributeDefs.window_covering_mode.name
        )

        # this entity needs a second attribute to function
        if (
            (
                window_covering_mode_attr
                in self._cluster_handler.cluster.unsupported_attributes
            )
            or (
                window_covering_mode_attr
                not in self._cluster_handler.cluster.attributes_by_name
            )
            or self._cluster_handler.cluster.get(window_covering_mode_attr) is None
        ):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                self._attribute_name,
                self.__class__.__name__,
            )
            return False

        return super()._is_supported()

    @property
    def is_on(self) -> bool:
        """Return if the switch is on based on the statemachine."""
        config_status = ConfigStatus(
            self._cluster_handler.cluster.get(self._attribute_name)
        )
        return ConfigStatus.Open_up_commands_reversed in config_status

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._async_on_off(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._async_on_off(False)

    async def async_update(self) -> None:
        """Attempt to retrieve the state of the entity."""
        self.debug("Polling current state")
        await self._cluster_handler.get_attributes(
            [
                self._attribute_name,
                WindowCovering.AttributeDefs.window_covering_mode.name,
            ],
            from_cache=False,
            only_cache=False,
        )
        self.maybe_emit_state_changed_event()

    async def _async_on_off(self, invert: bool) -> None:
        """Turn the entity on or off."""
        name: str = WindowCovering.AttributeDefs.window_covering_mode.name
        current_mode: WindowCoveringMode = WindowCoveringMode(
            self._cluster_handler.cluster.get(name)
        )
        send_command: bool = False
        if invert and WindowCoveringMode.Motor_direction_reversed not in current_mode:
            current_mode |= WindowCoveringMode.Motor_direction_reversed
            send_command = True
        elif not invert and WindowCoveringMode.Motor_direction_reversed in current_mode:
            current_mode &= ~WindowCoveringMode.Motor_direction_reversed
            send_command = True
        if send_command:
            await self._cluster_handler.write_attributes_safe({name: current_mode})
            await self.async_update()


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.curtain.agl001"}
)
class AqaraE1CurtainMotorHooksLockedSwitch(ConfigurableAttributeSwitch):
    """Representation of a switch that controls whether the curtain motor hooks are locked."""

    _unique_id_suffix = "hooks_lock"
    _attribute_name = "hooks_lock"
    _attr_translation_key = "hooks_locked"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossExternalOpenWindowDetected(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute for communicating an open window."""

    _unique_id_suffix = "external_open_window_detected"
    _attribute_name: str = "external_open_window_detected"
    _attr_translation_key: str = "external_window_sensor"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossWindowOpenFeature(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute enabling open window detection."""

    _unique_id_suffix = "window_open_feature"
    _attribute_name: str = "window_open_feature"
    _attr_translation_key: str = "use_internal_window_detection"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossMountingModeControl(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute for switching to mounting mode."""

    _unique_id_suffix = "mounting_mode_control"
    _attribute_name: str = "mounting_mode_control"
    _attr_translation_key: str = "mounting_mode"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossRadiatorCovered(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute for communicating full usage of the external temperature sensor."""

    _unique_id_suffix = "radiator_covered"
    _attribute_name: str = "radiator_covered"
    _attr_translation_key: str = "prioritize_external_temperature_sensor"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossHeatAvailable(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute for communicating available heat."""

    _unique_id_suffix = "heat_available"
    _attribute_name: str = "heat_available"
    _attr_translation_key: str = "heat_available"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossLoadBalancingEnable(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute for enabling load balancing."""

    _unique_id_suffix = "load_balancing_enable"
    _attribute_name: str = "load_balancing_enable"
    _attr_translation_key: str = "use_load_balancing"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names=CLUSTER_HANDLER_THERMOSTAT,
    quirk_ids={DANFOSS_ALLY_THERMOSTAT},
)
class DanfossAdaptationRunSettings(ConfigurableAttributeSwitch):
    """Danfoss proprietary attribute for enabling daily adaptation run.

    Actually a bitmap, but only the first bit is used.
    """

    _unique_id_suffix = "adaptation_run_settings"
    _attribute_name: str = "adaptation_run_settings"
    _attr_translation_key: str = "adaptation_run_enabled"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="sinope_manufacturer_specific",
    models={
        "DM2500ZB",
        "DM2500ZB-G2",
        "DM2550ZB",
        "DM2550ZB-G2",
    },
)
class SinopeLightDoubleTapFullSwitch(ConfigurableAttributeSwitch):
    """Representation of a config option that controls whether Double Tap Full option is enabled on a Sinope light switch."""

    _unique_id_suffix = "double_up_full"
    _attribute_name = "double_up_full"
    _attr_translation_key: str = "double_up_full"
