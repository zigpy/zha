"""Text entities on Zigbee Home Automation networks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any

from zigpy.zcl import (
    AttributeReadEvent,
    AttributeReportedEvent,
    AttributeUpdatedEvent,
    AttributeWrittenEvent,
)

from zha.application import Platform
from zha.application.helpers import write_attributes_safe
from zha.application.platforms import (
    BaseEntityState,
    EntityCategory,
    PlatformEntity,
    ZclPlatformEntity,
)
from zha.application.platforms.text.const import MAX_LENGTH_STATE_STATE, TextMode
from zha.exceptions import ZHAException

if TYPE_CHECKING:
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TextState(BaseEntityState):
    """State for text entities."""

    native_value: str | None
    mode: TextMode
    native_min: int
    native_max: int
    pattern: str | None


class BaseText(PlatformEntity, ABC):
    """Abstract base class for ZHA text entities."""

    PLATFORM = Platform.TEXT

    _attr_mode: TextMode = TextMode.TEXT
    _attr_native_min: int = 0
    _attr_native_max: int = MAX_LENGTH_STATE_STATE
    _attr_pattern: str | None = None

    @property
    def state(self) -> TextState:
        """Return the state of the text entity."""
        return TextState(
            **super().state.__dict__,
            native_value=self.native_value,
            mode=self.mode,
            native_min=self.native_min,
            native_max=self.native_max,
            pattern=self.pattern,
        )

    @property
    def mode(self) -> TextMode:
        """Return how the frontend shows the text input."""
        return self._attr_mode

    @property
    def native_min(self) -> int:
        """Return the minimum length of the value."""
        return self._attr_native_min

    @property
    def native_max(self) -> int:
        """Return the maximum length of the value."""
        return self._attr_native_max

    @property
    def pattern(self) -> str | None:
        """Return the regex pattern the value has to match."""
        return self._attr_pattern

    @property
    @abstractmethod
    def native_value(self) -> str | None:
        """Return the current value."""

    @abstractmethod
    async def async_set_value(self, value: str) -> None:
        """Change the value."""


class TextConfigurationEntity(BaseText, ZclPlatformEntity):
    """A text entity that shows and writes a ZCL string attribute.

    Attributes typed as raw bytes (`LVBytes` and the like) are decoded from and
    encoded to UTF-8.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attribute_name: str

    def __init__(
        self,
        endpoint: Endpoint,
        device: Device,
        *,
        attribute_name: str | None = None,
        min_length: int | None = None,
        max_length: int | None = None,
        pattern: str | None = None,
        mode: TextMode | str | None = None,
        **kwargs: Any,
    ) -> None:
        """Init this text configuration entity."""
        if attribute_name is not None:
            self._attribute_name = attribute_name
        if min_length is not None:
            self._attr_native_min = min_length
        if max_length is not None:
            self._attr_native_max = max_length
        if pattern is not None:
            self._attr_pattern = pattern
        if mode is not None:
            self._attr_mode = TextMode(mode)

        super().__init__(endpoint=endpoint, device=device, **kwargs)

    def _is_supported(self) -> bool:
        """Return if the entity is supported for the device, internal."""
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

    def on_add(self) -> None:
        """Run when the entity is added."""
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

    @property
    def _is_bytes_attribute(self) -> bool:
        """Return if the attribute holds raw bytes rather than a string."""
        attr_def = self._cluster.attributes_by_name[self._attribute_name]
        return issubclass(attr_def.type, bytes)

    @property
    def native_value(self) -> str | None:
        """Return the current value."""
        value = self._cluster.get(self._attribute_name)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    async def async_set_value(self, value: str) -> None:
        """Write a new value to the attribute."""
        new_value: str | bytes = (
            value.encode("utf-8") if self._is_bytes_attribute else value
        )

        try:
            await write_attributes_safe(
                self._cluster, {self._attribute_name: new_value}
            )
        except ZHAException:
            if self.mode is not TextMode.PASSWORD:
                raise
            # The error message contains the value, which must not end up in a log
            raise ZHAException(
                f"Failed to write attribute {self._attribute_name}"
            ) from None

        self.maybe_emit_state_changed_event()

    def handle_attribute_updated(
        self,
        event: AttributeReadEvent
        | AttributeReportedEvent
        | AttributeUpdatedEvent
        | AttributeWrittenEvent,
    ) -> None:
        """Handle a value update from the cluster."""
        if event.attribute_name == self._attribute_name:
            self.maybe_emit_state_changed_event()
