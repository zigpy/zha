"""Models for the ZHA cluster handlers module."""

from enum import StrEnum
from typing import Any, Literal

from zha.model import BaseEvent, BaseModel


class ClusterHandlerStatus(StrEnum):
    """Status of a cluster handler."""

    CREATED = "created"
    CONFIGURED = "configured"
    INITIALIZED = "initialized"


class ClusterAttributeUpdatedEvent(BaseEvent):
    """Event to signal that a cluster attribute has been updated."""

    attribute_id: int
    attribute_name: str
    attribute_value: Any
    cluster_handler_unique_id: str
    cluster_id: int
    event_type: Literal["cluster_handler_event"] = "cluster_handler_event"
    event: Literal["cluster_handler_attribute_updated"] = (
        "cluster_handler_attribute_updated"
    )


class ClusterBindEvent(BaseEvent):
    """Event generated when the cluster is bound."""

    cluster_name: str
    cluster_id: int
    success: bool
    cluster_handler_unique_id: str
    event_type: Literal["zha_channel_message"] = "zha_channel_message"
    event: Literal["zha_channel_bind"] = "zha_channel_bind"


class ClusterConfigureReportingEvent(BaseEvent):
    """Event generates when a cluster configures attribute reporting."""

    cluster_name: str
    cluster_id: int
    attributes: dict[str, dict[str, Any]]
    cluster_handler_unique_id: str
    event_type: Literal["zha_channel_message"] = "zha_channel_message"
    event: Literal["zha_channel_configure_reporting"] = (
        "zha_channel_configure_reporting"
    )


class ClusterInfo(BaseModel):
    """Cluster information."""

    id: int
    name: str
    type: str
    endpoint_id: int
    endpoint_attribute: str | None = None


class ClusterHandlerInfo(BaseModel):
    """Cluster handler information."""

    class_name: str
    generic_id: str
    endpoint_id: int
    cluster: ClusterInfo
    id: str
    unique_id: str
    status: ClusterHandlerStatus
    value_attribute: str | None = None


class LevelChangeEvent(BaseEvent):
    """Event to signal that a cluster attribute has been updated."""

    level: int
    event: str
    event_type: Literal["cluster_handler_event"] = "cluster_handler_event"
