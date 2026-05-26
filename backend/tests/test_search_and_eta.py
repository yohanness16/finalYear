"""Tests for search ETA and bus data in responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_point_to_point_response_structure(client: AsyncClient):
    """Point-to-point should return buses array alongside etas."""
    with (
        patch("app.api.v1.search.crud_route") as mock_route,
        patch("app.api.v1.search.crud_vehicle") as mock_vehicle,
        patch("app.api.v1.search.get_redis") as mock_redis,
    ):
        mock_route.get_stop_by_id = AsyncMock(
            side_effect=[
                type("Stop", (), {"id": 1, "name": "Stop A"})(),
                type("Stop", (), {"id": 2, "name": "Stop B"})(),
            ]
        )
        mock_route.get_routes_through_stops = AsyncMock(
            return_value=[type("Route", (), {"id": 1, "route_number": "12"})()]
        )
        mock_vehicle.get_live_positions = AsyncMock(
            return_value={
                "1": {
                    "vehicle_id": 1,
                    "plate_number": "ABC-123",
                    "lat": 9.03,
                    "lon": 38.74,
                    "route_id": 1,
                }
            }
        )
        redis_mock = AsyncMock()
        redis_mock.hgetall = AsyncMock(
            return_value={
                "eta_seconds": "120",
                "bus_plate": "ABC-123",
                "vehicle_id": "1",
            }
        )
        mock_redis.return_value = redis_mock

        resp = await client.post(
            "/api/v1/search/point-to-point",
            json={
                "start_stop_id": 1,
                "end_stop_id": 2,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "routes" in data
        assert len(data["routes"]) == 1
        assert "buses" in data["routes"][0]
        assert "etas" in data["routes"][0]


@pytest.mark.asyncio
async def test_eta_payload_includes_bus_plate():
    """ETA payload dict should contain bus_plate and vehicle_id."""
    from app.services.route_eta import estimate_route_stop_eta_payloads

    mock_stop = MagicMock()
    mock_stop.id = 42
    mock_stop.name = "Test Stop"
    mock_stop.lat = 9.03
    mock_stop.lon = 38.74
    mock_stop.base_dwell_time = 30
    mock_stop.peak_multiplier = 1.0

    payloads = estimate_route_stop_eta_payloads(
        lat=9.03,
        lon=38.74,
        speed_kmh=30.0,
        occupancy_level=1,
        route_number="12",
        route_id=1,
        route_stops=[mock_stop],
        plate_number="ABC-123",
        vehicle_id=5,
    )
    assert 42 in payloads
    assert payloads[42]["bus_plate"] == "ABC-123"
    assert payloads[42]["vehicle_id"] == "5"
