"""Websocket api platform module for zha."""

from __future__ import annotations

from typing import Union

from zigpy.types.named import EUI64

from zha.application.platforms import Platform
from zha.websocket.server.api.model import WebSocketCommand


class PlatformEntityCommand(WebSocketCommand):
    """Base class for platform entity commands."""

    ieee: Union[EUI64, None] = None
    group_id: Union[int, None] = None
    unique_id: str
    platform: Platform
