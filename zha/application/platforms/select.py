"""Support for ZHA controls using the select platform."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import functools
import logging
from typing import TYPE_CHECKING, Any, cast

from zigpy import types
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
    ReportingConfig,
)
from zigpy.zcl.clusters.general import LevelControl, OnOff
from zigpy.zcl.clusters.hvac import Thermostat, UserInterface
from zigpy.zcl.clusters.measurement import OccupancySensing
from zigpy.zcl.clusters.security import (
    IasWd,
    SirenLevel,
    Strobe,
    StrobeLevel,
    WarningMode,
)

from zha.application import Platform
from zha.application.helpers import write_attributes_safe
from zha.application.platforms import (
    AttrConfig,
    BaseEntity,
    BaseEntityInfo,
    ClusterConfig,
    ClusterMatch,
    EntityCategory,
    PlatformEntity,
    register_entity,
)
from zha.application.platforms.const import (
    INOVELLI_CLUSTER,
    SINOPE_MANUFACTURER_CLUSTER,
    TUYA_MANUFACTURER_CLUSTER,
)
from zha.application.platforms.legacy_quirks import (
    AQARA_OPPLE_CLUSTER,
    DanfossAdaptationRunControlEnum,
    DanfossExerciseDayOfTheWeekEnum,
    DanfossViewingDirectionEnum,
    MagnetAC01OppleCluster,
    T2RelayOppleCluster,
)
from zha.application.platforms.siren import AdvancedSiren
from zha.quirks import (
    BEGA_LIGHT_SWITCHABLE_WHITE,
    DANFOSS_ALLY_THERMOSTAT,
    SIREN_BASIC,
    TUYA_PLUG_MANUFACTURER,
    TUYA_PLUG_ONOFF,
)

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class EnumSelectInfo(BaseEntityInfo):
    """Enum select entity info."""

    enum: str
    options: list[str]


class BaseSelectEntity(BaseEntity, ABC):
    """Abstract base class for select entities (platform-agnostic)."""

    PLATFORM = Platform.SELECT

    _attr_options: list[str]

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        return self._attr_options

    @property
    def state(self) -> dict[str, Any]:
        """Return the state of the select."""
        response = super().state
        response["state"] = self.current_option
        return response

    @property
    @abstractmethod
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""

    @abstractmethod
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""


class SirenDefaultSelectEntity(BaseSelectEntity, PlatformEntity):
    """Select entity whose state lives on the AdvancedSiren on the same cluster."""

    _attr_entity_category = EntityCategory.CONFIG
    _enum: type[Enum]
    # Subclasses can override to pin specific option strings (e.g. to preserve
    # legacy display names that differ from zigpy's enum member names).
    _option_overrides: dict[str, Enum] | None = None

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this select entity."""
        if self._option_overrides is not None:
            self._option_to_member: dict[str, Enum] = self._option_overrides
        else:
            self._option_to_member = {
                entry.name.replace("_", " "): entry for entry in self._enum
            }
        self._member_to_option = {m: o for o, m in self._option_to_member.items()}
        self._attr_options = list(self._option_to_member)
        super().__init__(endpoint=endpoint, device=device, **kwargs)

    @functools.cached_property
    def info_object(self) -> EnumSelectInfo:
        """Return a representation of the select."""
        return EnumSelectInfo(
            **super().info_object.__dict__,
            enum=self._enum.__name__,
            options=self.options,
        )

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return True

    def _siren(self) -> AdvancedSiren:
        return cast(
            AdvancedSiren,
            self._device.get_entity(
                Platform.SIREN,
                endpoint_id=self._endpoint.id,
                cluster_id=IasWd.cluster_id,
            ),
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        value = self._siren().defaults[self._enum]
        if value is None:
            return None
        return self._member_to_option[value]

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._siren().defaults[self._enum] = self._option_to_member[option]
        self.maybe_emit_state_changed_event()

    def restore_external_state_attributes(
        self,
        *,
        state: str,
    ) -> None:
        """Restore extra state attributes that are stored outside of the ZCL cache."""
        self._siren().defaults[self._enum] = self._option_to_member[state]


@register_entity(IasWd.cluster_id)
class DefaultToneSelectEntity(SirenDefaultSelectEntity):
    """Representation of a ZHA default siren tone select entity."""

    _unique_id_suffix = "WarningMode"
    _enum = WarningMode
    _attr_translation_key: str = "default_siren_tone"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
        not_exposed_features=frozenset({SIREN_BASIC}),
    )


@register_entity(IasWd.cluster_id)
class DefaultSirenLevelSelectEntity(SirenDefaultSelectEntity):
    """Representation of a ZHA default siren level select entity."""

    _unique_id_suffix = "SirenLevel"
    _enum = SirenLevel
    _attr_translation_key: str = "default_siren_level"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
        not_exposed_features=frozenset({SIREN_BASIC}),
    )


@register_entity(IasWd.cluster_id)
class DefaultStrobeLevelSelectEntity(SirenDefaultSelectEntity):
    """Representation of a ZHA default siren strobe level select entity."""

    _unique_id_suffix = "StrobeLevel"
    _enum = StrobeLevel
    _attr_translation_key: str = "default_strobe_level"

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
        not_exposed_features=frozenset({SIREN_BASIC}),
    )


@register_entity(IasWd.cluster_id)
class DefaultStrobeSelectEntity(SirenDefaultSelectEntity):
    """Representation of a ZHA default siren strobe select entity."""

    _unique_id_suffix = "Strobe"
    _enum = Strobe
    _attr_translation_key: str = "default_strobe"

    # Backwards-compat: this entity previously used a zha-local `Strobe` enum
    # with members `No_Strobe`/`Strobe` displayed as "No Strobe"/"Strobe".
    # zigpy's enum uses `No_strobe`, which would otherwise change the display
    # to "No strobe". Pin the option strings here.
    _option_overrides = {"No Strobe": Strobe.No_strobe, "Strobe": Strobe.Strobe}

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
        not_exposed_features=frozenset({SIREN_BASIC}),
    )


class ZCLEnumSelectEntity(BaseSelectEntity, PlatformEntity):
    """Representation of a ZHA ZCL enum select entity."""

    _attribute_name: str
    _attr_entity_category = EntityCategory.CONFIG
    _enum: type[Enum]

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        attribute_name: str | None = None,
        enum: type[Enum] | None = None,
        **kwargs: Any,
    ) -> None:
        """Init this select entity."""
        if attribute_name is not None:
            self._attribute_name = attribute_name
        if enum is not None:
            self._enum = enum

        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._attr_options = [entry.name.replace("_", " ") for entry in self._enum]

    def on_add(self) -> None:
        """Run when entity is added."""
        super().on_add()
        for event_type in (
            AttributeReadEvent,
            AttributeReportedEvent,
            AttributeUpdatedEvent,
            AttributeWrittenEvent,
        ):
            self._on_remove_callbacks.append(
                self._cluster.on_event(
                    event_type.event_type, self.handle_attribute_updated
                )
            )

    def _is_supported(self) -> bool:
        if (
            self._attribute_name not in self._cluster.attributes_by_name
            or self._cluster.is_attribute_unsupported(self._attribute_name)
            or self._cluster.get(self._attribute_name) is None
        ):
            _LOGGER.debug(
                "%s is not supported - skipping %s entity creation",
                self._attribute_name,
                self.__class__.__name__,
            )
            return False

        return super()._is_supported()

    @functools.cached_property
    def info_object(self) -> EnumSelectInfo:
        """Return a representation of the select."""
        return EnumSelectInfo(
            **super().info_object.__dict__,
            enum=self._enum.__name__,
            options=self.options,
        )

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        option = self._cluster.get(self._attribute_name)
        if option is None:
            return None
        option = self._enum(option)
        return option.name.replace("_", " ")

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await write_attributes_safe(
            self._cluster,
            {self._attribute_name: self._enum[option.replace(" ", "_")]},
        )
        self.maybe_emit_state_changed_event()

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle value update from cluster."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    def restore_external_state_attributes(
        self,
        *,
        state: str,
    ) -> None:
        """Restore extra state attributes."""
        # Select entities backed by the ZCL cache don't need to restore their state!


@register_entity(OnOff.cluster_id)
class StartupOnOffSelectEntity(ZCLEnumSelectEntity):
    """Representation of a ZHA startup onoff select entity."""

    _unique_id_suffix = "StartUpOnOff"
    _attribute_name = "start_up_on_off"
    _enum = OnOff.StartUpOnOff
    _attr_translation_key: str = "start_up_on_off"
    _cluster_id = OnOff.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OnOff.cluster_id}),
    )

    _server_cluster_config = {
        OnOff.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                OnOff.AttributeDefs.on_off: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                OnOff.AttributeDefs.start_up_on_off: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


class TuyaPowerOnState(types.enum8):
    """Tuya power on state enum."""

    Off = 0x00
    On = 0x01
    LastState = 0x02


@register_entity(OnOff.cluster_id)
class TuyaPowerOnStateSelectEntity(ZCLEnumSelectEntity):
    """Representation of a ZHA power on state select entity."""

    _unique_id_suffix = "power_on_state"
    _attribute_name = "power_on_state"
    _enum = TuyaPowerOnState
    _attr_translation_key: str = "power_on_state"
    _cluster_id = OnOff.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OnOff.cluster_id}),
        exposed_features=frozenset({TUYA_PLUG_ONOFF}),
    )

    _server_cluster_config = {
        OnOff.cluster_id: ClusterConfig(
            attributes={
                "power_on_state": AttrConfig(read_on_startup=False),
            },
        ),
    }


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class TuyaManufacturerPowerOnStateSelectEntity(ZCLEnumSelectEntity):
    """Representation of a ZHA power on state select entity."""

    _unique_id_suffix = "power_on_state"
    _attribute_name = "power_on_state"
    _enum = TuyaPowerOnState
    _attr_translation_key: str = "power_on_state"
    _cluster_id = TUYA_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
        exposed_features=frozenset({TUYA_PLUG_MANUFACTURER}),
    )


class TuyaBacklightMode(types.enum8):
    """Tuya switch backlight mode enum."""

    Off = 0x00
    LightWhenOn = 0x01
    LightWhenOff = 0x02


@register_entity(OnOff.cluster_id)
class TuyaBacklightModeSelectEntity(ZCLEnumSelectEntity):
    """Representation of a ZHA backlight mode select entity."""

    _unique_id_suffix = "backlight_mode"
    _attribute_name = "backlight_mode"
    _enum = TuyaBacklightMode
    _attr_translation_key: str = "backlight_mode"
    _cluster_id = OnOff.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OnOff.cluster_id}),
        exposed_features=frozenset({TUYA_PLUG_ONOFF}),
    )

    _server_cluster_config = {
        OnOff.cluster_id: ClusterConfig(
            attributes={
                "backlight_mode": AttrConfig(read_on_startup=False),
            },
        ),
    }


class MoesBacklightMode(types.enum8):
    """MOES switch backlight mode enum."""

    Off = 0x00
    LightWhenOn = 0x01
    LightWhenOff = 0x02
    Freeze = 0x03


@register_entity(TUYA_MANUFACTURER_CLUSTER)
class MoesBacklightModeSelectEntity(ZCLEnumSelectEntity):
    """Moes devices have a different backlight mode select options."""

    _unique_id_suffix = "backlight_mode"
    _attribute_name = "backlight_mode"
    _enum = MoesBacklightMode
    _attr_translation_key: str = "backlight_mode"
    _cluster_id = TUYA_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({TUYA_MANUFACTURER_CLUSTER}),
        exposed_features=frozenset({TUYA_PLUG_MANUFACTURER}),
    )


class AqaraMotionSensitivities(types.enum8):
    """Aqara motion sensitivities."""

    Low = 0x01
    Medium = 0x02
    High = 0x03


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMotionSensitivity(ZCLEnumSelectEntity):
    """Representation of a ZHA motion sensitivity configuration entity."""

    _unique_id_suffix = "motion_sensitivity"
    _attribute_name = "motion_sensitivity"
    _enum = AqaraMotionSensitivities
    _attr_translation_key: str = "motion_sensitivity"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac01", "lumi.motion.ac02", "lumi.motion.agl04"}),
    )


class HueV1MotionSensitivities(types.enum8):
    """Hue v1 motion sensitivities."""

    Low = 0x00
    Medium = 0x01
    High = 0x02


@register_entity(OccupancySensing.cluster_id)
class HueV1MotionSensitivity(ZCLEnumSelectEntity):
    """Representation of a ZHA motion sensitivity configuration entity."""

    _unique_id_suffix = "motion_sensitivity"
    _attribute_name = "sensitivity"
    _enum = HueV1MotionSensitivities
    _attr_translation_key: str = "motion_sensitivity"
    _cluster_id = OccupancySensing.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OccupancySensing.cluster_id}),
        manufacturers=frozenset({"Philips", "Signify Netherlands B.V."}),
        models=frozenset({"SML001"}),
    )

    _server_cluster_config = {
        OccupancySensing.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                OccupancySensing.AttributeDefs.occupancy: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=0, max_interval=900, reportable_change=1
                    ),
                ),
                OccupancySensing.AttributeDefs.pir_o_to_u_delay: AttrConfig(
                    read_on_startup=False,
                ),
                OccupancySensing.AttributeDefs.pir_u_to_o_delay: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


class HueV2MotionSensitivities(types.enum8):
    """Hue v2 motion sensitivities."""

    Lowest = 0x00
    Low = 0x01
    Medium = 0x02
    High = 0x03
    Highest = 0x04


@register_entity(OccupancySensing.cluster_id)
class HueV2MotionSensitivity(ZCLEnumSelectEntity):
    """Representation of a ZHA motion sensitivity configuration entity."""

    _unique_id_suffix = "motion_sensitivity"
    _attribute_name = "sensitivity"
    _enum = HueV2MotionSensitivities
    _attr_translation_key: str = "motion_sensitivity"
    _cluster_id = OccupancySensing.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OccupancySensing.cluster_id}),
        manufacturers=frozenset({"Philips", "Signify Netherlands B.V."}),
        models=frozenset({"SML002", "SML003", "SML004"}),
    )


class AqaraMonitoringModess(types.enum8):
    """Aqara monitoring modes."""

    Undirected = 0x00
    Left_Right = 0x01


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraMonitoringMode(ZCLEnumSelectEntity):
    """Representation of a ZHA monitoring mode configuration entity."""

    _unique_id_suffix = "monitoring_mode"
    _attribute_name = "monitoring_mode"
    _enum = AqaraMonitoringModess
    _attr_translation_key: str = "monitoring_mode"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac01"}),
    )


class AqaraApproachDistances(types.enum8):
    """Aqara approach distances."""

    Far = 0x00
    Medium = 0x01
    Near = 0x02


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraApproachDistance(ZCLEnumSelectEntity):
    """Representation of a ZHA approach distance configuration entity."""

    _unique_id_suffix = "approach_distance"
    _attribute_name = "approach_distance"
    _enum = AqaraApproachDistances
    _attr_translation_key: str = "approach_distance"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.motion.ac01"}),
    )


@register_entity(MagnetAC01OppleCluster.cluster_id)
class AqaraMagnetAC01DetectionDistance(ZCLEnumSelectEntity):
    """Representation of a ZHA detection distance configuration entity."""

    _unique_id_suffix = "detection_distance"
    _attribute_name = "detection_distance"
    _enum = MagnetAC01OppleCluster.DetectionDistance
    _attr_translation_key: str = "detection_distance"
    _cluster_id = MagnetAC01OppleCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({MagnetAC01OppleCluster.cluster_id}),
        models=frozenset({"lumi.magnet.ac01"}),
    )


@register_entity(T2RelayOppleCluster.cluster_id)
class AqaraT2RelaySwitchMode(ZCLEnumSelectEntity):
    """Representation of a ZHA switch mode configuration entity."""

    _unique_id_suffix = "switch_mode"
    _attribute_name = "switch_mode"
    _enum = T2RelayOppleCluster.SwitchMode
    _attr_translation_key: str = "switch_mode"
    _cluster_id = T2RelayOppleCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({T2RelayOppleCluster.cluster_id}),
        models=frozenset({"lumi.switch.acn047"}),
    )


@register_entity(T2RelayOppleCluster.cluster_id)
class AqaraT2RelaySwitchType(ZCLEnumSelectEntity):
    """Representation of a ZHA switch type configuration entity."""

    _unique_id_suffix = "switch_type"
    _attribute_name = "switch_type"
    _enum = T2RelayOppleCluster.SwitchType
    _attr_translation_key: str = "switch_type"
    _cluster_id = T2RelayOppleCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({T2RelayOppleCluster.cluster_id}),
        models=frozenset({"lumi.switch.acn047"}),
    )


@register_entity(T2RelayOppleCluster.cluster_id)
class AqaraT2RelayStartupOnOff(ZCLEnumSelectEntity):
    """Representation of a ZHA startup on off configuration entity."""

    _unique_id_suffix = "startup_on_off"
    _attribute_name = "startup_on_off"
    _enum = T2RelayOppleCluster.StartupOnOff
    _attr_translation_key: str = "start_up_on_off"
    _cluster_id = T2RelayOppleCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({T2RelayOppleCluster.cluster_id}),
        models=frozenset({"lumi.switch.acn047"}),
    )


@register_entity(T2RelayOppleCluster.cluster_id)
class AqaraT2RelayDecoupledMode(ZCLEnumSelectEntity):
    """Representation of a ZHA switch decoupled mode configuration entity."""

    _unique_id_suffix = "decoupled_mode"
    _attribute_name = "decoupled_mode"
    _enum = T2RelayOppleCluster.DecoupledMode
    _attr_translation_key: str = "decoupled_mode"
    _cluster_id = T2RelayOppleCluster.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({T2RelayOppleCluster.cluster_id}),
        models=frozenset({"lumi.switch.acn047"}),
    )


class InovelliOutputMode(types.enum1):
    """Inovelli output mode."""

    Dimmer = 0x00
    OnOff = 0x01


@register_entity(INOVELLI_CLUSTER)
class InovelliOutputModeEntity(ZCLEnumSelectEntity):
    """Inovelli output mode control."""

    _unique_id_suffix = "output_mode"
    _attribute_name = "output_mode"
    _enum = InovelliOutputMode
    _attr_translation_key: str = "output_mode"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


class InovelliSwitchType(types.enum8):
    """Inovelli switch mode."""

    Single_Pole = 0x00
    Three_Way_Dumb = 0x01
    Three_Way_AUX = 0x02
    Single_Pole_Full_Sine = 0x03


@register_entity(INOVELLI_CLUSTER)
class InovelliSwitchTypeEntity(ZCLEnumSelectEntity):
    """Inovelli switch type control."""

    _unique_id_suffix = "switch_type"
    _attribute_name = "switch_type"
    _enum = InovelliSwitchType
    _attr_translation_key: str = "switch_type"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM31-SN"}),
    )


class InovelliFanSwitchType(types.enum1):
    """Inovelli fan switch mode."""

    Load_Only = 0x00
    Three_Way_AUX = 0x01


@register_entity(INOVELLI_CLUSTER)
class InovelliFanSwitchTypeEntity(ZCLEnumSelectEntity):
    """Inovelli fan switch type control."""

    _unique_id_suffix = "switch_type"
    _attribute_name = "switch_type"
    _enum = InovelliFanSwitchType
    _attr_translation_key: str = "switch_type"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM35-SN"}),
    )


class InovelliLedScalingMode(types.enum1):
    """Inovelli led mode."""

    VZM31SN = 0x00
    LZW31SN = 0x01


@register_entity(INOVELLI_CLUSTER)
class InovelliLedScalingModeEntity(ZCLEnumSelectEntity):
    """Inovelli led mode control."""

    _unique_id_suffix = "led_scaling_mode"
    _attribute_name = "led_scaling_mode"
    _enum = InovelliLedScalingMode
    _attr_translation_key: str = "led_scaling_mode"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


class InovelliFanLedScalingMode(types.enum8):
    """Inovelli fan led mode."""

    VZM31SN = 0x00
    Grade_1 = 0x01
    Grade_2 = 0x02
    Grade_3 = 0x03
    Grade_4 = 0x04
    Grade_5 = 0x05
    Grade_6 = 0x06
    Grade_7 = 0x07
    Grade_8 = 0x08
    Grade_9 = 0x09
    Adaptive = 0x0A


@register_entity(INOVELLI_CLUSTER)
class InovelliFanLedScalingModeEntity(ZCLEnumSelectEntity):
    """Inovelli fan switch led mode control."""

    _unique_id_suffix = "smart_fan_led_display_levels"
    _attribute_name = "smart_fan_led_display_levels"
    _enum = InovelliFanLedScalingMode
    _attr_translation_key: str = "smart_fan_led_display_levels"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM35-SN"}),
    )


class InovelliNonNeutralOutput(types.enum1):
    """Inovelli non neutral output selection."""

    Low = 0x00
    High = 0x01


@register_entity(INOVELLI_CLUSTER)
class InovelliNonNeutralOutputEntity(ZCLEnumSelectEntity):
    """Inovelli non neutral output control."""

    _unique_id_suffix = "increased_non_neutral_output"
    _attribute_name = "increased_non_neutral_output"
    _enum = InovelliNonNeutralOutput
    _attr_translation_key: str = "increased_non_neutral_output"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
    )


class InovelliDimmingMode(types.enum1):
    """Inovelli dimming mode selection."""

    LeadingEdge = 0x00
    TrailingEdge = 0x01


@register_entity(INOVELLI_CLUSTER)
class InovelliDimmingModeEntity(ZCLEnumSelectEntity):
    """Inovelli dimming mode control."""

    _unique_id_suffix = "leading_or_trailing_edge"
    _attribute_name = "leading_or_trailing_edge"
    _enum = InovelliDimmingMode
    _attr_translation_key: str = "leading_or_trailing_edge"
    _cluster_id = INOVELLI_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({INOVELLI_CLUSTER}),
        models=frozenset({"VZM31-SN", "VZM36"}),
    )


class AqaraFeedingMode(types.enum8):
    """Feeding mode."""

    Manual = 0x00
    Schedule = 0x01


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraPetFeederMode(ZCLEnumSelectEntity):
    """Representation of an Aqara pet feeder mode configuration entity."""

    _unique_id_suffix = "feeding_mode"
    _attribute_name = "feeding_mode"
    _enum = AqaraFeedingMode
    _attr_translation_key: str = "feeding_mode"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"aqara.feeder.acn001"}),
    )


class AqaraThermostatPresetMode(types.enum8):
    """Thermostat preset mode."""

    Manual = 0x00
    Auto = 0x01
    Away = 0x02


@register_entity(AQARA_OPPLE_CLUSTER)
class AqaraThermostatPreset(ZCLEnumSelectEntity):
    """Representation of an Aqara thermostat preset configuration entity."""

    _unique_id_suffix = "preset"
    _attribute_name = "preset"
    _enum = AqaraThermostatPresetMode
    _attr_translation_key: str = "preset"
    _cluster_id = AQARA_OPPLE_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({AQARA_OPPLE_CLUSTER}),
        models=frozenset({"lumi.airrtc.agl001"}),
    )


class SonoffPresenceDetectionSensitivityEnum(types.enum8):
    """Enum for detection sensitivity select entity."""

    Low = 0x01
    Medium = 0x02
    High = 0x03


@register_entity(OccupancySensing.cluster_id)
class SonoffPresenceDetectionSensitivity(ZCLEnumSelectEntity):
    """Entity to set the detection sensitivity of the Sonoff SNZB-06P."""

    _unique_id_suffix = "detection_sensitivity"
    _attribute_name = "ultrasonic_u_to_o_threshold"
    _enum = SonoffPresenceDetectionSensitivityEnum
    _attr_translation_key: str = "detection_sensitivity"
    _cluster_id = OccupancySensing.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({OccupancySensing.cluster_id}),
        models=frozenset({"SNZB-06P", "SNZB-03P"}),
    )


class KeypadLockoutEnum(types.enum8):
    """Keypad lockout options."""

    Unlock = 0x00
    Lock1 = 0x01
    Lock2 = 0x02
    Lock3 = 0x03
    Lock4 = 0x04


@register_entity(UserInterface.cluster_id)
class KeypadLockout(ZCLEnumSelectEntity):
    """Mandatory attribute for thermostat_ui cluster.

    Often only the first two are implemented, and Lock2 to Lock4 should map to Lock1 in the firmware.
    This however covers all bases.
    """

    _unique_id_suffix = "keypad_lockout"
    _attribute_name: str = "keypad_lockout"
    _enum = KeypadLockoutEnum
    _attr_translation_key: str = "keypad_lockout"
    _cluster_id = UserInterface.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({UserInterface.cluster_id}),
    )

    _server_cluster_config = {
        UserInterface.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                UserInterface.AttributeDefs.keypad_lockout: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


@register_entity(Thermostat.cluster_id)
class DanfossExerciseDayOfTheWeek(ZCLEnumSelectEntity):
    """Danfoss proprietary attribute for setting the day of the week for exercising."""

    _unique_id_suffix = "exercise_day_of_week"
    _attribute_name = "exercise_day_of_week"
    _attr_translation_key: str = "exercise_day_of_week"
    _enum = DanfossExerciseDayOfTheWeekEnum
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        Thermostat.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                Thermostat.AttributeDefs.local_temperature: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.occupied_cooling_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.occupied_heating_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.unoccupied_cooling_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.unoccupied_heating_setpoint: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=25
                    ),
                ),
                Thermostat.AttributeDefs.running_mode: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.running_state: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.system_mode: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.occupancy: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=1
                    ),
                ),
                Thermostat.AttributeDefs.pi_cooling_demand: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=5
                    ),
                ),
                Thermostat.AttributeDefs.pi_heating_demand: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=30, max_interval=900, reportable_change=5
                    ),
                ),
                Thermostat.AttributeDefs.abs_min_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.abs_max_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.abs_min_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.abs_max_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.ctrl_sequence_of_oper: AttrConfig(
                    read_on_startup=True,
                ),
                Thermostat.AttributeDefs.max_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.max_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.min_cool_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.min_heat_setpoint_limit: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.local_temperature_calibration: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.setpoint_change_source: AttrConfig(
                    read_on_startup=False,
                ),
                Thermostat.AttributeDefs.setpoint_change_source_timestamp: AttrConfig(
                    read_on_startup=False,
                ),
            },
        ),
    }


class DanfossOrientationEnum(types.enum8):
    """Vertical or Horizontal."""

    Horizontal = 0x00
    Vertical = 0x01


@register_entity(Thermostat.cluster_id)
class DanfossOrientation(ZCLEnumSelectEntity):
    """Danfoss proprietary attribute for setting the orientation of the valve.

    Needed for biasing the internal temperature sensor.
    This is implemented as an enum here, but is a boolean on the device.
    """

    _unique_id_suffix = "orientation"
    _attribute_name = "orientation"
    _attr_translation_key: str = "valve_orientation"
    _enum = DanfossOrientationEnum
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )


@register_entity(Thermostat.cluster_id)
class DanfossAdaptationRunControl(ZCLEnumSelectEntity):
    """Danfoss proprietary attribute for controlling the current adaptation run."""

    _unique_id_suffix = "adaptation_run_control"
    _attribute_name = "adaptation_run_control"
    _attr_translation_key: str = "adaptation_run_command"
    _enum = DanfossAdaptationRunControlEnum
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )


class DanfossControlAlgorithmScaleFactorEnum(types.enum8):
    """The time scale factor for changing the opening of the valve.

    Not all values are given, therefore there are some extrapolated values with a margin of error of about 5 minutes.
    This is implemented as an enum here, but is a number on the device.
    """

    quick_5min = 0x01

    quick_10min = 0x02  # extrapolated
    quick_15min = 0x03  # extrapolated
    quick_25min = 0x04  # extrapolated

    moderate_30min = 0x05

    moderate_40min = 0x06  # extrapolated
    moderate_50min = 0x07  # extrapolated
    moderate_60min = 0x08  # extrapolated
    moderate_70min = 0x09  # extrapolated

    slow_80min = 0x0A

    quick_open_disabled = 0x11  # not sure what it does; also requires lower 4 bits to be in [1, 10] I assume


@register_entity(Thermostat.cluster_id)
class DanfossControlAlgorithmScaleFactor(ZCLEnumSelectEntity):
    """Danfoss proprietary attribute for setting the scale factor of the setpoint filter time constant."""

    _unique_id_suffix = "control_algorithm_scale_factor"
    _attribute_name = "control_algorithm_scale_factor"
    _attr_translation_key: str = "setpoint_response_time"
    _enum = DanfossControlAlgorithmScaleFactorEnum
    _cluster_id = Thermostat.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({Thermostat.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )


@register_entity(UserInterface.cluster_id)
class DanfossViewingDirection(ZCLEnumSelectEntity):
    """Danfoss proprietary attribute for setting the viewing direction of the screen."""

    _unique_id_suffix = "viewing_direction"
    _attribute_name = "viewing_direction"
    _attr_translation_key: str = "viewing_direction"
    _enum = DanfossViewingDirectionEnum
    _cluster_id = UserInterface.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({UserInterface.cluster_id}),
        exposed_features=frozenset({DANFOSS_ALLY_THERMOSTAT}),
    )

    _server_cluster_config = {
        UserInterface.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                "viewing_direction": AttrConfig(read_on_startup=True),
            },
        ),
    }


class SinopeLightLedColors(types.enum32):
    """Color values for Sinope light switch status LEDs."""

    Lim = 0x0AFFDC
    Amber = 0x000A4B
    Fushia = 0x0100A5
    Perle = 0x64FFFF
    Blue = 0xFFFF00


SINOPE_MODELS = frozenset(
    {
        "DM2500ZB",
        "DM2500ZB-G2",
        "DM2550ZB",
        "DM2550ZB-G2",
        "SW2500ZB",
        "SW2500ZB-G2",
    }
)


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeLightLEDOffColorSelect(ZCLEnumSelectEntity):
    """Representation of the marker LED Off-state color of Sinope light switches."""

    _unique_id_suffix = "off_led_color"
    _attribute_name = "off_led_color"
    _attr_translation_key: str = "off_led_color"
    _enum = SinopeLightLedColors
    _cluster_id = SINOPE_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=SINOPE_MODELS,
    )


@register_entity(SINOPE_MANUFACTURER_CLUSTER)
class SinopeLightLEDOnColorSelect(ZCLEnumSelectEntity):
    """Representation of the marker LED On-state color of Sinope light switches."""

    _unique_id_suffix = "on_led_color"
    _attribute_name = "on_led_color"
    _attr_translation_key: str = "on_led_color"
    _enum = SinopeLightLedColors
    _cluster_id = SINOPE_MANUFACTURER_CLUSTER

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({SINOPE_MANUFACTURER_CLUSTER}),
        models=SINOPE_MODELS,
    )


class BegaColorTemperatureChannel(types.enum8):
    """BEGA switchable white color temperature channel enum."""

    Warm_white = 0x00
    Cool_white = 0x01


@register_entity(LevelControl.cluster_id)
class BegaColorTemperatureChannelSelect(ZCLEnumSelectEntity):
    """Select entity for switching BEGA light color temperature channel."""

    _unique_id_suffix = "switchable_white"
    _attribute_name = "switchable_white"
    _enum = BegaColorTemperatureChannel
    _attr_translation_key: str = "color_temperature_channel"
    _cluster_id = LevelControl.cluster_id

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({LevelControl.cluster_id}),
        exposed_features=frozenset({BEGA_LIGHT_SWITCHABLE_WHITE}),
    )

    _server_cluster_config = {
        LevelControl.cluster_id: ClusterConfig(
            bind=True,
            attributes={
                LevelControl.AttributeDefs.current_level: AttrConfig(
                    read_on_startup=True,
                    reporting=ReportingConfig(
                        min_interval=1, max_interval=900, reportable_change=1
                    ),
                ),
                LevelControl.AttributeDefs.on_off_transition_time: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.on_level: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.on_transition_time: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.off_transition_time: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.default_move_rate: AttrConfig(
                    read_on_startup=False,
                ),
                LevelControl.AttributeDefs.start_up_current_level: AttrConfig(
                    read_on_startup=False,
                ),
                "switchable_white": AttrConfig(read_on_startup=False),
                "switchable_color_temperature_1": AttrConfig(read_on_startup=False),
                "switchable_color_temperature_2": AttrConfig(read_on_startup=False),
            },
        ),
    }

    def _is_supported(self) -> bool:
        """Check if the light supports switchable color temperatures."""
        temp_1 = self._cluster.get("switchable_color_temperature_1")
        temp_2 = self._cluster.get("switchable_color_temperature_2")

        if temp_1 == 0xFFFF or temp_2 == 0xFFFF:
            _LOGGER.debug(
                "A color temperature is 0xFFFF (unsupported) - "
                "skipping %s entity creation",
                self.__class__.__name__,
            )
            return False

        return super()._is_supported()
