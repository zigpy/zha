"""Shared models for ZHA."""

from collections.abc import Callable
from enum import Enum
import logging
from typing import Any, Literal, Optional, Union

from pydantic import (
    BaseModel as PydanticBaseModel,
    ConfigDict,
    field_serializer,
    field_validator,
)
from zigpy.types.named import EUI64, NWK

_LOGGER = logging.getLogger(__name__)


def convert_ieee(ieee: Optional[Union[str, EUI64]]) -> Optional[EUI64]:
    """Convert ieee to EUI64."""
    if ieee is None:
        return None
    if isinstance(ieee, str):
        return EUI64.convert(ieee)
    return ieee


def convert_nwk(nwk: Optional[Union[int, NWK]]) -> Optional[NWK]:
    """Convert int to NWK."""
    if isinstance(nwk, int) and not isinstance(nwk, NWK):
        return NWK(nwk)
    return nwk


def convert_enum(enum_type: Enum) -> Callable[[str | Enum], Enum]:
    """Convert enum name to enum instance."""

    def _convert_enum(enum_name_or_instance: str | Enum) -> Enum:
        """Convert extended_pan_id to ExtendedPanId."""
        if isinstance(enum_name_or_instance, str):
            return enum_type(enum_name_or_instance)  # type: ignore
        return enum_name_or_instance

    return _convert_enum


def convert_int(zigpy_type: type) -> Any:
    """Convert int to zigpy type."""

    def _convert_int(value: int) -> Any:
        """Convert int to zigpy type."""
        return zigpy_type(value)

    return _convert_int


class BaseModel(PydanticBaseModel):
    """Base model for ZHA models."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    _convert_ieee = field_validator(
        "ieee", "device_ieee", mode="before", check_fields=False
    )(convert_ieee)

    _convert_nwk = field_validator(
        "nwk", "dest_nwk", "next_hop", mode="before", check_fields=False
    )(convert_nwk)

    @field_serializer("ieee", "device_ieee", check_fields=False)
    def serialize_ieee(self, ieee: EUI64):
        """Customize how ieee is serialized."""
        return str(ieee)


class BaseEvent(BaseModel):
    """Base model for ZHA events."""

    message_type: Literal["event"] = "event"
    event_type: str
    event: str
