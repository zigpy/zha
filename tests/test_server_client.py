"""Tests for the server and client."""
from __future__ import annotations

from zhaws.client.client import Client
from zhaws.client.controller import Controller
from zhaws.server.config.model import ServerConfiguration
from zhaws.server.websocket.server import Server, StopServerCommand


async def test_server_client_connect_disconnect(
    server_configuration: ServerConfiguration,
) -> None:
    """Tests basic connect/disconnect logic."""

    async with Server(configuration=server_configuration) as server:
        assert server.is_serving
        assert server._ws_server is not None

        async with Client(f"ws://localhost:{server_configuration.port}") as client:
            assert client.connected
            assert "connected" in repr(client)

            # The client does not begin listening immediately
            assert client._listen_task is None
            await client.listen()
            assert client._listen_task is not None

        # The listen task is automatically stopped when we disconnect
        assert client._listen_task is None  # type: ignore
        assert "not connected" in repr(client)
        assert not client.connected

    assert not server.is_serving  # type: ignore
    assert server._ws_server is None


async def test_client_message_id_uniqueness(
    connected_client_and_server: tuple[Controller, Server]
) -> None:
    """Tests that client message IDs are unique."""
    controller, server = connected_client_and_server

    ids = [controller.client.new_message_id() for _ in range(1000)]
    assert len(ids) == len(set(ids))


async def test_client_stop_server(
    connected_client_and_server: tuple[Controller, Server]
) -> None:
    """Tests that the client can stop the server."""
    controller, server = connected_client_and_server

    assert server.is_serving
    await controller.client.async_send_command_no_wait(StopServerCommand())
    await controller.disconnect()
    await server.wait_closed()
    assert not server.is_serving
