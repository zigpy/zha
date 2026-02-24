"""Support for ZHA sirens."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum, IntFlag
import functools
from typing import TYPE_CHECKING, Any, Final, cast

from zigpy.profiles import zha
from zigpy.quirks.v2 import SwitchMetadata, ZCLEnumMetadata
from zigpy.zcl.clusters.security import IasWd

from zha.application import Platform
from zha.application.const import (
    WARNING_DEVICE_MODE_BURGLAR,
    WARNING_DEVICE_MODE_EMERGENCY,
    WARNING_DEVICE_MODE_EMERGENCY_PANIC,
    WARNING_DEVICE_MODE_FIRE,
    WARNING_DEVICE_MODE_FIRE_PANIC,
    WARNING_DEVICE_MODE_POLICE_PANIC,
    WARNING_DEVICE_MODE_STOP,
    WARNING_DEVICE_SOUND_HIGH,
    WARNING_DEVICE_STROBE_HIGH,
    WARNING_DEVICE_STROBE_NO,
    Strobe,
)
from zha.application.platforms import (
    BaseEntityInfo,
    ClusterHandlerMatch,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)
from zha.zigbee.cluster_handlers import ClusterAttributeUpdatedEvent
from zha.zigbee.cluster_handlers.const import (
    CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
    CLUSTER_HANDLER_IAS_WD,
)
from zha.zigbee.cluster_handlers.security import IasWdClusterHandler

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

DEFAULT_DURATION = 5  # seconds

ATTR_AVAILABLE_TONES: Final[str] = "available_tones"
ATTR_DURATION: Final[str] = "duration"
ATTR_VOLUME_LEVEL: Final[str] = "volume_level"
ATTR_TONE: Final[str] = "tone"


class SirenEntityFeature(IntFlag):
    """Supported features of the siren entity."""

    TURN_ON = 1
    TURN_OFF = 2
    TONES = 4
    VOLUME_SET = 8
    DURATION = 16


@dataclass(frozen=True, kw_only=True)
class SirenEntityInfo(BaseEntityInfo):
    """Siren entity info."""

    available_tones: dict[int, str]
    supported_features: SirenEntityFeature


class BaseSiren(PlatformEntity, ABC):
    """Abstract base class for ZHA siren entities."""

    PLATFORM = Platform.SIREN

    _attr_is_on: bool = False
    _attr_available_tones: dict[int, str]
    _attr_supported_features: SirenEntityFeature

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the siren."""
        response = super().state
        response["state"] = self.is_on
        return response

    @property
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return self._attr_is_on

    @property
    def available_tones(self) -> dict[int, str]:
        """Return available tones."""
        return self._attr_available_tones

    @property
    def supported_features(self) -> SirenEntityFeature:
        """Return supported features."""
        return self._attr_supported_features

    @functools.cached_property
    def info_object(self) -> SirenEntityInfo:
        """Return representation of the siren."""
        return SirenEntityInfo(
            **super().info_object.__dict__,
            available_tones=self.available_tones,
            supported_features=self.supported_features,
        )

    @abstractmethod
    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
    ) -> None:
        """Turn on siren."""

    @abstractmethod
    async def async_turn_off(self) -> None:
        """Turn off siren."""


class BaseZclSiren(BaseSiren, ABC):
    """Base class for ZHA IAS WD siren entities with shared ZCL logic."""

    _cluster_handler: IasWdClusterHandler
    _off_listener: asyncio.TimerHandle | None

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init ZCL siren base."""
        self._cluster_handler = cast(IasWdClusterHandler, cluster_handlers[0])
        self._off_listener = None
        super().__init__(cluster_handlers, endpoint, device, **kwargs)

    async def async_turn_off(self) -> None:
        """Turn off siren."""
        await self._cluster_handler.issue_start_warning(
            mode=WARNING_DEVICE_MODE_STOP, strobe=WARNING_DEVICE_STROBE_NO
        )
        self._attr_is_on = False
        self.maybe_emit_state_changed_event()

    def _async_set_off(self) -> None:
        """Set is_on to False and write HA state."""
        self._attr_is_on = False
        if self._off_listener:
            self._off_listener.cancel()

            with contextlib.suppress(ValueError):
                self._tracked_handles.remove(self._off_listener)

            self._off_listener = None
        self.maybe_emit_state_changed_event()


class ConfigurableAttributeSiren(BaseSiren):
    """Siren entity backed by a ZCL attribute, created from quirks v2 SwitchMetadata."""

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
        """Init this configurable attribute siren."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF
        )
        self._attr_available_tones: dict[int, str] = {}
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

    @property
    def inverted(self) -> bool:
        """Return True if the siren is inverted."""
        if self._inverter_attribute_name:
            return bool(
                self._cluster_handler.cluster.get(self._inverter_attribute_name)
            )
        return self._force_inverted

    @property
    def is_on(self) -> bool:
        """Return if the siren is on based on the cluster attribute."""
        if self._on_value != 1:
            val = self._cluster_handler.cluster.get(self._attribute_name)
            val = val == self._on_value
        else:
            val = bool(self._cluster_handler.cluster.get(self._attribute_name))
        return (not val) if self.inverted else val

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,
    ) -> None:
        """Handle state update from cluster handler."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
    ) -> None:
        """Turn on siren."""
        await self._cluster_handler.write_attributes_safe(
            {
                self._attribute_name: self._on_value
                if not self.inverted
                else self._off_value
            }
        )
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self) -> None:
        """Turn off siren."""
        await self._cluster_handler.write_attributes_safe(
            {
                self._attribute_name: self._off_value
                if not self.inverted
                else self._on_value
            }
        )
        self.maybe_emit_state_changed_event()

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


class EnumSiren(BaseSiren):
    """Siren entity backed by a ZCL enum attribute, created from quirks v2 ZCLEnumMetadata.

    Entry 0 of the enum is the off state.
    Entry 1 is the default tone used when no specific tone is requested.
    All remaining entries are exposed as additional tones.
    """

    _attribute_name: str
    _enum: type[Enum]

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this enum siren."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        self._attr_available_tones: dict[int, str] = {}
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON
            | SirenEntityFeature.TURN_OFF
            | SirenEntityFeature.TONES
        )
        self._cluster_handler.on_event(
            CLUSTER_HANDLER_ATTRIBUTE_UPDATED,
            self.handle_cluster_handler_attribute_updated,
        )

    def _init_from_quirks_metadata(self, entity_metadata: ZCLEnumMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        self._attribute_name = entity_metadata.attribute_name
        self._enum = entity_metadata.enum
        # All entries except index 0 (off) are exposed as tones
        entries = list(self._enum)
        self._attr_available_tones = {
            entry.value: entry.name.replace("_", " ") for entry in entries[1:]
        }

    @property
    def is_on(self) -> bool:
        """Return True if the current enum value is not the off entry (index 0)."""
        value = self._cluster_handler.cluster.get(self._attribute_name)
        if value is None:
            return False
        off_value = next(iter(self._enum)).value
        return int(value) != off_value

    def handle_cluster_handler_attribute_updated(
        self,
        event: ClusterAttributeUpdatedEvent,
    ) -> None:
        """Handle state update from cluster handler."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
    ) -> None:
        """Turn on siren. Uses tone if provided, otherwise the second enum entry."""
        entries = list(self._enum)
        if tone is not None and tone in self._attr_available_tones:
            target = self._enum(tone)
        else:
            # Default: second entry (index 1)
            target = entries[1]
        await self._cluster_handler.write_attributes_safe(
            {self._attribute_name: target}
        )
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self) -> None:
        """Turn off siren by writing the first enum entry (index 0)."""
        off_entry = next(iter(self._enum))
        await self._cluster_handler.write_attributes_safe(
            {self._attribute_name: off_entry}
        )
        self.maybe_emit_state_changed_event()

    async def async_update(self) -> None:
        """Attempt to retrieve the state of the entity."""
        self.debug("Polling current state")
        results = await self._cluster_handler.get_attributes(
            [self._attribute_name], from_cache=False, only_cache=False
        )
        self.debug("read values=%s", results)
        self.maybe_emit_state_changed_event()


@register_entity(IasWd.cluster_id)
class AdvancedSiren(BaseZclSiren):
    """Representation of a ZHA siren with full tone, level, and strobe support."""

    _attr_fallback_name: str = "Siren"
    _attr_primary_weight = 4

    _cluster_handler_match = ClusterHandlerMatch(
        cluster_handlers=frozenset({CLUSTER_HANDLER_IAS_WD}),
        feature_priority=(PlatformFeatureGroup.SIREN, 0),
    )

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this siren."""
        legacy_discovery_unique_id = (
            f"{endpoint.device.ieee}-{endpoint.id}"
            if (
                endpoint.zigpy_endpoint.device_type == zha.DeviceType.IAS_WARNING_DEVICE
            )
            else f"{endpoint.device.ieee}-{endpoint.id}-{int(IasWd.cluster_id)}"
        )

        super().__init__(
            cluster_handlers,
            endpoint,
            device,
            **kwargs,
            legacy_discovery_unique_id=legacy_discovery_unique_id,
        )
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON
            | SirenEntityFeature.TURN_OFF
            | SirenEntityFeature.DURATION
            | SirenEntityFeature.VOLUME_SET
            | SirenEntityFeature.TONES
        )
        self._attr_available_tones: dict[int, str] = {
            WARNING_DEVICE_MODE_BURGLAR: "Burglar",
            WARNING_DEVICE_MODE_FIRE: "Fire",
            WARNING_DEVICE_MODE_EMERGENCY: "Emergency",
            WARNING_DEVICE_MODE_POLICE_PANIC: "Police Panic",
            WARNING_DEVICE_MODE_FIRE_PANIC: "Fire Panic",
            WARNING_DEVICE_MODE_EMERGENCY_PANIC: "Emergency Panic",
        }

    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
    ) -> None:
        """Turn on siren."""
        if self._off_listener:
            self._off_listener.cancel()
            self._off_listener = None
        tone_cache = self._cluster_handler.data_cache.get(
            IasWd.Warning.WarningMode.__name__
        )
        siren_tone = (
            tone_cache.value
            if tone_cache is not None
            else WARNING_DEVICE_MODE_EMERGENCY
        )
        siren_duration = DEFAULT_DURATION
        level_cache = self._cluster_handler.data_cache.get(
            IasWd.Warning.SirenLevel.__name__
        )
        siren_level = (
            level_cache.value if level_cache is not None else WARNING_DEVICE_SOUND_HIGH
        )
        strobe_cache = self._cluster_handler.data_cache.get(Strobe.__name__)
        should_strobe = (
            strobe_cache.value if strobe_cache is not None else Strobe.No_Strobe
        )
        strobe_level_cache = self._cluster_handler.data_cache.get(
            IasWd.StrobeLevel.__name__
        )
        strobe_level = (
            strobe_level_cache.value
            if strobe_level_cache is not None
            else WARNING_DEVICE_STROBE_HIGH
        )
        if duration is not None:
            siren_duration = duration
        if tone is not None:
            siren_tone = tone
        if volume_level is not None:
            siren_level = int(volume_level)
        await self._cluster_handler.issue_start_warning(
            mode=siren_tone,
            warning_duration=siren_duration,
            siren_level=siren_level,
            strobe=should_strobe,
            strobe_duty_cycle=50 if should_strobe else 0,
            strobe_intensity=strobe_level,
        )
        self._attr_is_on = True
        self._off_listener = asyncio.get_running_loop().call_later(
            siren_duration, self._async_set_off
        )
        self._tracked_handles.append(self._off_listener)
        self.maybe_emit_state_changed_event()


@register_entity(IasWd.cluster_id)
class BasicSiren(BaseZclSiren):
    """Representation of a basic ZHA siren with fixed tone, level, and strobe."""

    _attr_fallback_name: str = "Siren"
    _attr_primary_weight = 4

    _cluster_handler_match = ClusterHandlerMatch(
        cluster_handlers=frozenset({CLUSTER_HANDLER_IAS_WD}),
        exposed_features=frozenset({"siren_basic"}),
        feature_priority=(PlatformFeatureGroup.SIREN, 1),
    )

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this basic siren."""
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON
            | SirenEntityFeature.TURN_OFF
            | SirenEntityFeature.DURATION
        )
        self._attr_available_tones: dict[int, str] = {}

    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
    ) -> None:
        """Turn on siren with fixed tone, level, and strobe."""
        if self._off_listener:
            self._off_listener.cancel()
            self._off_listener = None
        siren_duration = duration if duration is not None else DEFAULT_DURATION
        await self._cluster_handler.issue_start_warning(
            mode=WARNING_DEVICE_MODE_EMERGENCY,
            warning_duration=siren_duration,
            siren_level=WARNING_DEVICE_SOUND_HIGH,
            strobe=WARNING_DEVICE_STROBE_NO,
            strobe_duty_cycle=0,
            strobe_intensity=WARNING_DEVICE_STROBE_HIGH,
        )
        self._attr_is_on = True
        self._off_listener = asyncio.get_running_loop().call_later(
            siren_duration, self._async_set_off
        )
        self._tracked_handles.append(self._off_listener)
        self.maybe_emit_state_changed_event()
