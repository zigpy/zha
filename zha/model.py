"""Shared models for ZHA."""

import logging
from typing import Literal, Optional, Union

from pydantic import (
    BaseModel as PydanticBaseModel,
    ConfigDict,
    field_serializer,
    field_validator,
)
from zigpy.types.named import EUI64, NWK

_LOGGER = logging.getLogger(__name__)


class BaseModel(PydanticBaseModel):
    """Base model for ZHA models."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    @field_validator("ieee", "device_ieee", mode="before", check_fields=False)
    @classmethod
    def convert_ieee(cls, ieee: Optional[Union[str, EUI64]]) -> Optional[EUI64]:
        """Convert ieee to EUI64."""
        if ieee is None:
            return None
        if isinstance(ieee, str):
            return EUI64.convert(ieee)
        return ieee

    @field_validator("nwk", mode="before", check_fields=False)
    @classmethod
    def convert_nwk(cls, nwk: Optional[Union[int, NWK]]) -> Optional[NWK]:
        """Convert int to NWK."""
        if isinstance(nwk, int) and not isinstance(nwk, NWK):
            return NWK(nwk)
        return nwk

    @field_serializer("ieee", "device_ieee", check_fields=False)
    def serialize_ieee(self, ieee: EUI64):
        """Customize how ieee is serialized."""
        return str(ieee)


class BaseEvent(BaseModel):
    """Base model for ZHA events."""

    message_type: Literal["event"] = "event"
    event_type: str
    event: str
