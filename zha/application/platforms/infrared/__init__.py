"""Infrared emitters and receivers on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import abstractmethod
import dataclasses
from typing import TYPE_CHECKING, Any, Final

from zigpy.types.named import EUI64

from zha.application import Platform
from zha.application.platforms import BaseEntityState, PlatformEntity
from zha.application.platforms.infrared.const import InfraredDeviceClass

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


@dataclasses.dataclass(frozen=True, kw_only=True)
class InfraredSignal:
    """A raw infrared signal, sent by an emitter or captured by a receiver."""

    timings: list[int]
    modulation: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class InfraredReceiverState(BaseEntityState):
    """State for infrared receiver entities."""

    receiving: bool


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


class BaseInfraredEmitter(PlatformEntity):
    """Base representation of a ZHA infrared emitter entity."""

    PLATFORM = Platform.INFRARED

    _attr_device_class: InfraredDeviceClass = InfraredDeviceClass.EMITTER

    @abstractmethod
    async def async_send_command(self, signal: InfraredSignal) -> None:
        """Transmit an infrared signal."""


class BaseInfraredReceiver(PlatformEntity):
    """Base representation of a ZHA infrared receiver entity."""

    PLATFORM = Platform.INFRARED

    _attr_device_class: InfraredDeviceClass = InfraredDeviceClass.RECEIVER

    def __init__(self, endpoint: Endpoint, device: Device, **kwargs: Any) -> None:
        """Initialize the infrared receiver entity."""
        super().__init__(endpoint=endpoint, device=device, **kwargs)

        self._receiving = False

    @property
    def receiving(self) -> bool:
        """Return whether the device is currently in receive mode."""
        return self._receiving

    @property
    def state(self) -> InfraredReceiverState:
        """Return the state of the infrared receiver entity."""
        return InfraredReceiverState(
            **super().state.__dict__,
            receiving=self.receiving,
        )

    async def async_start_receiving(self) -> None:
        """Put the device into receive mode."""
        await self._async_start_receiving()
        self._receiving = True
        self.maybe_emit_state_changed_event()

    async def async_stop_receiving(self) -> None:
        """Take the device out of receive mode."""
        if not self._receiving:
            return

        await self._async_stop_receiving()
        self._receiving = False
        self.maybe_emit_state_changed_event()

    def _handle_receive_mode_ended(self) -> None:
        """Handle the device leaving receive mode, to be called by subclasses."""
        self._receiving = False
        self.maybe_emit_state_changed_event()

    def _handle_received_signal(self, signal: InfraredSignal) -> None:
        """Handle a captured signal, to be called by subclasses."""
        self.emit(
            EntityInfraredSignalReceivedEvent.event,
            EntityInfraredSignalReceivedEvent(
                **self.identifiers.__dict__,
                signal=signal,
            ),
        )

    @abstractmethod
    async def _async_start_receiving(self) -> None:
        """Ask the device to enter receive mode."""

    @abstractmethod
    async def _async_stop_receiving(self) -> None:
        """Ask the device to leave receive mode."""
