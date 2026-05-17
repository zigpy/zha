"""Support for ZHA sirens."""

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import contextlib
from dataclasses import dataclass
from enum import IntFlag
import functools
from typing import TYPE_CHECKING, Any, Final

from zhaquirks.quirk_ids import SIREN_BASIC
from zigpy.profiles import zha
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
from zha.application.helpers import cluster_runtime_state
from zha.application.platforms import (
    BaseEntityInfo,
    ClusterConfig,
    ClusterMatch,
    PlatformEntity,
    PlatformFeatureGroup,
    register_entity,
)

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


def _set_bit(destination_value, destination_bit, source_value, source_bit):
    """Set the specified bit in the value."""
    if (source_value & (1 << source_bit)) != 0:
        return destination_value | (1 << destination_bit)
    return destination_value


async def issue_start_warning(
    cluster,
    *,
    mode,
    strobe,
    siren_level,
    warning_duration,
    strobe_duty_cycle,
    strobe_intensity,
) -> None:
    """Issue an IAS WD start_warning command with packed warning byte."""
    value = 0
    value = _set_bit(value, 0, siren_level, 0)
    value = _set_bit(value, 1, siren_level, 1)
    value = _set_bit(value, 2, strobe, 0)
    value = _set_bit(value, 4, mode, 0)
    value = _set_bit(value, 5, mode, 1)
    value = _set_bit(value, 6, mode, 2)
    value = _set_bit(value, 7, mode, 3)

    await cluster.start_warning(
        value, warning_duration, strobe_duty_cycle, strobe_intensity
    )


async def issue_squawk(cluster, *, mode, strobe, squawk_level) -> None:
    """Issue an IAS WD squawk command with packed squawk byte."""
    value = 0
    value = _set_bit(value, 0, squawk_level, 0)
    value = _set_bit(value, 1, squawk_level, 1)
    value = _set_bit(value, 3, strobe, 0)
    value = _set_bit(value, 4, mode, 0)
    value = _set_bit(value, 5, mode, 1)
    value = _set_bit(value, 6, mode, 2)
    value = _set_bit(value, 7, mode, 3)

    await cluster.squawk(value)


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
        self._cluster = endpoint.zigpy_endpoint.in_clusters[IasWd.cluster_id]
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
        await issue_start_warning(
            self._cluster,
            mode=WARNING_DEVICE_MODE_STOP,
            strobe=WARNING_DEVICE_STROBE_NO,
            siren_level=IasWd.Warning.SirenLevel.High_level_sound,
            warning_duration=5,
            strobe_duty_cycle=0,
            strobe_intensity=IasWd.StrobeLevel.High_level_strobe,
        )
        self._cancel_off_listener()
        self._attr_is_on = False
        self.maybe_emit_state_changed_event()

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
        self._cancel_off_listener()
        cache = cluster_runtime_state(self._cluster)
        tone_cache = cache.get(IasWd.Warning.WarningMode.__name__)
        siren_tone = (
            tone_cache.value
            if tone_cache is not None
            else WARNING_DEVICE_MODE_EMERGENCY
        )
        siren_duration = DEFAULT_DURATION
        level_cache = cache.get(IasWd.Warning.SirenLevel.__name__)
        siren_level = (
            level_cache.value if level_cache is not None else WARNING_DEVICE_SOUND_HIGH
        )
        strobe_cache = cache.get(Strobe.__name__)
        should_strobe = (
            strobe_cache.value if strobe_cache is not None else Strobe.No_Strobe
        )
        strobe_level_cache = cache.get(IasWd.StrobeLevel.__name__)
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
        await issue_start_warning(
            self._cluster,
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
    ) -> None:
        """Turn on siren with fixed tone, level, and strobe."""
        self._cancel_off_listener()
        siren_duration = duration if duration is not None else DEFAULT_DURATION
        await issue_start_warning(
            self._cluster,
            # some Frient sensors send INVALID_VALUE for EMERGENCY
            mode=WARNING_DEVICE_MODE_BURGLAR,
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
