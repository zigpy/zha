"""Platform module for zhas."""

from __future__ import annotations

import abc
import asyncio
from contextlib import suppress
import logging
from typing import TYPE_CHECKING, Any, Union

from zigpy.types.named import EUI64

from zha.application.platforms.model import STATE_CHANGED, EntityStateChangedEvent
from zha.application.platforms.registries import Platform
from zha.event import EventBase
from zha.mixins import LogMixin
from zha.server.const import EVENT, EVENT_TYPE, EventTypes, PlatformEntityEvents
from zha.server.websocket.api.model import WebSocketCommand

if TYPE_CHECKING:
    from zha.server.zigbee.cluster import ClusterHandler
    from zha.server.zigbee.device import Device
    from zha.server.zigbee.endpoint import Endpoint
    from zha.server.zigbee.group import Group


_LOGGER = logging.getLogger(__name__)


class BaseEntity(LogMixin, EventBase):
    """Base class for entities."""

    PLATFORM: Platform = Platform.UNKNOWN

    def __init__(
        self,
        unique_id: str,
    ):
        """Initialize the platform entity."""
        super().__init__()
        self._unique_id: str = unique_id
        self._previous_state: Any = None
        self._tracked_tasks: list[asyncio.Task] = []

    @property
    def unique_id(self) -> str:
        """Return the unique id."""
        return self._unique_id

    @abc.abstractmethod
    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this platform entity."""

    @abc.abstractmethod
    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""

    def get_state(self) -> dict:
        """Return the arguments to use in the command."""
        return {
            "class_name": self.__class__.__name__,
        }

    async def async_update(self) -> None:
        """Retrieve latest state."""

    async def on_remove(self) -> None:
        """Cancel tasks this entity owns."""
        tasks = [t for t in self._tracked_tasks if not (t.done() or t.cancelled())]
        for task in tasks:
            self.debug("Cancelling task: %s", task)
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    def maybe_send_state_changed_event(self) -> None:
        """Send the state of this platform entity."""
        state = self.get_state()
        if self._previous_state != state:
            self.send_event(
                {
                    "state": self.get_state(),
                    EVENT: PlatformEntityEvents.PLATFORM_ENTITY_STATE_CHANGED,
                    EVENT_TYPE: EventTypes.PLATFORM_ENTITY_EVENT,
                }
            )
            self.emit(
                STATE_CHANGED, EntityStateChangedEvent.parse_obj(self.get_identifiers())
            )
            self._previous_state = state

    def to_json(self) -> dict:
        """Return a JSON representation of the platform entity."""
        return {
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
            "class_name": self.__class__.__name__,
            "state": self.get_state(),
        }

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a message."""
        msg = f"%s: {msg}"
        args = (self._unique_id,) + args
        _LOGGER.log(level, msg, *args, **kwargs)


class PlatformEntity(BaseEntity):
    """Class that represents an entity for a device platform."""

    unique_id_suffix: str | None = None

    def __init_subclass__(
        cls: type[PlatformEntity], id_suffix: str | None = None, **kwargs: Any
    ):
        """Initialize subclass.

        :param id_suffix: suffix to add to the unique_id of the entity. Used for multi
                          entities using the same cluster handler/cluster id for the entity.
        """
        super().__init_subclass__(**kwargs)
        if id_suffix:
            cls.unique_id_suffix = id_suffix

    def __init__(
        self,
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
    ):
        """Initialize the platform entity."""
        super().__init__(unique_id)
        ieeetail = "".join([f"{o:02x}" for o in device.ieee[:4]])
        ch_names = ", ".join(sorted(ch.name for ch in cluster_handlers))
        self._name: str = f"{device.name} {ieeetail} {ch_names}"
        if self.unique_id_suffix:
            self._name += f" {self.unique_id_suffix}"
            self._unique_id += f"-{self.unique_id_suffix}"
        self._cluster_handlers: list[ClusterHandler] = cluster_handlers
        self.cluster_handlers: dict[str, ClusterHandler] = {}
        for cluster_handler in cluster_handlers:
            self.cluster_handlers[cluster_handler.name] = cluster_handler
        self._device: Device = device
        self._endpoint = endpoint
        # we double create these in discovery tests because we reissue the create calls to count and prove them out
        if self.unique_id not in self._device.platform_entities:
            self._device.platform_entities[self.unique_id] = self

    @classmethod
    def create_platform_entity(
        cls: type[PlatformEntity],
        unique_id: str,
        cluster_handlers: list[ClusterHandler],
        endpoint: Endpoint,
        device: Device,
        **kwargs: Any,
    ) -> PlatformEntity | None:
        """Entity Factory.

        Return a platform entity if it is a supported configuration, otherwise return None
        """
        return cls(unique_id, cluster_handlers, endpoint, device, **kwargs)

    @property
    def device(self) -> Device:
        """Return the device."""
        return self._device

    @property
    def endpoint(self) -> Endpoint:
        """Return the endpoint."""
        return self._endpoint

    @property
    def should_poll(self) -> bool:
        """Return True if we need to poll for state changes."""
        return False

    @property
    def available(self) -> bool:
        """Return true if the device this entity belongs to is available."""
        return self.device.available

    @property
    def name(self) -> str:
        """Return the name of the platform entity."""
        return self._name

    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""
        return {
            "unique_id": self.unique_id,
            "platform": self.PLATFORM,
            "device_ieee": self.device.ieee,
            "endpoint_id": self.endpoint.id,
        }

    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this platform entity."""
        signal["platform_entity"] = {
            "name": self._name,
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
        }
        signal["endpoint"] = {
            "id": self._endpoint.id,
            "unique_id": self._endpoint.unique_id,
        }
        _LOGGER.info("Sending event from platform entity: %s", signal)
        self.device.send_event(signal)

    def to_json(self) -> dict:
        """Return a JSON representation of the platform entity."""
        json = super().to_json()
        json["name"] = self._name
        json["cluster_handlers"] = [ch.to_json() for ch in self._cluster_handlers]
        json["device_ieee"] = str(self._device.ieee)
        json["endpoint_id"] = self._endpoint.id
        return json

    async def async_update(self) -> None:
        """Retrieve latest state."""
        self.debug("polling current state")
        tasks = [
            cluster_handler.async_update()
            for cluster_handler in self.cluster_handlers.values()
            if hasattr(cluster_handler, "async_update")
        ]
        if tasks:
            await asyncio.gather(*tasks)
            self.maybe_send_state_changed_event()


class GroupEntity(BaseEntity):
    """A base class for group entities."""

    def __init__(
        self,
        group: Group,
    ) -> None:
        """Initialize a group."""
        super().__init__(f"{self.PLATFORM}.{group.group_id}")
        self._zigpy_group: Group = group
        self._name: str = f"{group.name}_0x{group.group_id:04x}"
        self._group: Group = group
        self._group.register_group_entity(self)
        self.update()

    @property
    def name(self) -> str:
        """Return the name of the group entity."""
        return self._name

    @property
    def group_id(self) -> int:
        """Return the group id."""
        return self._group.group_id

    @property
    def group(self) -> Group:
        """Return the group."""
        return self._group

    def get_identifiers(self) -> dict[str, str | int]:
        """Return a dict with the information necessary to identify this entity."""
        return {
            "unique_id": self.unique_id,
            "platform": self.PLATFORM,
            "group_id": self.group.group_id,
        }

    def update(self, _: Any | None = None) -> None:
        """Update the state of this group entity."""

    def send_event(self, signal: dict[str, Any]) -> None:
        """Broadcast an event from this group entity."""
        signal["platform_entity"] = {
            "name": self._name,
            "unique_id": self._unique_id,
            "platform": self.PLATFORM,
        }
        signal["group"] = {
            "id": self._group.group_id,
        }
        _LOGGER.info("Sending event from group entity: %s", signal)
        self._group.send_event(signal)

    def to_json(self) -> dict[str, Any]:
        """Return a JSON representation of the group."""
        json = super().to_json()
        json["name"] = self._name
        json["group_id"] = self.group_id
        return json
