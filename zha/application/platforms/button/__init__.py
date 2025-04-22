"""Support for ZHA button."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import logging
from typing import TYPE_CHECKING, Any

from zigpy.quirks.v2 import WriteAttributeButtonMetadata, ZCLCommandButtonMetadata

from zha.application import Platform
from zha.application.const import ENTITY_METADATA
from zha.application.platforms import (
    BaseEntity,
    BaseEntityInfo,
    EntityCategory,
    PlatformEntity,
)
from zha.application.platforms.button.const import DEFAULT_DURATION, ButtonDeviceClass
from zha.application.registries import PLATFORM_ENTITIES
from zha.zigbee.cluster_handlers.const import CLUSTER_HANDLER_IDENTIFY

if TYPE_CHECKING:
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device
    from zha.zigbee.endpoint import Endpoint


MULTI_MATCH = functools.partial(PLATFORM_ENTITIES.multipass_match, Platform.BUTTON)
CONFIG_DIAGNOSTIC_MATCH = functools.partial(
    PLATFORM_ENTITIES.config_diagnostic_match, Platform.BUTTON
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class CommandButtonEntityInfo(BaseEntityInfo):
    """Command button entity info."""

    command: str
    args: list[Any]
    kwargs: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class WriteAttributeButtonEntityInfo(BaseEntityInfo):
    """Write attribute button entity info."""

    attribute_name: str
    attribute_value: Any


class Button(PlatformEntity):
    """Defines a ZHA button."""

    PLATFORM = Platform.BUTTON

    _command_name: str
    _args: list[Any]
    _kwargs: dict[str, Any]

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ):
        """Initialize button."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        if ENTITY_METADATA in kwargs:
            self._init_from_quirks_metadata(kwargs[ENTITY_METADATA])
        super().__init__(cluster_handlers, endpoint, device, **kwargs)

    def _init_from_quirks_metadata(
        self, entity_metadata: ZCLCommandButtonMetadata
    ) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        self._command_name = entity_metadata.command_name
        self._args = entity_metadata.args
        self._kwargs = entity_metadata.kwargs

    @functools.cached_property
    def info_object(self) -> CommandButtonEntityInfo:
        """Return a representation of the button."""
        return CommandButtonEntityInfo(
            **super().info_object.__dict__,
            command=self._command_name,
            args=self._args,
            kwargs=self._kwargs,
        )

    @functools.cached_property
    def args(self) -> list[Any]:
        """Return the arguments to use in the command."""
        return list(self._args) if self._args else []

    @functools.cached_property
    def kwargs(self) -> dict[str, Any]:
        """Return the keyword arguments to use in the command."""
        return self._kwargs

    async def async_press(self) -> None:
        """Send out a update command."""
        command = getattr(self._cluster_handler, self._command_name)
        arguments = self.args or []
        kwargs = self.kwargs or {}
        await command(*arguments, **kwargs)


@MULTI_MATCH(cluster_handler_names=CLUSTER_HANDLER_IDENTIFY)
class IdentifyButton(Button):
    """Defines a ZHA identify button."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _command_name = "identify"
    _kwargs = {}
    _args = [DEFAULT_DURATION]

    def is_supported_in_list(self, entities: list[BaseEntity]) -> bool:
        """Check if this button is supported given the list of entities."""
        cls = type(self)
        return not any(type(entity) is cls for entity in entities)


class WriteAttributeButton(PlatformEntity):
    """Defines a ZHA button, which writes a value to an attribute."""

    PLATFORM = Platform.BUTTON

    _attribute_name: str
    _attribute_value: Any = None

    def __init__(
        self,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> None:
        """Init this button."""
        self._cluster_handler: ClusterHandler = cluster_handlers[0]
        if ENTITY_METADATA in kwargs:
            self._init_from_quirks_metadata(kwargs[ENTITY_METADATA])
        super().__init__(cluster_handlers, endpoint, device, **kwargs)
        self.recompute_capabilities()

    def _init_from_quirks_metadata(
        self, entity_metadata: WriteAttributeButtonMetadata
    ) -> None:
        """Init this entity from the quirks metadata."""
        super()._init_from_quirks_metadata(entity_metadata)
        self._attribute_name = entity_metadata.attribute_name
        self._attribute_value = entity_metadata.attribute_value

    @functools.cached_property
    def info_object(self) -> WriteAttributeButtonEntityInfo:
        """Return a representation of the button."""
        return WriteAttributeButtonEntityInfo(
            **super().info_object.__dict__,
            attribute_name=self._attribute_name,
            attribute_value=self._attribute_value,
        )

    async def async_press(self) -> None:
        """Write attribute with defined value."""
        await self._cluster_handler.write_attributes_safe(
            {self._attribute_name: self._attribute_value}
        )


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="tuya_manufacturer",
    manufacturers={
        "_TZE200_htnnfasr",
    },
)
class FrostLockResetButton(WriteAttributeButton):
    """Defines a ZHA frost lock reset button."""

    _unique_id_suffix = "reset_frost_lock"
    _attribute_name = "frost_lock_reset"
    _attribute_value = 0
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reset_frost_lock"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.motion.ac01"}
)
class NoPresenceStatusResetButton(WriteAttributeButton):
    """Defines a ZHA no presence status reset button."""

    _unique_id_suffix = "reset_no_presence_status"
    _attribute_name = "reset_no_presence_status"
    _attribute_value = 1
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reset_no_presence_status"


@MULTI_MATCH(cluster_handler_names="opple_cluster", models={"aqara.feeder.acn001"})
class AqaraPetFeederFeedButton(WriteAttributeButton):
    """Defines a feed button for the aqara c1 pet feeder."""

    _unique_id_suffix = "feeding"
    _attribute_name = "feeding"
    _attribute_value = 1
    _attr_translation_key = "feed"


@CONFIG_DIAGNOSTIC_MATCH(
    cluster_handler_names="opple_cluster", models={"lumi.sensor_smoke.acn03"}
)
class AqaraSelfTestButton(WriteAttributeButton):
    """Defines a ZHA self-test button for Aqara smoke sensors."""

    _unique_id_suffix = "self_test"
    _attribute_name = "self_test"
    _attribute_value = 1
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "self_test"
