from unittest.mock import AsyncMock, patch

import pytest

from app.utils.redis_client import bus_live_key, set_bus_live


@pytest.mark.asyncio
async def test_bus_keys():
    assert bus_live_key("ABC-123") == "bus:live:ABC-123"


@pytest.mark.asyncio
@patch("app.utils.redis_client.get_redis")
async def test_set_bus_live_calls_redis(mock_get_redis):
    # Setup mock redis client
    mock_client = AsyncMock()
    mock_get_redis.return_value = mock_client

    await set_bus_live(
        plate_number="TEST-1",
        lat=9.0,
        lon=38.0,
        speed=25.0,
        occupancy_level=1,
        assignment_id=10,
    )

    # Verify hset was called with the correct mapping
    mock_client.hset.assert_called_once()
    args, kwargs = mock_client.hset.call_args
    assert kwargs["mapping"]["speed"] == "25.0"
