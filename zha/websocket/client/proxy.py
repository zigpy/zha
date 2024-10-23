"""Proxy object for the client side objects."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from zha.application.platforms.model import (
    BasePlatformEntity,
    EntityStateChangedEvent,
    GroupEntity,
)
from zha.event import EventBase
from zha.zigbee.model import ExtendedDeviceInfo, GroupInfo

if TYPE_CHECKING:
    from zha.websocket.client.client import Client
    from zha.websocket.client.controller import Controller


class BaseProxyObject(EventBase, abc.ABC):
    """BaseProxyObject for the zhaws.client."""

    def __init__(self, controller: Controller, client: Client):
        """Initialize the BaseProxyObject class."""
        super().__init__()
        self._controller: Controller = controller
        self._client: Client = client
        self._proxied_object: GroupInfo | ExtendedDeviceInfo

    @property
    def controller(self) -> Controller:
        """Return the controller."""
        return self._controller

    @property
    def client(self) -> Client:
        """Return the client."""
        return self._client

    @abc.abstractmethod
    def _get_entity(
        self, event: EntityStateChangedEvent
    ) -> BasePlatformEntity | GroupEntity:
        """Get the entity for the event."""

    def emit_platform_entity_event(self, event: EntityStateChangedEvent) -> None:
        """Proxy the firing of an entity event."""
        entity = self._get_entity(event)
        if entity is None:
            if isinstance(self._proxied_object, ExtendedDeviceInfo):  # type: ignore
                raise ValueError(
                    f"Entity not found: {event.platform_entity.unique_id}",
                )
            return  # group entities are updated to get state when created so we may not have the entity yet
        entity.state = event.state
        self.emit(f"{event.unique_id}_{event.event}", event)


class GroupProxy(BaseProxyObject):
    """Group proxy for the zhaws.client."""

    def __init__(self, group_model: GroupInfo, controller: Controller, client: Client):
        """Initialize the GroupProxy class."""
        super().__init__(controller, client)
        self._proxied_object: GroupInfo = group_model

    @property
    def group_model(self) -> GroupInfo:
        """Return the group model."""
        return self._proxied_object

    @group_model.setter
    def group_model(self, group_model: GroupInfo) -> None:
        """Set the group model."""
        self._proxied_object = group_model

    def _get_entity(self, event: EntityStateChangedEvent) -> GroupEntity:
        """Get the entity for the event."""
        return self._proxied_object.entities.get(event.unique_id)  # type: ignore

    def __repr__(self) -> str:
        """Return the string representation of the group proxy."""
        return self._proxied_object.__repr__()


class DeviceProxy(BaseProxyObject):
    """Device proxy for the zhaws.client."""

    def __init__(
        self, device_model: ExtendedDeviceInfo, controller: Controller, client: Client
    ):
        """Initialize the DeviceProxy class."""
        super().__init__(controller, client)
        self._proxied_object: ExtendedDeviceInfo = device_model

    @property
    def device_model(self) -> ExtendedDeviceInfo:
        """Return the device model."""
        return self._proxied_object

    @device_model.setter
    def device_model(self, device_model: ExtendedDeviceInfo) -> None:
        """Set the device model."""
        self._proxied_object = device_model

    @property
    def device_automation_triggers(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Return the device automation triggers."""
        model_triggers = self._proxied_object.device_automation_triggers
        return {
            (key.split("~")[0], key.split("~")[1]): value
            for key, value in model_triggers.items()
        }

    def _get_entity(self, event: EntityStateChangedEvent) -> BasePlatformEntity:
        """Get the entity for the event."""
        return self._proxied_object.entities.get((event.platform, event.unique_id))  # type: ignore

    def __repr__(self) -> str:
        """Return the string representation of the device proxy."""
        return self._proxied_object.__repr__()
