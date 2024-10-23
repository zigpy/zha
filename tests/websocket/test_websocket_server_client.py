"""Tests for the server and client."""

from __future__ import annotations

from zha.application.gateway import WebSocketServerGateway
from zha.application.helpers import ZHAData
from zha.websocket.client.client import Client
from zha.websocket.client.controller import Controller
from zha.websocket.server.gateway_api import StopServerCommand


async def test_server_client_connect_disconnect(
    zha_data: ZHAData,
) -> None:
    """Tests basic connect/disconnect logic."""

    async with WebSocketServerGateway(zha_data) as gateway:
        assert gateway.is_serving
        assert gateway._ws_server is not None

        async with Client(f"ws://localhost:{zha_data.server_config.port}") as client:
            assert client.connected
            assert "connected" in repr(client)

            # The client does not begin listening immediately
            assert client._listen_task is None
            await client.listen()
            assert client._listen_task is not None

        # The listen task is automatically stopped when we disconnect
        assert client._listen_task is None
        assert "not connected" in repr(client)
        assert not client.connected

    assert not gateway.is_serving
    assert gateway._ws_server is None


async def test_client_message_id_uniqueness(
    connected_client_and_server: tuple[Controller, WebSocketServerGateway],
) -> None:
    """Tests that client message IDs are unique."""
    controller, _ = connected_client_and_server

    ids = [controller.client.new_message_id() for _ in range(1000)]
    assert len(ids) == len(set(ids))


async def test_client_stop_server(
    connected_client_and_server: tuple[Controller, WebSocketServerGateway],
) -> None:
    """Tests that the client can stop the server."""
    controller, gateway = connected_client_and_server

    assert gateway.is_serving
    await controller.client.async_send_command_no_wait(StopServerCommand())
    await controller.disconnect()
    await gateway.wait_closed()
    assert not gateway.is_serving
