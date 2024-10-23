"""Type information for the websocket api module."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from zha.websocket.server.api.model import WebSocketCommand

T_WebSocketCommand = TypeVar("T_WebSocketCommand", bound=WebSocketCommand)

AsyncWebSocketCommandHandler = Callable[
    [Any, Any, T_WebSocketCommand], Coroutine[Any, Any, None]
]
WebSocketCommandHandler = Callable[[Any, Any, T_WebSocketCommand], None]
