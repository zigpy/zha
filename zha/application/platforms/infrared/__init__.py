"""Infrared emitters and receivers on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
import dataclasses
from typing import Final

from zigpy.types.named import EUI64

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.infrared.const import InfraredDeviceClass


@dataclasses.dataclass(frozen=True, kw_only=True)
class InfraredSignal:
    """A raw infrared signal, sent by an emitter or captured by a receiver."""

    timings: list[int]
    modulation: int | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class EntityInfraredSignalReceivedEvent:
    """Event for when an infrared receiver captures a signal."""

    event_type: Final[str] = "entity"
    event: Final[str] = "infrared_signal_received"
    platform: str
    unique_id: str
    device_ieee: EUI64 | None = None
    endpoint_id: int | None = None
    group_id: int | None = None
    signal: InfraredSignal


class BaseInfraredEmitter(PlatformEntity, ABC):
    """Base representation of a ZHA infrared emitter entity."""

    PLATFORM = Platform.INFRARED

    _attr_device_class: InfraredDeviceClass = InfraredDeviceClass.EMITTER

    @abstractmethod
    async def async_send_command(self, signal: InfraredSignal) -> None:
        """Transmit an infrared signal."""


class BaseInfraredReceiver(PlatformEntity, ABC):
    """Base representation of a ZHA infrared receiver entity."""

    PLATFORM = Platform.INFRARED

    _attr_device_class: InfraredDeviceClass = InfraredDeviceClass.RECEIVER

    def _handle_received_signal(self, signal: InfraredSignal) -> None:
        """Handle a captured signal, to be called by subclasses."""
        self.emit(
            EntityInfraredSignalReceivedEvent.event,
            EntityInfraredSignalReceivedEvent(
                **self.identifiers.__dict__,
                signal=signal,
            ),
        )
