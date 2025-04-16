"""Support for the ZHA event platform."""

from __future__ import annotations

import dataclasses
import functools
import logging
from typing import Any, Final

from zigpy.quirks.v2 import EventMetadata

from zha.application import Platform
from zha.application.platforms import PlatformEntity
from zha.application.platforms.helpers import validate_device_class

from .const import EventDeviceClass

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class EventPlatformEvent:
    """Event for the event platform trigger."""

    event: Final[str] = "trigger_event"
    event_type: str
    event_attributes: dict[str, Any] | None


class EventEntity(PlatformEntity):
    """Represent an event entity."""

    PLATFORM = Platform.EVENT
    _attr_event_types: tuple[str] = ()

    def _init_from_quirks_metadata(self, entity_metadata: EventMetadata) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)

        self._attr_event_types = entity_metadata.event_types

        if entity_metadata.device_class is not None:
            self._attr_device_class = validate_device_class(
                EventDeviceClass,
                entity_metadata.device_class,
                Platform.EVENT.value,
                _LOGGER,
            )

    @functools.cached_property
    def event_types(self) -> list[str]:
        """Return a list of possible events."""
        return list(self._attr_event_types)

    def trigger_event(
        self, event_type: str, event_attributes: dict[str, Any] | None = None
    ) -> None:
        """Trigger an event."""
        self.emit(
            EventPlatformEvent.event_type,
            EventPlatformEvent(
                event_type=event_type,
                event_attributes=event_attributes,
            ),
        )
