"""Support for ZHA sirens."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from enum import IntFlag
import functools
from typing import TYPE_CHECKING, Any, Final, cast

from zigpy.zcl.clusters.security import IasWd as WD

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
from zha.application.platforms import BaseEntityInfo, PlatformEntity
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers.const import CLUSTER_HANDLER_IAS_WD
from zha.zigbee.cluster_handlers.security import IasWdClusterHandler

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.SIREN)
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


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_IAS_WD)
class Siren(PlatformEntity):
    """Representation of a ZHA siren."""

    PLATFORM = Platform.SIREN
    _attr_fallback_name: str = "Siren"
    _attr_primary_weight = 10

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this siren."""
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
        self._cluster_handler: IasWdClusterHandler = cast(
            IasWdClusterHandler, cluster_handlers[0]
        )
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self._attr_is_on: bool = False
        self._off_listener: asyncio.TimerHandle | None = None

    @functools.cached_property
    def info_object(self) -> SirenEntityInfo:
        """Return representation of the siren."""
        return SirenEntityInfo(
            **super().info_object.__dict__,
            available_tones=self._attr_available_tones,
            supported_features=self._attr_supported_features,
        )

    @property
    def state(self) -> dict[str, Any]:
        """Get the state of the siren."""
        response = super().state
        response["state"] = self.is_on
        return response

    @property
    def supported_features(self) -> SirenEntityFeature:
        """Return supported features."""
        return self._attr_supported_features

    @property
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on siren."""
        if self._off_listener:
            self._off_listener.cancel()
            self._off_listener = None
        tone_cache = self._cluster_handler.data_cache.get(
            WD.Warning.WarningMode.__name__
        )
        siren_tone = (
            tone_cache.value
            if tone_cache is not None
            else WARNING_DEVICE_MODE_EMERGENCY
        )
        siren_duration = DEFAULT_DURATION
        level_cache = self._cluster_handler.data_cache.get(
            WD.Warning.SirenLevel.__name__
        )
        siren_level = (
            level_cache.value if level_cache is not None else WARNING_DEVICE_SOUND_HIGH
        )
        strobe_cache = self._cluster_handler.data_cache.get(Strobe.__name__)
        should_strobe = (
            strobe_cache.value if strobe_cache is not None else Strobe.No_Strobe
        )
        strobe_level_cache = self._cluster_handler.data_cache.get(
            WD.StrobeLevel.__name__
        )
        strobe_level = (
            strobe_level_cache.value
            if strobe_level_cache is not None
            else WARNING_DEVICE_STROBE_HIGH
        )
        if (duration := kwargs.get(ATTR_DURATION)) is not None:
            siren_duration = duration
        if (tone := kwargs.get(ATTR_TONE)) is not None:
            siren_tone = tone
        if (level := kwargs.get(ATTR_VOLUME_LEVEL)) is not None:
            siren_level = int(level)
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
            siren_duration, self.async_set_off
        )
        self._tracked_handles.append(self._off_listener)
        self.maybe_emit_state_changed_event()

    async def async_turn_off(self, **kwargs: Any) -> None:  # pylint: disable=unused-argument
        """Turn off siren."""
        await self._cluster_handler.issue_start_warning(
            mode=WARNING_DEVICE_MODE_STOP, strobe=WARNING_DEVICE_STROBE_NO
        )
        self._attr_is_on = False
        self.maybe_emit_state_changed_event()

    def async_set_off(self) -> None:
        """Set is_on to False and write HA state."""
        self._attr_is_on = False
        if self._off_listener:
            self._off_listener.cancel()

            with contextlib.suppress(ValueError):
                self._tracked_handles.remove(self._off_listener)

            self._off_listener = None
        self.maybe_emit_state_changed_event()
