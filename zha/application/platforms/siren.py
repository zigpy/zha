"""Support for ZHA sirens."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import contextlib
from dataclasses import dataclass
from enum import Enum, IntFlag
import functools
from typing import TYPE_CHECKING, Any, Final

from zigpy.profiles import zha
import zigpy.zcl
from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
)
from zigpy.zcl.clusters.security import (
    IasWd,
    SirenLevel,
    Squawk,
    SquawkMode,
    Strobe,
    StrobeLevel,
    WarningMode,
    WarningType,
)

from zha.application import Platform
from zha.application.helpers import write_attributes_safe
from zha.application.platforms import (
    BaseEntityInfo,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)
from zha.quirks import SIREN_BASIC

if TYPE_CHECKING:
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
        # These kwargs are ZHA extensions to the base HA entity signature
        strobe: int | None = None,
        strobe_duty_cycle: int | None = None,
        strobe_intensity: int | None = None,
    ) -> None:
        """Turn on siren."""

    @abstractmethod
    async def async_turn_off(self) -> None:
        """Turn off siren."""


class BaseZclSiren(BaseSiren, ABC):
    """Base class for ZHA IAS WD siren entities with shared ZCL logic."""

    _off_listener: asyncio.TimerHandle | None
    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
    )
    _server_cluster_config = {
        IasWd.cluster_id: ClusterConfig(
            bind=True,
        ),
    }

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init ZCL siren base."""
        self._off_listener = None

        legacy_discovery_unique_id = (
            f"{endpoint.device.ieee}-{endpoint.id}"
            if (
                endpoint.zigpy_endpoint.device_type == zha.DeviceType.IAS_WARNING_DEVICE
            )
            else f"{endpoint.device.ieee}-{endpoint.id}-{int(IasWd.cluster_id)}"
        )

        super().__init__(
            endpoint=endpoint,
            device=device,
            legacy_discovery_unique_id=legacy_discovery_unique_id,
            **kwargs,
        )

    def _cancel_off_listener(self) -> None:
        """Cancel and clean up the off listener."""
        if self._off_listener:
            self._off_listener.cancel()

            with contextlib.suppress(ValueError):
                self._tracked_handles.remove(self._off_listener)

            self._off_listener = None

    async def async_turn_off(self) -> None:
        """Turn off siren."""
        warning = WarningType()
        warning.mode = WarningMode.Stop
        warning.strobe = Strobe.No_strobe
        warning.level = SirenLevel.High_level_sound
        await self._cluster.start_warning(
            warning=warning,
            warning_duration=5,
            strobe_duty_cycle=0,
            stobe_level=StrobeLevel.High_level_strobe,
        )
        self._cancel_off_listener()
        self._attr_is_on = False
        self.maybe_emit_state_changed_event()

    async def async_squawk(
        self,
        *,
        mode: SquawkMode,
        strobe: int,
        squawk_level: int,
    ) -> None:
        """Issue an IAS WD squawk command."""
        squawk = Squawk()
        squawk.mode = mode
        squawk.strobe = strobe
        squawk.level = squawk_level
        await self._cluster.squawk(squawk=squawk)

    def _async_set_off(self) -> None:
        """Set is_on to False and write HA state."""
        self._attr_is_on = False
        self._cancel_off_listener()
        self.maybe_emit_state_changed_event()


@register_entity(IasWd.cluster_id)
class AdvancedSiren(BaseZclSiren):
    """Representation of a ZHA siren with full tone, level, and strobe support."""

    _attr_fallback_name: str = "Siren"
    _attr_primary_weight = 4

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
        feature_priority=(PlatformFeatureGroup.SIREN, 0),
    )

    defaults: dict[type[Enum], Enum | None]

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this siren."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON
            | SirenEntityFeature.TURN_OFF
            | SirenEntityFeature.DURATION
            | SirenEntityFeature.VOLUME_SET
            | SirenEntityFeature.TONES
        )
        self._attr_available_tones: dict[int, str] = {
            WarningMode.Burglar: "Burglar",
            WarningMode.Fire: "Fire",
            WarningMode.Emergency: "Emergency",
            WarningMode.Police_Panic: "Police Panic",
            WarningMode.Fire_Panic: "Fire Panic",
            WarningMode.Emergency_Panic: "Emergency Panic",
        }
        self.defaults = {
            WarningMode: None,
            SirenLevel: None,
            Strobe: None,
            StrobeLevel: None,
        }

    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
        # These kwargs are ZHA extensions to the base HA entity signature
        strobe: int | None = None,
        strobe_duty_cycle: int | None = None,
        strobe_intensity: int | None = None,
    ) -> None:
        """Turn on siren."""
        self._cancel_off_listener()
        tone_default = self.defaults[WarningMode]
        siren_tone = (
            tone_default.value if tone_default is not None else WarningMode.Emergency
        )
        level_default = self.defaults[SirenLevel]
        siren_level = (
            level_default.value
            if level_default is not None
            else SirenLevel.High_level_sound
        )
        strobe_default = self.defaults[Strobe]
        should_strobe = (
            strobe_default.value if strobe_default is not None else Strobe.No_strobe
        )
        strobe_level_default = self.defaults[StrobeLevel]
        strobe_level = (
            strobe_level_default.value
            if strobe_level_default is not None
            else StrobeLevel.High_level_strobe
        )
        siren_duration = DEFAULT_DURATION
        if duration is not None:
            siren_duration = duration
        if tone is not None:
            siren_tone = tone
        if volume_level is not None:
            siren_level = int(volume_level)
        if strobe is not None:
            should_strobe = strobe
        if strobe_intensity is not None:
            strobe_level = strobe_intensity
        duty_cycle = (
            strobe_duty_cycle
            if strobe_duty_cycle is not None
            else (50 if should_strobe else 0)
        )

        warning = WarningType()
        warning.mode = siren_tone
        warning.strobe = should_strobe
        warning.level = siren_level
        await self._cluster.start_warning(
            warning=warning,
            warning_duration=siren_duration,
            strobe_duty_cycle=duty_cycle,
            stobe_level=strobe_level,
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

    _cluster_match = ClusterMatch(
        server_clusters=frozenset({IasWd.cluster_id}),
        exposed_features=frozenset({SIREN_BASIC}),
        feature_priority=(PlatformFeatureGroup.SIREN, 1),
    )

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this basic siren."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)
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
        # These kwargs are ZHA extensions to the base HA entity signature
        strobe: int | None = None,
        strobe_duty_cycle: int | None = None,
        strobe_intensity: int | None = None,
    ) -> None:
        """Turn on siren with fixed tone, level, and strobe."""
        self._cancel_off_listener()
        siren_duration = duration if duration is not None else DEFAULT_DURATION

        warning = WarningType()
        # some Frient sensors send INVALID_VALUE for EMERGENCY
        warning.mode = WarningMode.Burglar
        warning.strobe = Strobe.No_strobe
        warning.level = SirenLevel.High_level_sound
        await self._cluster.start_warning(
            warning=warning,
            warning_duration=siren_duration,
            strobe_duty_cycle=0,
            stobe_level=StrobeLevel.High_level_strobe,
        )
        self._attr_is_on = True
        self._off_listener = asyncio.get_running_loop().call_later(
            siren_duration, self._async_set_off
        )
        self._tracked_handles.append(self._off_listener)
        self.maybe_emit_state_changed_event()


class AttributeSiren(BaseSiren):
    """Siren that is controlled by writing an enum attribute.

    Unlike the IAS WD sirens, this entity does not issue ``start_warning``
    commands. It turns on by writing a (tone) value to a manufacturer-specific
    attribute and off by writing ``off_value``; the device keeps sounding until
    it is turned off or the device itself reports the attribute back to
    ``off_value``. State is derived from the cached attribute value, so a device
    that resets the attribute on its own keeps the entity in sync.

    This entity is only created from quirks v2 metadata (``.siren(...)``); it has
    no default cluster match.
    """

    _attr_fallback_name: str = "Siren"

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        cluster: zigpy.zcl.Cluster,
        attribute_name: str,
        available_tones: dict[int, str] | None = None,
        off_value: int = 0,
        default_tone: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Init this attribute-controlled siren."""
        self._attribute_name = attribute_name
        self._off_value = off_value
        self._attr_available_tones = dict(available_tones or {})
        # Tone written when turned on without an explicit tone: the configured
        # default, else the first available tone, else 1.
        self._default_tone = (
            default_tone
            if default_tone is not None
            else next(iter(self._attr_available_tones), 1)
        )
        super().__init__(endpoint=endpoint, device=device, cluster=cluster, **kwargs)
        self._attr_supported_features = (
            SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF
        )
        if self._attr_available_tones:
            self._attr_supported_features |= SirenEntityFeature.TONES

    def on_add(self) -> None:
        """Subscribe to attribute updates so device-driven changes update state."""
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

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle state update from the cluster."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()

    @property
    def is_on(self) -> bool:
        """Return true if the siren is sounding."""
        value = self._cluster.get(self._attribute_name)
        return value is not None and value != self._off_value

    async def async_turn_on(
        self,
        duration: int | None = None,
        tone: int | None = None,
        volume_level: int | None = None,
        # These kwargs are ZHA extensions to the base HA entity signature
        strobe: int | None = None,
        strobe_duty_cycle: int | None = None,
        strobe_intensity: int | None = None,
    ) -> None:
        """Turn on siren by writing the requested tone to the attribute."""
        siren_tone = tone if tone is not None else self._default_tone
        await write_attributes_safe(self._cluster, {self._attribute_name: siren_tone})
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self) -> None:
        """Turn off siren by writing the off value to the attribute."""
        await write_attributes_safe(
            self._cluster, {self._attribute_name: self._off_value}
        )
        self.maybe_emit_state_changed_event()
