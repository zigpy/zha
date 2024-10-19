"""Proxy object for the client side objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zha.event import EventBase
from zha.websocket.client.model.events import PlatformEntityStateChangedEvent
from zha.websocket.client.model.types import (
    ButtonEntity,
    Device as DeviceModel,
    Group as GroupModel,
)

if TYPE_CHECKING:
    from zha.websocket.client.client import Client
    from zha.websocket.client.controller import Controller


class BaseProxyObject(EventBase):
    """BaseProxyObject for the zhaws.client."""

    def __init__(self, controller: Controller, client: Client):
        """Initialize the BaseProxyObject class."""
        super().__init__()
        self._controller: Controller = controller
        self._client: Client = client
        self._proxied_object: GroupModel | DeviceModel

    @property
    def controller(self) -> Controller:
        """Return the controller."""
        return self._controller

    @property
    def client(self) -> Client:
        """Return the client."""
        return self._client

    def emit_platform_entity_event(
        self, event: PlatformEntityStateChangedEvent
    ) -> None:
        """Proxy the firing of an entity event."""
        entity = self._proxied_object.entities.get(
            f"{event.platform_entity.platform}.{event.platform_entity.unique_id}"
            if event.group is None
            else event.platform_entity.unique_id
        )
        if entity is None:
            if isinstance(self._proxied_object, DeviceModel):
                raise ValueError(
                    f"Entity not found: {event.platform_entity.unique_id}",
                )
            return  # group entities are updated to get state when created so we may not have the entity yet
        if not isinstance(entity, ButtonEntity):
            entity.state = event.state
        self.emit(f"{event.platform_entity.unique_id}_{event.event}", event)


class GroupProxy(BaseProxyObject):
    """Group proxy for the zhaws.client."""

    def __init__(self, group_model: GroupModel, controller: Controller, client: Client):
        """Initialize the GroupProxy class."""
        super().__init__(controller, client)
        self._proxied_object: GroupModel = group_model

    @property
    def group_model(self) -> GroupModel:
        """Return the group model."""
        return self._proxied_object

    @group_model.setter
    def group_model(self, group_model: GroupModel) -> None:
        """Set the group model."""
        self._proxied_object = group_model

    def __repr__(self) -> str:
        """Return the string representation of the group proxy."""
        return self._proxied_object.__repr__()


class DeviceProxy(BaseProxyObject):
    """Device proxy for the zhaws.client."""

    def __init__(
        self, device_model: DeviceModel, controller: Controller, client: Client
    ):
        """Initialize the DeviceProxy class."""
        super().__init__(controller, client)
        self._proxied_object: DeviceModel = device_model

    @property
    def device_model(self) -> DeviceModel:
        """Return the device model."""
        return self._proxied_object

    @device_model.setter
    def device_model(self, device_model: DeviceModel) -> None:
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

    def __repr__(self) -> str:
        """Return the string representation of the device proxy."""
        return self._proxied_object.__repr__()
