from unittest.mock import AsyncMock

import pytest

from app.services.websocket import ConnectionManager


@pytest.mark.asyncio
async def test_websocket_manager_lifecycle():
    manager = ConnectionManager()
    mock_ws = AsyncMock()

    # Test Connect
    await manager.connect(mock_ws)
    assert mock_ws in manager.active_connections
    mock_ws.accept.assert_called_once()

    # Test Broadcast
    message = {"type": "bus_update", "data": "test"}
    await manager.broadcast(message)
    mock_ws.send_json.assert_called_with(message)

    # Test Disconnect
    manager.disconnect(mock_ws)
    assert mock_ws not in manager.active_connections


@pytest.mark.asyncio
async def test_broadcast_error_handling():
    manager = ConnectionManager()
    bad_ws = AsyncMock()
    bad_ws.send_json.side_effect = Exception("Connection lost")

    await manager.connect(bad_ws)
    # Broadcast must not crash; failed sends drop stale sockets
    await manager.broadcast({"test": "data"})
    assert bad_ws not in manager.active_connections
    assert len(manager.active_connections) == 0
